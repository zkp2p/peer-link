"""CLI admission must succeed before any owner secret input, using synthetic data."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock,patch
from transcripts.cli import main
from transcripts.common import Rejected


class CliAdmissionTests(unittest.TestCase):
    def run_cli(self, directory, *, failure=None, save_failure=False):
        state_path=Path(directory)/'job.json'
        client=Mock();client.job=None
        events=[];payload={'credential':{'origin':'https://api.wise.com','kind':'bearer'},
                           'profileId':None,'recipe':{'version':1,'reads':[]},'notes':'','transcript':[]}
        stdin=Mock()
        def read(_):
            self.assertTrue(state_path.exists())
            events.append('input');return json.dumps(payload).encode()
        stdin.buffer.read.side_effect=read
        def reserve(*_,on_reserved,**__):
            events.append('reserve')
            if failure:raise Rejected(failure)
            client.job={'jobId':'a'*32,'bindingDigest':'b'*64}
            if save_failure:
                # A racing writer appears after the CLI's initial exists check.
                state_path.write_text('existing public recovery handle')
            on_reserved(client.job)
            events.append('saved')
        client.reserve.side_effect=reserve
        def prompt(value):
            self.assertTrue(state_path.exists());events.append('prompt')
            value['credential']['value']='SYNTHETIC-BANK'
            value['inferenceKey']='SYNTHETIC-INFERENCE'
        def submit(value,**_):
            self.assertEqual(value['inferenceKey'],'SYNTHETIC-INFERENCE')
            events.append('submit');return {'state':'unverified'}
        client.submit_reserved.side_effect=submit
        argv=['transcripts.cli','contribute','--campaign',json.loads((Path(__file__).parents[1]/'policy.json').read_text())['campaigns'][0]['id'],
              '--payout','0x'+'1'*40,'--provider','near','--model','z-ai/glm-5.3-flash',
              '--consent','--prompt-secrets','--state',str(state_path)]
        output=io.StringIO()
        with patch('sys.argv',argv),patch('sys.stdin',stdin),patch('transcripts.cli.Client',return_value=client),\
                patch('transcripts.cli.prompt_secrets',side_effect=prompt),redirect_stdout(output):
            if failure or save_failure:
                with self.assertRaises(SystemExit):main()
            else:main()
        self.assertNotIn('SYNTHETIC-',output.getvalue())
        return events,stdin,client,output.getvalue(),state_path

    def test_reserve_and_save_before_input_and_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            events,_,_,_,path=self.run_cli(directory)
            self.assertEqual(events,['reserve','saved','input','prompt','submit'])
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertNotIn('SYNTHETIC-',path.read_text())

    def test_campaign_full_never_reads_or_prompts_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            events,stdin,client,output,path=self.run_cli(directory,failure='campaign_capacity')
            self.assertEqual(events,['reserve']);stdin.buffer.read.assert_not_called()
            client.submit_reserved.assert_not_called();self.assertFalse(path.exists())
            self.assertEqual(json.loads(output)['error'],'campaign_capacity')

    def test_recovery_file_race_never_reads_or_prompts_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            events,stdin,client,output,path=self.run_cli(directory,save_failure=True)
            self.assertEqual(events,['reserve']);stdin.buffer.read.assert_not_called()
            client.submit_reserved.assert_not_called()
            self.assertEqual(path.read_text(),'existing public recovery handle')
            self.assertEqual(json.loads(output)['nextAction'],'poll_same_job_do_not_resubmit')


if __name__=='__main__':unittest.main()

class CliReservedTests(unittest.TestCase):
    def run_reserved(self,*,reported='reserved',expired=False,extra=(),consent=True):
        import copy
        from transcripts.client import DEFAULT_LIMITS
        from transcripts.common import canonical
        clock=2000
        state={'version':2,'jobId':'a'*32,'bindingDigest':'b'*64,'campaignId':json.loads((Path(__file__).parents[1]/'policy.json').read_text())['campaigns'][0]['id'],
               'request':{'expiresAt':clock-1 if expired else clock+60,'payoutAddress':'0x'+'2'*40,
                          'provider':'near','model':'z-ai/glm-5.3-flash','privacyMode':'provider_visible',
                          'limits':DEFAULT_LIMITS.copy()}}
        events=[];client=Mock();client.job=None
        def restore(value):client.job=copy.deepcopy(value);events.append('restore')
        client.restore.side_effect=restore
        def status(job):
            self.assertEqual(job,state['jobId']);events.append('fresh_status')
            return {'state':'unverified','reportedState':reported}
        client.status.side_effect=status
        stdin=Mock()
        def read(_):events.append('input');return canonical({'credential':{'origin':'https://api.wise.com','kind':'bearer'},
            'profileId':None,'recipe':{'version':1,'reads':[]},'notes':'','transcript':{}})
        stdin.buffer.read.side_effect=read
        def prompt(payload):
            events.append('prompt');payload['credential']['value']='SYNTHETIC-BANK';payload['inferenceKey']='SYNTHETIC-MODEL'
        def submit(payload,*,consent):
            self.assertTrue(consent);self.assertEqual(payload['inferenceKey'],'SYNTHETIC-MODEL')
            self.assertEqual(client.job,state);events.append('submit');return {'state':'unverified','reportedState':'submitted'}
        client.submit_reserved.side_effect=submit
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'job.json';path.write_bytes(canonical(state));path.chmod(0o600)
            before=path.read_bytes();output=io.StringIO()
            argv=['transcripts.cli','submit-reserved','--state',str(path),'--prompt-secrets',*extra]
            if consent:argv.append('--consent')
            with patch('sys.argv',argv),patch('sys.stdin',stdin),patch('transcripts.cli.time.time',return_value=clock),\
                    patch('transcripts.cli.Client',return_value=client),patch('transcripts.cli.prompt_secrets',side_effect=prompt),\
                    patch('transcripts.cli.save_state') as save,redirect_stdout(output):
                try:main()
                except SystemExit as error:self.assertEqual(error.code,1)
            self.assertEqual(path.read_bytes(),before);self.assertEqual(path.stat().st_mode&0o777,0o600)
            save.assert_not_called();client.reserve.assert_not_called()
            self.assertNotIn('SYNTHETIC-',output.getvalue());self.assertNotIn('SYNTHETIC-',path.read_text())
            return events,client,stdin,output.getvalue(),state

    def test_existing_reserved_job_continues_without_reservation_or_state_overwrite(self):
        events,client,_,output,state=self.run_reserved(extra=('--job-id','a'*32))
        self.assertEqual(events,['restore','fresh_status','input','prompt','submit'])
        client.restore.assert_called_once_with(state);client.submit_reserved.assert_called_once()
        preview=json.loads(output.splitlines()[0])
        self.assertEqual(preview['payoutAddress'],state['request']['payoutAddress'])
        self.assertEqual(preview['model'],state['request']['model']);self.assertEqual(preview['rewardMinor'],json.loads((Path(__file__).parents[1]/'policy.json').read_text())['campaigns'][0]['rewardMinor'])

    def test_nonreserved_jobs_reject_before_read_or_prompt(self):
        for status in ('submitted','verifying','accepted','payout_pending','paid','rejected','expired','cancelled'):
            with self.subTest(status=status):
                events,client,stdin,output,_=self.run_reserved(reported=status)
                self.assertEqual(events,['restore','fresh_status']);stdin.buffer.read.assert_not_called()
                client.submit_reserved.assert_not_called();self.assertEqual(json.loads(output)['error'],'job_replayed')

    def test_expired_job_and_wrong_job_id_reject_before_secrets(self):
        for kwargs,code in [({'expired':True},'job_expired'),({'extra':('--job-id','c'*32)},'job_context_required')]:
            events,client,stdin,output,_=self.run_reserved(**kwargs)
            self.assertEqual(events,['restore']);client.status.assert_not_called();stdin.buffer.read.assert_not_called()
            client.submit_reserved.assert_not_called();self.assertEqual(json.loads(output)['error'],code)

    def test_privacy_override_rejected_before_secret_input(self):
        events,client,stdin,output,_=self.run_reserved(extra=('--privacy','confidential'))
        self.assertEqual(events,['restore','fresh_status']);stdin.buffer.read.assert_not_called()
        client.submit_reserved.assert_not_called();self.assertEqual(json.loads(output)['error'],'unexpected_arguments')

    def test_original_terms_cannot_be_overridden_and_fresh_consent_required(self):
        for kwargs,code in [({'extra':('--payout','0x'+'3'*40)},'unexpected_arguments'),
                            ({'extra':('--model','other-model')},'unexpected_arguments'),
                            ({'consent':False},'consent_required')]:
            events,client,stdin,output,_=self.run_reserved(**kwargs)
            self.assertEqual(events,[]);client.restore.assert_not_called();stdin.buffer.read.assert_not_called()
            client.submit_reserved.assert_not_called();self.assertEqual(json.loads(output)['error'],code)
