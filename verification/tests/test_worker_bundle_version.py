"""Keep resource-policy grants from widening the approved bundle version."""
import unittest

from verification.infra.manual_template import template


class WorkerBundleVersionTests(unittest.TestCase):
    def test_version_pin_has_an_explicit_complementary_deny(self):
        statements = template()['Resources']['HostRole']['Properties']['Policies'][0]['PolicyDocument']['Statement']
        grants = [s for s in statements if s['Effect'] == 'Allow' and s.get('Action') == 's3:GetObjectVersion']
        self.assertEqual(len(grants), 1)
        grant = grants[0]
        self.assertEqual(grant['Condition'], {'StringEquals': {'s3:VersionId': {'Ref': 'ArtifactVersion'}}})
        # The deny must cover the same object and parameter as the grant. Without
        # it an additional bucket policy can allow an old or unreviewed version.
        # StringNotEquals also denies when the context key is absent.
        self.assertIn({
            'Effect': 'Deny',
            'Action': 's3:GetObjectVersion',
            'Resource': grant['Resource'],
            'Condition': {'StringNotEquals': grant['Condition']['StringEquals']},
        }, statements)


if __name__ == '__main__':
    unittest.main()
