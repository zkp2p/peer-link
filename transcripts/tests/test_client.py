"""Synthetic contributor recovery and trust-boundary tests; no live services."""
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from transcripts.artifacts import extract_artifact
from transcripts.channel import Channel
from transcripts.client import Client
from transcripts.cli import main,prompt_secrets,save_state,terms
from transcripts.common import Rejected, canonical, digest
from transcripts.tests.test_core import campaign, read, NOW
from transcripts.tests.test_artifacts import kms_descriptor,kms_policy
from verification.common import b64


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ephemeral test-only key, never a banking/inference/payout credential.
        cls.channel=Channel()

    def setUp(self):
        self.policy=kms_policy(campaign())
        self.release={'status':'approved','serviceUrl':'https://synthetic.invalid',
                      'expiresAt':NOW+10000,'policyDigest':digest(self.policy)}
        self.clock=patch('transcripts.client.time.time',return_value=NOW);self.clock.start()
        self.client=Client(self.release['serviceUrl'],self.release,self.policy)
        self.epoch=kms_descriptor()
        self.responses=[];self.sent=[];self.reservation=None;self.receipt_record=None
        self.verify=patch('transcripts.client.verify_document',side_effect=self.verify_quote);self.verify.start()
        self.calls=patch.object(self.client,'call',side_effect=self.call);self.calls.start()

    def tearDown(self):self.calls.stop();self.verify.stop();self.clock.stop()

    def verify_quote(self,document,*,nonce,public_key_der,release):
        # Synthetic quote binds this unit test's context exactly. This is not an
        # AWS signature substitute; existing verifier tests own that boundary.
        self.assertEqual(document,nonce)
        self.assertEqual(public_key_der,self.channel.public_key_der)
        self.assertEqual(release,self.release)

    def quote(self,context):
        return {'context':context,'publicKey':b64(self.channel.public_key_der),
                'attestation':b64(hashlib.sha256(canonical(context)).digest())}

    def call(self,path,body=None):
        self.sent.append(path)
        if path=='/v1/attest':
            return self.quote({'protocol':'peerlink-epoch-v1','nonce':body['nonce'],
                               'policyDigest':digest(self.policy),'epoch':self.epoch})
        if path=='/v1/reservations':
            self.reservation=copy.deepcopy(body);job_id='a'*32
            return {'jobId':job_id,'campaignId':body['campaignId'],'state':'reserved',
                    'bindingDigest':digest({'jobId':job_id,'campaign':self.policy['campaigns'][0],'request':body}),
                    'expiresAt':body['expiresAt'],'rewardMinor':10000000,'payoutAddress':body['payoutAddress'].lower(),
                    'reason':None,'artifactDigest':None,'transactionId':None}
        if path=='/v1/challenges':
            return self.quote({'protocol':'peerlink-transcript-v1','jobId':body['jobId'],
                'bindingDigest':digest({'jobId':body['jobId'],'campaign':self.policy['campaigns'][0],'request':self.reservation}),
                'policyDigest':digest(self.policy),'epochId':self.epoch['epochId'],'wallet':self.epoch['payoutWallet'],
                'nonce':'c'*64,'clientNonce':body['nonce'],'expiresAt':NOW+120})
        if path=='/v1/submissions':
            if self.responses:
                value=self.responses.pop(0)
                if isinstance(value,Exception):raise value
                return value
            return self.status_record('submitted')
        if path.endswith('/receipt'):return self.channel.sign(copy.deepcopy(self.receipt_record))
        if path.startswith('/v1/jobs/'):return self.status_record('paid' if '/v1/submissions' in self.sent else 'reserved')
        raise AssertionError(path)

    def status_record(self,state):
        job=self.client.job
        return {'jobId':job['jobId'],'campaignId':job['campaignId'],'state':state,
                'bindingDigest':job['bindingDigest'],'expiresAt':job['request']['expiresAt'],'rewardMinor':10000000,
                'payoutAddress':job['request']['payoutAddress'].lower(),'reason':None,'artifactDigest':None,'transactionId':None}

    def contribute(self,**kwargs):
        return self.client.contribute('synthetic-bank-v1','0x'+'1'*40,'synthetic','synthetic-model',
                                     'provider_visible',{'credential':{'value':'SYNTHETIC-PRIVATE-BANK'},
                                                         'inferenceKey':'SYNTHETIC-PRIVATE-INFERENCE'},consent=True,**kwargs)

    def record(self):
        artifact=extract_artifact(self.policy['campaigns'][0],[read(self.client.job['jobId'])])
        grade={'rubricVersion':'rubric-v1','score':90,'useful':True}
        job=self.status_record('paid');job['artifactDigest']=digest(artifact);job['transactionId']='0x'+'d'*64
        return {'version':1,'epoch':self.epoch,'job':job,'artifact':artifact,'modelResult':grade,
                'inference':{'requestDigest':'d'*64,'responseDigest':digest(grade),'provider':'synthetic',
                             'model':'synthetic-model','privacyMode':'provider_visible','inputTokens':10,'outputTokens':10},
                'policyDigest':digest(self.policy)}

    def test_unreleased_precedes_service_configuration(self):
        with self.assertRaisesRegex(Rejected,'release_not_approved'):
            Client(None,{'status':'unreleased','serviceUrl':None,'expiresAt':0},self.policy)

    def test_reservation_binds_default_completion_budget_without_extra_calls(self):
        self.contribute()
        self.assertEqual(self.reservation['limits'],{'maxCalls':1,'maxInputTokens':50000,
                         'maxOutputTokens':2048,'maxBankReads':10,'deadlineSeconds':120})
        self.assertEqual(self.client.job['request']['limits'],self.reservation['limits'])

    def test_fixed_http_errors_preserved_without_raw_error_text(self):
        client=Client(self.release['serviceUrl'],self.release,self.policy)
        for code,expected in [('campaign_capacity','campaign_capacity'),('budget_exhausted','budget_exhausted'),
                              ('SYNTHETIC-PRIVATE-ERROR','service_unavailable')]:
            error=urllib.error.HTTPError(client.service,400,'synthetic',{},io.BytesIO(canonical({'error':code})))
            with patch('urllib.request.OpenerDirector.open',side_effect=error):
                with self.assertRaisesRegex(Rejected,'^'+expected+'$'):client.call('/v1/reservations',{})

    def test_submission_timeout_retains_public_handle_before_submission(self):
        self.responses=[Rejected('service_unavailable')];saved=[]
        with self.assertRaisesRegex(Rejected,'service_unavailable'):self.contribute(on_reserved=lambda value:saved.append(value))
        self.assertEqual(len(saved),1);self.assertEqual(saved[0],self.client.job)
        self.assertEqual(self.sent.count('/v1/submissions'),1)
        self.assertNotIn('SYNTHETIC-PRIVATE',canonical(saved[0]).decode())
        with self.assertRaisesRegex(Rejected,'job_context_exists'):self.contribute()

    def test_unsigned_submission_cannot_claim_payment(self):
        def fake_submit(path,body=None):
            if path=='/v1/submissions':return self.status_record('paid')
            return self.call(path,body)
        with patch.object(self.client,'call',side_effect=fake_submit):result=self.contribute()
        self.assertEqual(result['state'],'unverified');self.assertFalse(result['verified'])
        self.assertEqual(result['nextAction'],'verify_receipt')

    def test_unsigned_submission_wrong_job_rejected(self):
        def fake_submit(path,body=None):
            result=self.call(path,body)
            if path=='/v1/submissions':result['jobId']='b'*32
            return result
        with patch.object(self.client,'call',side_effect=fake_submit):
            with self.assertRaisesRegex(Rejected,'binding_mismatch'):self.contribute()
        self.assertEqual(self.client.job['jobId'],'a'*32)

    def test_restored_context_requires_fresh_same_epoch_and_key(self):
        self.contribute();state=copy.deepcopy(self.client.job)
        restored=Client(self.release['serviceUrl'],self.release,self.policy);restored.restore(state)
        with self.assertRaisesRegex(Rejected,'preflight_required'):restored.receipt(state['jobId'])
        with patch.object(restored,'call',side_effect=self.call):restored.preflight()
        self.epoch={**self.epoch,'epochId':'f'*32}
        with patch.object(restored,'call',side_effect=self.call):
            with self.assertRaisesRegex(Rejected,'enclave_restarted'):restored.preflight()

    def test_restore_rejects_changed_terms_and_path_job_ids(self):
        self.contribute();state=copy.deepcopy(self.client.job)
        for candidate in [dict(state,jobId='../health'),dict(state,bindingDigest='f'*64)]:
            with self.assertRaisesRegex(Rejected,'state_mismatch'):
                Client(self.release['serviceUrl'],self.release,self.policy).restore(candidate)

    def test_receipt_requires_original_terms_and_safe_artifact(self):
        self.contribute();self.receipt_record=self.record()
        signed=self.client.receipt(self.client.job['jobId']);self.assertEqual(signed['payload']['job']['state'],'paid')
        modifications=[('job','bindingDigest','f'*64),('job','artifactDigest','f'*64),
                       ('job','payoutAddress','0x'+'2'*40),
                       ('inference','outputTokens',self.reservation['limits']['maxOutputTokens']+1),
                       ('inference','responseDigest','f'*64),('modelResult','privateProse','SYNTHETIC-PRIVATE')]
        for section,field,value in modifications:
            with self.subTest(field=field):
                self.receipt_record=self.record();self.receipt_record[section][field]=value
                with self.assertRaises(Rejected):self.client.receipt(self.client.job['jobId'])

    def test_poll_only_reports_paid_after_valid_signed_receipt(self):
        self.contribute();self.receipt_record=self.record()
        result=self.client.status(self.client.job['jobId'])
        self.assertEqual(result['state'],'paid');self.assertTrue(result['verified'])
        self.receipt_record['job']['bindingDigest']='f'*64
        with self.assertRaisesRegex(Rejected,'receipt_mismatch'):self.client.status(self.client.job['jobId'])

    def test_paid_host_status_cannot_upgrade_an_accepted_signed_receipt(self):
        self.contribute();self.receipt_record=self.record()
        self.receipt_record['job'].update(state='accepted',transactionId=None)
        result=self.client.status(self.client.job['jobId'])
        self.assertEqual(result['state'],'accepted');self.assertTrue(result['verified'])

    def test_invalid_signature_never_reports_paid(self):
        self.contribute();self.receipt_record=self.record()
        original=self.channel.sign
        def invalid(record):
            signed=original(record);signed['signature']=b64(b'wrong-signature');return signed
        with patch.object(self.channel,'sign',side_effect=invalid):
            with self.assertRaisesRegex(Rejected,'receipt_signature_invalid'):self.client.status(self.client.job['jobId'])

    def test_public_state_never_overwrites_and_is_private_permissions(self):
        self.contribute()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'job.json';save_state(path,self.client.job)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertEqual(json.loads(path.read_text()),self.client.job)
            with self.assertRaises(FileExistsError):save_state(path,self.client.job)

    def test_cli_validates_consent_and_arguments_before_reading_stdin(self):
        for flags,expected in [([], 'consent_required'),(['--consent'],'missing_arguments')]:
            output=io.StringIO();stdin=unittest.mock.Mock()
            with patch('sys.argv',['transcripts.cli','contribute',*flags]),patch('sys.stdin',stdin),\
                    patch('transcripts.cli.Client',return_value=self.client),redirect_stdout(output):
                with self.assertRaises(SystemExit):main()
            self.assertEqual(json.loads(output.getvalue())['error'],expected)
            stdin.buffer.read.assert_not_called()

    def test_cli_timeout_prints_recovery_and_saves_no_secrets(self):
        self.policy['campaigns'][0]['inferenceRoutes'][0]['provider']='openai'
        self.release['policyDigest']=digest(self.policy)
        self.client=Client(self.release['serviceUrl'],self.release,self.policy)
        self.responses=[Rejected('service_unavailable')]
        payload=b'{"credential":{"value":"SYNTHETIC-PRIVATE-BANK"},"inferenceKey":"SYNTHETIC-PRIVATE-INFERENCE"}'
        with tempfile.TemporaryDirectory() as directory:
            state_path=Path(directory)/'job.json';output=io.StringIO()
            policy_path=Path(directory)/'policy.json';policy_path.write_text(json.dumps(self.policy))
            release_path=Path(directory)/'release.json';release_path.write_text(json.dumps(self.release))
            argv=['transcripts.cli','contribute','--campaign','synthetic-bank-v1','--payout','0x'+'1'*40,
                  '--provider','openai','--model','synthetic-model','--consent','--state',str(state_path),
                  '--policy',str(policy_path),'--release',str(release_path)]
            with patch('sys.argv',argv),patch('sys.stdin',io.TextIOWrapper(io.BytesIO(payload))),\
                    patch('transcripts.cli.Client',return_value=self.client),\
                    patch.object(self.client,'call',side_effect=self.call),redirect_stdout(output):
                with self.assertRaises(SystemExit):main()
            messages=[json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(messages[0]['event'],'reserved')
            self.assertEqual(messages[-1]['nextAction'],'poll_same_job_do_not_resubmit')
            self.assertEqual(messages[-1]['jobId'],messages[0]['jobId'])
            self.assertNotIn('SYNTHETIC-PRIVATE',state_path.read_text()+output.getvalue())

    def test_offline_terms_work_unreleased_without_key_or_network(self):
        output=io.StringIO()
        with patch('sys.argv',['transcripts.cli','terms','--campaign','wise-api-public-v1',
                              '--provider','openrouter','--model','openai/gpt-4o-mini-2024-07-18']),\
                patch('transcripts.cli.Client') as client,patch('transcripts.cli.getpass.getpass') as secret,redirect_stdout(output):
            main()
        result=json.loads(output.getvalue())
        self.assertFalse(result['accepting']);self.assertEqual(result['reason'],'release_not_approved')
        self.assertEqual(result['rewardUSDC'],5);self.assertEqual(result['provider'],'openrouter')
        self.assertEqual(result['upstream'],'OpenAI');self.assertEqual(result['privacyMode'],'provider_visible')
        self.assertEqual(result['payout']['chainId'],8453)
        self.assertEqual(result['payout']['contract'],'0x833589fcd6edb6e08f4c7c32d4f71b54bda02913')
        self.assertEqual(result['defaultLimits']['maxInputTokens'],50000)
        self.assertFalse(result['guaranteedDollarCap']);client.assert_not_called();secret.assert_not_called()

    def test_preflight_exposes_independently_pinned_release_digest_and_measurements(self):
        self.release['measurements']={str(i):'f'*96 for i in (0,1,2,8)}
        result=self.client.preflight()
        self.assertEqual(result['releaseDigest'],digest(self.release))
        self.assertEqual(result['measurements'],self.release['measurements'])

    def test_preflight_rejects_custody_mismatch_before_credentials_or_reservation(self):
        original=copy.deepcopy(self.epoch)
        for name,value in [('version',1),('payoutKeyCustody','enclave_only'),
                           ('payoutKeyId',original['payoutKeyId'].replace('11111111-','22222222-',1)),
                           ('payoutWallet','0x'+'3'*40),('operatorRecovery',False),
                           ('restartRequiresOperatorReview',False),('ledgerPersistence','persistent')]:
            self.epoch=dict(original,**{name:value});self.sent=[]
            with self.subTest(name=name),self.assertRaises(Rejected):self.contribute()
            self.assertFalse(self.client.preflight_verified)
            self.assertNotIn('/v1/reservations',self.sent);self.assertNotIn('/v1/submissions',self.sent)
        self.epoch=original

    def test_local_handle_cannot_substitute_kms_custody(self):
        self.contribute();state=copy.deepcopy(self.client.job)
        state['epoch']['payoutKeyId']=state['epoch']['payoutKeyId'].replace('11111111-','22222222-',1)
        restored=Client(self.release['serviceUrl'],self.release,self.policy)
        with self.assertRaises(Rejected):restored.restore(state)
        self.assertIsNone(restored.job);self.assertFalse(restored.preflight_verified)

    def test_preflight_rejects_unmeasured_budget_before_reservation(self):
        self.policy['pilotBudgetMinor']=5_000_000
        self.release['policyDigest']=digest(self.policy)
        self.client=Client(self.release['serviceUrl'],self.release,self.policy)
        with patch.object(self.client,'call',side_effect=self.call):
            with self.assertRaisesRegex(Rejected,'epoch_mismatch'):self.contribute()
            self.assertNotIn('/v1/reservations',self.sent)
            self.epoch['budgetMinor']=5_000_000
            self.assertEqual(self.client.preflight()['epoch']['budgetMinor'],5_000_000)

    def prompt_payload(self):
        return {'credential':{'origin':'https://api.wise.com','kind':'bearer'},'profileId':None,
                'recipe':{'version':1,'reads':[]},'notes':'','transcript':[]}

    def test_owner_prompt_secret_values_only_enter_memory(self):
        payload=self.prompt_payload();terminal=unittest.mock.MagicMock();terminal.isatty.return_value=True
        output=io.StringIO()
        import sys
        original_stdin=sys.stdin
        with patch('transcripts.cli.open',return_value=terminal,create=True),\
                patch('transcripts.cli.getpass.getpass',side_effect=['SYNTHETIC-PRIVATE-BANK','SYNTHETIC-PRIVATE-INFERENCE']) as secret,\
                redirect_stdout(output):
            terminal.__enter__.return_value=terminal;prompt_secrets(payload)
        self.assertEqual(payload['credential']['value'],'SYNTHETIC-PRIVATE-BANK')
        self.assertEqual(payload['inferenceKey'],'SYNTHETIC-PRIVATE-INFERENCE')
        self.assertEqual(output.getvalue(),'');self.assertIs(sys.stdin,original_stdin)
        self.assertEqual(secret.call_count,2)
        self.assertTrue(all(call.kwargs['stream'] is terminal for call in secret.call_args_list))

    def test_owner_prompt_refuses_existing_keys_and_missing_tty(self):
        payload=self.prompt_payload();payload['credential']['value']='SYNTHETIC-PRIVATE-BANK'
        with patch('transcripts.cli.getpass.getpass') as secret:
            with self.assertRaises(Rejected):prompt_secrets(payload)
            secret.assert_not_called()
        payload=self.prompt_payload()
        with patch('transcripts.cli.open',side_effect=OSError('SYNTHETIC-PRIVATE-ERROR'),create=True),\
                patch('transcripts.cli.getpass.getpass') as secret:
            with self.assertRaisesRegex(Rejected,'^secret_prompt_unavailable$'):prompt_secrets(payload)
            secret.assert_not_called()

    def test_getpass_cannot_fall_back_to_recipe_stdin(self):
        payload=self.prompt_payload();terminal=unittest.mock.MagicMock();terminal.isatty.return_value=True
        terminal.__enter__.return_value=terminal
        import sys
        original_stdin=sys.stdin
        with patch('transcripts.cli.open',return_value=terminal,create=True),\
                patch('getpass.os.open',side_effect=OSError('no controlling tty')):
            with self.assertRaisesRegex(Rejected,'^secret_prompt_unavailable$'):prompt_secrets(payload)
        self.assertIs(sys.stdin,original_stdin)
        self.assertNotIn('value',payload['credential']);self.assertNotIn('inferenceKey',payload)

    def test_unreleased_never_reads_recipe_or_prompts_owner(self):
        output=io.StringIO();stdin=unittest.mock.Mock()
        with patch('sys.argv',['transcripts.cli','contribute','--prompt-secrets','--consent']),\
                patch('sys.stdin',stdin),patch('transcripts.cli.getpass.getpass') as secret,redirect_stdout(output):
            with self.assertRaises(SystemExit):main()
        self.assertEqual(json.loads(output.getvalue())['error'],'release_not_approved')
        stdin.buffer.read.assert_not_called();secret.assert_not_called()

    @unittest.skipUnless(os.name=='posix','Owner TTY mode requires POSIX')
    def test_real_owner_tty_hides_synthetic_keys(self):
        # Run the PTY harness in a fresh single-threaded subprocess; cryptography
        # or other test fixtures may have created threads in the test runner.
        child="""
from transcripts.cli import prompt_secrets
p={'credential':{'origin':'https://api.wise.com','kind':'bearer'},'profileId':None,
   'recipe':{'version':1,'reads':[]},'notes':'','transcript':[]}
prompt_secrets(p)
assert p['credential']['value']=='SYNTHETIC-TTY-BANK'
assert p['inferenceKey']=='SYNTHETIC-TTY-INFERENCE'
print('prompt-memory-ok',flush=True)
"""
        harness="""
import os,pty,select,sys,time
pid,descriptor=pty.fork()
if pid==0:os.execl(sys.executable,sys.executable,'-c',sys.argv[1])
output=b'';bank_sent=False;inference_sent=False;reaped=False
deadline=time.monotonic()+5
try:
    while time.monotonic()<deadline:
        if select.select([descriptor],[],[],0.1)[0]:
            try:chunk=os.read(descriptor,4096)
            except OSError:break
            if not chunk:break
            output+=chunk
            if b'Bank API token (owner only):' in output and not bank_sent:
                os.write(descriptor,b'SYNTHETIC-TTY-BANK\\n');bank_sent=True
            if b'Inference API key (owner only):' in output and not inference_sent:
                os.write(descriptor,b'SYNTHETIC-TTY-INFERENCE\\n');inference_sent=True
        if b'prompt-memory-ok' in output:
            waited,status=os.waitpid(pid,0);reaped=True
            assert os.waitstatus_to_exitcode(status)==0
            break
    assert b'prompt-memory-ok' in output
    assert b'SYNTHETIC-TTY-BANK' not in output
    assert b'SYNTHETIC-TTY-INFERENCE' not in output
    print('tty-no-echo-ok')
finally:
    os.close(descriptor)
    if not reaped:
        try:os.kill(pid,9)
        except ProcessLookupError:pass
        os.waitpid(pid,0)
"""
        completed=subprocess.run([sys.executable,'-c',harness,child],capture_output=True,timeout=10)
        self.assertEqual(completed.returncode,0,completed.stderr.decode())
        self.assertEqual(completed.stdout.strip(),b'tty-no-echo-ok')


    def test_terminal_report_has_terminal_hint_but_is_not_verified_payment(self):
        self.contribute()
        for state in ('rejected','expired','cancelled'):
            status=self.status_record(state);status['reason']='cancelled' if state=='cancelled' else 'job_expired'
            result=self.client.provisional(status)
            self.assertEqual(result['nextAction'],'terminal_outcome_reported')
            self.assertEqual(result['state'],'unverified');self.assertFalse(result['verified'])
    def test_missing_after_local_expiry_is_terminal_unknown_not_paid_claim(self):
        self.contribute();original=self.call
        def missing(path,body=None):
            if path.startswith('/v1/jobs/'):raise Rejected('job_not_found')
            return original(path,body)
        with patch.object(self.client,'call',side_effect=missing):
            with self.assertRaisesRegex(Rejected,'job_not_found'):self.client.status(self.client.job['jobId'])
            with patch('transcripts.client.time.time',return_value=NOW+601):
                result=self.client.status(self.client.job['jobId'])
        self.assertEqual(result['nextAction'],'terminal_record_unavailable')
        self.assertFalse(result['verified']);self.assertEqual(result['reportedState'],'unavailable_after_expiry')

if __name__=='__main__':unittest.main()
