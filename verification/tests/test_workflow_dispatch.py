"""Exercise the actual privileged workflow body with synthetic OIDC/STS only."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import textwrap
import unittest
import urllib.parse
import urllib.error
from unittest.mock import Mock, patch


WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/verify-bank.yml'


class WorkflowDispatchTests(unittest.TestCase):
    def setUp(self):
        self.account = '123456789012'
        self.role = 'arn:aws:iam::123456789012:role/peer-link-invoke-test'
        self.arn = 'arn:aws:lambda:us-east-1:123456789012:function:peer-link-test:3'
        self.env = {'AWS_ACCOUNT': self.account, 'INVOKE_ROLE': self.role,
                    'CONTROLLER': self.arn, 'APPROVAL_ID': 'a' * 32,
                    'GITHUB_RUN_ID': '123', 'PATH': os.environ['PATH'],
                    'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://pipelines.actions.githubusercontent.com/token?api-version=2',
                    'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'synthetic-request-token',
                    'AWS_ACCESS_KEY_ID': 'old-key', 'AWS_SECRET_ACCESS_KEY': 'old-secret',
                    'AWS_ENDPOINT_URL': 'https://untrusted.invalid'}
        self.identity = {'AssumedRoleUser': {'Arn': 'arn:aws:sts::123456789012:assumed-role/peer-link-invoke-test/peer-link-123'},
                         'Credentials': {'AccessKeyId': 'ASIASYNTHETIC',
                                         'SecretAccessKey': 'syntheticSecret',
                                         'SessionToken': 'syntheticSession'}}
        self.result = {'approvalId': 'a' * 32, 'instanceId': 'i-0123456789abcdef0',
                       'artifactDigest': 'b' * 64, 'releaseDigest': 'c' * 64,
                       'reservedMicroUsd': 2000000, 'expiresAt': 1000,
                       'bankSessionAccepted': False}
        source = WORKFLOW.read_text().split('      - name: Invoke pinned trusted controller', 1)[1]
        self.code = textwrap.dedent(source.split("python3 - <<'PY'\n", 1)[1].rsplit('          PY', 1)[0])
        self.stdout = io.StringIO()
        self.response = Mock()
        self.response.__enter__ = Mock(return_value=self.response)
        self.response.__exit__ = Mock(return_value=False)
        self.response.read.return_value = json.dumps({'value': 'synthetic.oidc.token'}).encode()
        self.opener = Mock()
        self.opener.open.side_effect = self.http
        self.sts_error = None

    def http(self, request, **kwargs):
        if request.full_url.startswith('https://pipelines.actions.githubusercontent.com/'):
            self.assertIn('audience=sts.amazonaws.com', request.full_url)
            return self.response
        self.assertEqual(request.full_url, 'https://sts.us-east-1.amazonaws.com/')
        payload = urllib.parse.parse_qs(request.data.decode())
        self.assertEqual(payload['RoleArn'], [self.role])
        self.assertEqual(payload['DurationSeconds'], ['900'])
        self.assertEqual(payload['WebIdentityToken'], ['synthetic.oidc.token'])
        self.assertEqual(payload['Action'], ['AssumeRoleWithWebIdentity'])
        if self.sts_error:
            raise self.sts_error
        credentials = ''.join('<'+k+'>'+v+'</'+k+'>' for k, v in self.identity['Credentials'].items())
        raw = ('<AssumeRoleWithWebIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
               '<AssumeRoleWithWebIdentityResult><AssumedRoleUser><Arn>'
               + self.identity['AssumedRoleUser']['Arn'] + '</Arn></AssumedRoleUser><Credentials>'
               + credentials + '</Credentials></AssumeRoleWithWebIdentityResult></AssumeRoleWithWebIdentityResponse>')
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = raw.encode()
        return response

    def aws(self, args, **kwargs):
        self.assertNotIn('synthetic.oidc.token', str(args))
        self.assertNotIn('AWS_ENDPOINT_URL', kwargs['env'])
        self.assertNotIn('ACTIONS_ID_TOKEN_REQUEST_TOKEN', kwargs['env'])
        self.assertEqual(kwargs['env']['AWS_MAX_ATTEMPTS'], '1')
        self.assertEqual(args[1:3], ['lambda', 'invoke'])
        self.assertEqual(args[args.index('--function-name') + 1], self.arn)
        self.assertEqual(json.loads(args[args.index('--payload') + 1]), {'approvalId': 'a' * 32})
        self.assertEqual(kwargs['env']['AWS_ACCESS_KEY_ID'], 'ASIASYNTHETIC')
        Path(args[-1]).write_text(json.dumps(self.result))
        return subprocess.CompletedProcess(args, 0, '{}', '')

    def execute(self):
        with patch.dict(os.environ, self.env, clear=True), contextlib.redirect_stdout(self.stdout), \
                patch('urllib.request.build_opener', return_value=self.opener), \
                patch('subprocess.run', side_effect=self.aws) as process:
            exec(compile(self.code, str(WORKFLOW), 'exec'), {})
            return process

    def test_approval_only_invocation_and_credentials_stay_in_process(self):
        process = self.execute()
        self.assertEqual(process.call_count, 1)
        self.assertEqual(self.opener.open.call_count, 2)
        self.assertEqual(json.loads(self.stdout.getvalue()), self.result)
        for secret in ('synthetic.oidc.token', 'syntheticSecret', 'syntheticSession', 'synthetic-request-token'):
            self.assertNotIn(secret, self.stdout.getvalue())

    def test_wrong_account_alias_role_or_endpoint_never_requests_token(self):
        for key, value in [('AWS_ACCOUNT', '999999999999'),
                           ('CONTROLLER', self.arn.rsplit(':', 1)[0] + ':latest'),
                           ('INVOKE_ROLE', self.role.replace('peer-link-invoke-test', 'production')),
                           ('APPROVAL_ID', 'credentials'),
                           ('ACTIONS_ID_TOKEN_REQUEST_URL', 'https://actions.githubusercontent.com.attacker.invalid/token')]:
            with self.subTest(key=key), patch.dict(self.env, {key: value}):
                with self.assertRaises(SystemExit):
                    self.execute()
        self.opener.open.assert_not_called()

    def test_wrong_assumed_identity_never_invokes_controller(self):
        self.identity['AssumedRoleUser']['Arn'] = 'arn:aws:sts::999999999999:assumed-role/peer-link-invoke-test/peer-link-123'
        with patch.dict(os.environ, self.env, clear=True), \
                patch('urllib.request.build_opener', return_value=self.opener), \
                patch('subprocess.run', side_effect=self.aws) as process, self.assertRaises(SystemExit):
            exec(compile(self.code, str(WORKFLOW), 'exec'), {})
        process.assert_not_called()

    def test_controller_error_or_extra_data_is_not_logged(self):
        for result in ({'error': 'secret-diagnostic'}, {**self.result, 'session': 'secret-diagnostic'}):
            with self.subTest(result=result):
                self.result = result
                with self.assertRaises(SystemExit):
                    self.execute()
        self.assertEqual(self.stdout.getvalue(), '')

    def test_sts_failure_is_redacted_and_never_retried(self):
        self.sts_error = urllib.error.URLError('sensitive-token')
        with patch.dict(os.environ, self.env, clear=True), \
                patch('urllib.request.build_opener', return_value=self.opener), \
                patch('subprocess.run') as process, self.assertRaises(SystemExit) as caught:
            exec(compile(self.code, str(WORKFLOW), 'exec'), {})
        self.assertNotIn('sensitive-token', str(caught.exception))
        process.assert_not_called()
        self.assertEqual(self.opener.open.call_count, 2)
