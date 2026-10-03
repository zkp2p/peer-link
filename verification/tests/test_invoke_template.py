import re
import unittest

from verification.infra.invoke_template import template


class InvokeAuthorityTests(unittest.TestCase):
    def test_only_numeric_controller_version_can_be_selected(self):
        pattern = template()['Parameters']['ControllerVersionArn']['AllowedPattern']
        base = 'arn:aws:lambda:us-east-1:123456789012:function:peer-link-manual-launch'
        self.assertTrue(re.fullmatch(pattern, base + ':2'))
        for suffix in ('', ':$LATEST', ':production', ':0', ':01'):
            self.assertFalse(re.fullmatch(pattern, base + suffix))

    def test_trust_requires_exact_repository_environment_and_audience(self):
        role = template()['Resources']['Role']['Properties']
        trust = role['AssumeRolePolicyDocument']['Statement']
        self.assertEqual(len(trust), 1)
        self.assertEqual(trust[0]['Action'], 'sts:AssumeRoleWithWebIdentity')
        self.assertEqual(trust[0]['Condition'], {'StringEquals': {
            'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
            'token.actions.githubusercontent.com:sub':
                'repo:zkp2p/peer-link:environment:peer-link-verification',
        }})

    def test_resource_policy_cannot_widen_invocation_or_other_actions(self):
        role = template()['Resources']['Role']['Properties']
        statements = role['Policies'][0]['PolicyDocument']['Statement']
        self.assertEqual(statements, [
            {'Effect': 'Allow', 'Action': 'lambda:InvokeFunction',
             'Resource': {'Ref': 'ControllerVersionArn'}},
            {'Effect': 'Deny', 'NotAction': 'lambda:InvokeFunction', 'Resource': '*'},
            {'Effect': 'Deny', 'Action': 'lambda:InvokeFunction',
             'NotResource': {'Ref': 'ControllerVersionArn'}},
        ])


if __name__ == '__main__':
    unittest.main()
