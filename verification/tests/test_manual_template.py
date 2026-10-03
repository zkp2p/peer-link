"""Credential-free checks of the generated manual-controller stack and its reaper."""
import datetime
import os
import re
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

from verification.infra.manual_template import template


class SyntheticClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {'Error': {'Code': code}}


def actions(statement):
    value = statement.get('Action', [])
    return [value] if isinstance(value, str) else value


class ManualTemplateTests(unittest.TestCase):
    def setUp(self):
        self.stack = template()
        self.resources = self.stack['Resources']

    def test_worker_role_cannot_be_widened_by_shared_account_resource_policies(self):
        document = self.resources['HostRole']['Properties']['Policies'][0]['PolicyDocument']
        statements = document['Statement']
        allowed = sorted(a for s in statements if s['Effect'] == 'Allow' for a in actions(s))
        guard = [s for s in statements if s['Effect'] == 'Deny' and 'NotAction' in s]
        self.assertEqual(len(guard), 1)
        self.assertEqual(sorted(guard[0]['NotAction']), allowed)
        self.assertEqual(guard[0]['Resource'], '*')
        bundle = next(s['Resource'] for s in statements if actions(s) == ['s3:GetObjectVersion'])
        self.assertIn({'Effect': 'Deny', 'Action': 's3:*', 'NotResource': bundle}, statements)

    def test_ledger_is_protected_and_recoverable(self):
        ledger = self.resources['Ledger']
        self.assertEqual(ledger['DeletionPolicy'], 'Retain')
        self.assertTrue(ledger['Properties']['DeletionProtectionEnabled'])
        self.assertTrue(ledger['Properties']['PointInTimeRecoverySpecification']['PointInTimeRecoveryEnabled'])

    def test_existing_ledger_is_used_by_controller_reaper_and_roles(self):
        selected = {'Fn::If': ['CreateLedger', {'Ref': 'Ledger'}, {'Ref': 'LedgerTableName'}]}
        for name in ('Controller', 'Expiry'):
            self.assertEqual(self.resources[name]['Properties']['Environment']['Variables']['TABLE'], selected)
        for name in ('ControllerRole', 'ExpiryRole'):
            statements = self.resources[name]['Properties']['Policies'][0]['PolicyDocument']['Statement']
            ddb = [s for s in statements if any(a.startswith('dynamodb:') for a in actions(s))]
            self.assertEqual(len(ddb), 1)
            self.assertEqual(ddb[0]['Resource']['Fn::If'][0], 'CreateLedger')
        self.assertEqual(self.resources['Ledger']['Condition'], 'CreateLedger')

    def test_reaper_failure_and_silence_both_alarm_through_optional_route(self):
        pattern = self.stack['Parameters']['AlarmTopicArn']['AllowedPattern']
        self.assertTrue(re.fullmatch(pattern, ''))
        self.assertTrue(re.fullmatch(pattern, 'arn:aws:sns:us-east-1:123456789012:peer-link-alerts'))
        self.assertFalse(re.fullmatch(pattern, 'arn:aws:lambda:us-east-1:123456789012:function:x'))
        silent = self.resources['ExpiryNotRunning']['Properties']
        self.assertEqual(silent['TreatMissingData'], 'breaching')
        metric, expression = silent['Metrics']
        self.assertEqual(metric['MetricStat']['Metric'], {
            'Namespace': 'AWS/Lambda', 'MetricName': 'Invocations',
            'Dimensions': [{'Name': 'FunctionName', 'Value': {'Ref': 'Expiry'}}]})
        self.assertEqual((metric['MetricStat']['Period'], metric['MetricStat']['Stat']), (300, 'Sum'))
        self.assertFalse(metric['ReturnData'])
        self.assertEqual(expression, {'Id': 'heartbeat', 'Expression': 'FILL(invocations, 0)', 'ReturnData': True})
        self.assertEqual((silent['EvaluationPeriods'], silent['DatapointsToAlarm']), (3, 3))
        for name in ('ExpiryErrors', 'ExpiryNotRunning'):
            self.assertEqual(self.resources[name]['Properties']['AlarmActions']['Fn::If'][0], 'HasAlarmTopic')


class ReaperTests(unittest.TestCase):
    def run_reaper(self, lease=None, instances=(), lookup='terminated'):
        ec2, ddb = Mock(), Mock()
        ec2.exceptions.ClientError = SyntheticClientError

        def describe(**kwargs):
            if 'Filters' in kwargs:
                return {'Reservations': [{'Instances': list(instances)}] if instances else []}
            if isinstance(lookup, Exception):
                raise lookup
            return {'Reservations': [{'Instances': [{'State': {'Name': lookup}}]}]}

        ec2.describe_instances.side_effect = describe
        ddb.get_item.return_value = {'Item': lease} if lease else {}
        boto3 = types.ModuleType('boto3')
        boto3.client = {'ec2': ec2, 'dynamodb': ddb}.__getitem__
        code = template()['Resources']['Expiry']['Properties']['Code']['ZipFile']
        namespace = {}
        with patch.dict(sys.modules, {'boto3': boto3}), \
                patch.dict(os.environ, {'TABLE': 'synthetic-ledger', 'STACK_ID': 'synthetic-stack'}):
            exec(compile(code, 'expiry', 'exec'), namespace)
            namespace['handler']({}, None)
        return ec2, ddb

    def lease(self, expires_in):
        return {'id': {'S': 'active'}, 'approvalId': {'S': 'a' * 32}, 'instanceId': {'S': 'i-0123456789abcdef0'},
                'expiresAt': {'N': str(int(time.time() + expires_in))}}

    def instance(self, age, state='running'):
        launched = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age)
        return {'InstanceId': 'i-0123456789abcdef0', 'LaunchTime': launched, 'State': {'Name': state}}

    def test_unknown_instance_never_releases_a_live_lease(self):
        _, ddb = self.run_reaper(self.lease(3600), lookup=SyntheticClientError('InvalidInstanceID.NotFound'))
        ddb.delete_item.assert_not_called()

    def test_unknown_instance_after_lease_lifetime_releases_lease(self):
        _, ddb = self.run_reaper(self.lease(-1), lookup=SyntheticClientError('InvalidInstanceID.NotFound'))
        self.assertEqual(ddb.delete_item.call_args.kwargs['ConditionExpression'], 'approvalId = :approval')

    def test_other_lookup_errors_fail_closed(self):
        with self.assertRaises(SyntheticClientError):
            self.run_reaper(self.lease(-1), lookup=SyntheticClientError('UnauthorizedOperation'))

    def test_only_observed_termination_releases_before_expiry(self):
        _, ddb = self.run_reaper(self.lease(3600), lookup='terminated')
        ddb.delete_item.assert_called_once()
        _, ddb = self.run_reaper(self.lease(-1), lookup='shutting-down')
        ddb.delete_item.assert_not_called()

    def test_expired_or_stopped_workers_are_terminated_and_hold_the_lease(self):
        for worker in (self.instance(6601), self.instance(10, 'stopped')):
            with self.subTest(state=worker['State']['Name']):
                ec2, ddb = self.run_reaper(self.lease(-1), instances=[worker])
                ec2.terminate_instances.assert_called_once_with(InstanceIds=['i-0123456789abcdef0'])
                ddb.delete_item.assert_not_called()
        ec2, _ = self.run_reaper(self.lease(3600), instances=[self.instance(60)])
        ec2.terminate_instances.assert_not_called()


if __name__ == '__main__':
    unittest.main()
