"""Host-only synthetic supervision/metrics/CF checks; no hardware or AWS calls."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from transcripts.infra import health_publisher as publisher
from transcripts.infra import supervise_enclave as supervisor
from transcripts.infra.template import template

INSTANCE = 'i-0123456789abcdef0'
ID = INSTANCE + '-encabc'
RECORD = {'EnclaveID': ID, 'EnclaveCID': 16}


class Stop:
    def __init__(self):
        self.calls = 0
    def is_set(self):
        return False
    def wait(self, timeout):
        self.calls += 1
        return self.calls > 1


class ContinuousTests(unittest.TestCase):
    def run_supervisor(self, runner, health=lambda: {}, stop=None, notify=lambda: None):
        with tempfile.TemporaryDirectory() as directory, patch.object(supervisor, 'policy_at', return_value={}), patch.object(supervisor, 'checked_health', side_effect=lambda h, p, paused: h):
            supervisor.supervise(directory, INSTANCE, Path(directory)/'record', stop or Stop(),
                                 run=runner, health=health, notify=notify, startup_timeout=0)

    def test_unknown_enclave_never_adopted_or_terminated(self):
        calls = []
        def run(*args):
            calls.append(args)
            return [{'EnclaveID': 'unrelated'}]
        with self.assertRaises(ValueError):
            self.run_supervisor(run)
        self.assertEqual(calls, [('describe-enclaves',)])

    def test_exact_liveness_failure_cleans_only_launched_id(self):
        calls = []
        def run(*args):
            calls.append(args)
            if args[0] == 'run-enclave':
                return RECORD
            return []
        with self.assertRaises(ValueError):
            self.run_supervisor(run)
        self.assertEqual(calls[-1], ('terminate-enclave', '--enclave-id', ID))
        self.assertFalse(any('--all' in c for c in calls))

    def test_healthy_enclave_ready_then_clean_shutdown_only_own_id(self):
        calls, notified = [], []
        def run(*args):
            calls.append(args)
            if args[0] == 'run-enclave':
                return RECORD
            if args[0] == 'describe-enclaves' and len(calls) > 2:
                return [{**RECORD, 'State': 'RUNNING', 'Flags': 'NONE', 'NumberOfCPUs': 2, 'MemoryMiB': 2048}]
            return []
        self.run_supervisor(run, notify=lambda: notified.append(1))
        self.assertEqual(notified, [1])
        self.assertEqual(calls[-1], ('terminate-enclave', '--enclave-id', ID))

    def test_health_startup_failure_terminates_exact_id_without_ready(self):
        calls, notifications = [], []
        def run(*args):
            calls.append(args)
            return RECORD if args[0] == 'run-enclave' else []
        def unavailable():
            raise ValueError('private exception must stay private')
        with self.assertRaisesRegex(ValueError, '^supervisor_failed$'):
            self.run_supervisor(run, health=unavailable, notify=lambda: notifications.append(1))
        self.assertEqual(notifications, [])
        self.assertEqual(calls[-1], ('terminate-enclave', '--enclave-id', ID))

    def test_metric_failure_emits_only_fixed_numeric_metadata(self):
        def private_error():
            raise RuntimeError('secret request data')
        metrics = publisher.sample({}, INSTANCE, private_error)
        self.assertEqual([x['Value'] for x in metrics], [0, 0])
        self.assertNotIn('secret', json.dumps(metrics))
        with patch.object(publisher, 'checked_health', return_value={'accepting': False}):
            self.assertEqual([x['Value'] for x in publisher.sample({}, INSTANCE, lambda: {})], [1, 0])

    def test_metric_cli_cannot_inherit_credentials_or_endpoint_overrides(self):
        bad = {'AWS_SECRET_ACCESS_KEY': 'private', 'AWS_PROFILE': 'other',
               'AWS_ENDPOINT_URL_CLOUDWATCH': 'https://bad', 'AWS_CA_BUNDLE': '/bad',
               'AWS_EC2_METADATA_SERVICE_ENDPOINT': 'http://bad', 'HTTPS_PROXY': 'http://bad'}
        with patch.dict(os.environ, bad):
            clean = publisher.role_environment()
        self.assertFalse(any(key in clean for key in bad))
        self.assertEqual(clean['AWS_SHARED_CREDENTIALS_FILE'], '/dev/null')
        with patch.object(publisher.subprocess, 'run') as run:
            publisher.publish(publisher.sample({}, INSTANCE, lambda: {}), 'us-east-1')
        args, kwargs = run.call_args
        self.assertIn('https://monitoring.us-east-1.amazonaws.com', args[0])
        self.assertEqual(kwargs['timeout'], 20)
        self.assertTrue(kwargs['capture_output'])

    def test_finite_guard_default_and_continuous_only_metrics_iam(self):
        value = template()
        self.assertEqual(value['Parameters']['ContinuousServiceEnabled']['Default'], 'false')
        r = value['Resources']
        self.assertEqual(r['ExpirySchedule']['Properties']['State']['Fn::If'], ['IsContinuous', 'DISABLED', 'ENABLED'])
        self.assertEqual(r['ExpiryNotRunning']['Condition'], 'IsFinitePilot')
        self.assertEqual(r['Host']['Properties']['InstanceType'], 'c6i.xlarge')
        self.assertEqual(r['Host']['Properties']['BlockDeviceMappings'][0]['Ebs']['VolumeSize'], 32)
        policy = r['HostRole']['Properties']['Policies'][0]['PolicyDocument']
        encoded = json.dumps(policy)
        self.assertNotIn('dynamodb:', encoded)
        self.assertNotIn('"kms:Encrypt"', encoded)
        self.assertIn('kms:RecipientAttestation:ImageSha384', encoded)
        grants = [x['Fn::If'][1] for x in policy['Statement'] if 'Fn::If' in x and x['Fn::If'][0] == 'IsContinuous']
        self.assertEqual({g['Effect'] for g in grants}, {'Allow', 'Deny'})
        self.assertTrue(all(g['Resource'] == '*' and g['Action'] == 'cloudwatch:PutMetricData' for g in grants))
        self.assertEqual(r['RuntimeHealthAlarm']['Properties']['TreatMissingData'], 'breaching')
        self.assertEqual(r['AdmissionsOpenAlarm']['Properties']['DatapointsToAlarm'], 3)
        self.assertFalse(any(resource['Type'] == 'AWS::SNS::Subscription' for resource in r.values()))


if __name__ == '__main__':
    unittest.main()
