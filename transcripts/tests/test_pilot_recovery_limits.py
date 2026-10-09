"""Existing 629b pilot mitigations, not automatic recovery fixes. No live calls."""
import copy
from unittest.mock import Mock,patch
from verification.common import b64
from transcripts.common import Rejected,canonical
from transcripts.eth_payout import BaseUSDCPayoutTransport
from transcripts.runtime import Runtime
from transcripts.tests.test_core import NOW,request
from transcripts.tests.test_core_eth_payout import SyntheticRPC
from transcripts.tests.test_durable import DurableFixture,SyntheticAWS
from transcripts.tests.test_runtime import FakeArchive,OPERATOR


class PilotRecoveryLimitTests(DurableFixture):
    def test_compound_bank_state_failure_releases_capacity_on_next_reservation_at_original_ttl(self):
        self.policy['campaigns'][0]['maxContributors']=1
        for bank_error in (Rejected('http_request_failed'),ValueError('synthetic bank parse failure')):
            with self.subTest(error=type(bank_error).__name__):
                self.aws=SyntheticAWS();epoch=self.epoch();cp=self.policy['campaigns'][0]
                original_request=request(cp,2)
                reserved=epoch.ledger.reserve(cp,original_request,NOW);job=reserved['jobId']
                epoch.ledger.submit(job,reserved['bindingDigest'],NOW+1)
                epoch._active=epoch._funded_once=True
                runtime=Runtime(self.policy,epoch,None,FakeArchive([]),attester=lambda *args:b'quote')
                bank=Mock()
                def fail(*args):
                    self.aws.outage=True
                    raise bank_error
                bank.acquire.side_effect=fail
                payload={'credential':{'value':'SYNTHETIC-BANK-SECRET'},'inferenceKey':'SYNTHETIC-INFERENCE-SECRET',
                         'profileId':None,'recipe':{},'notes':'','transcript':{}}
                runtime.jobs.acquire()
                with patch('transcripts.runtime.time.time',return_value=NOW+3),\
                        patch('transcripts.transport.BankClient',return_value=bank),\
                        patch('transcripts.providers.ProviderClient') as provider:
                    # The reviewed image retains this compound-failure limitation.
                    with self.assertRaisesRegex(Rejected,'state_unavailable'):runtime.process(job,payload)
                self.aws.outage=False
                self.assertEqual(epoch.ledger.status(job)['state'],'verifying')
                self.assertNotIn(job,runtime.deferred_jobs)
                self.assertEqual(original_request['expiresAt'],NOW+600)
                before=request(cp,3);before['expiresAt']=NOW+1199
                with self.assertRaisesRegex(Rejected,'campaign_capacity'):epoch.ledger.reserve(cp,before,NOW+599)
                after=request(cp,3);after['expiresAt']=NOW+1200
                fresh=epoch.ledger.reserve(cp,after,NOW+600)
                self.assertEqual(fresh['state'],'reserved');self.assertNotEqual(fresh['jobId'],job)
                with self.assertRaisesRegex(Rejected,'job_not_found'):epoch.ledger.status(job)
                bank.acquire.assert_called_once();bank.close.assert_called();provider.assert_not_called()
                self.assertEqual(payload,{})

    def test_signed_reconcile_rearchives_paid_restart_checkpoint_while_paused_without_replay(self):
        for checkpoint in ('absent','older_pending','paid'):
            with self.subTest(receipt_checkpoint=checkpoint):
                self.aws=SyntheticAWS()
                first=self.epoch();first.ledger.update_runtime({'fundedOnce':True});job=self.job(first)
                payment=BaseUSDCPayoutTransport(first,SyntheticRPC(),pinned_rpc_url=SyntheticRPC.endpoint)
                raw,tx=payment.sign(job,'0x'+f'{2:040x}',10_000_000)
                first.ledger.prepare_payout(job,raw,tx)
                saved=None
                if checkpoint=='older_pending':
                    saved=first.receipt_signer.sign(copy.deepcopy(first.ledger.archive_record(job)))
                    first.ledger.save_receipt(job,saved)
                first.ledger.mark_paid(job,tx,NOW+4)
                if checkpoint=='paid':
                    saved=first.receipt_signer.sign(copy.deepcopy(first.ledger.archive_record(job)))
                    first.ledger.save_receipt(job,saved)
                # Crash here: ledger says paid, but final receipt may not exist yet.
                second=self.epoch();archive=FakeArchive([])
                runtime=Runtime(self.policy,second,None,archive,attester=lambda *args:b'quote')
                self.assertFalse(second._active)
                self.assertEqual(runtime.dispatch('status',{'jobId':job})['state'],'paid')
                if saved is None:
                    with self.assertRaisesRegex(Rejected,'receipt_unavailable'):runtime.dispatch('receipt',{'jobId':job})
                else:
                    self.assertEqual(runtime.dispatch('receipt',{'jobId':job}),saved)
                    self.assertEqual(saved['payload']['job']['state'],'payout_pending' if checkpoint=='older_pending' else 'paid')
                self.assertEqual(archive.records,[]) # Polling does not automate this write.
                payload={'action':'reconcile','epochId':second.epoch_id,'wallet':second.wallet,'nonce':'e'*64,'expiresAt':NOW+90}
                body={'payload':payload,'signature':b64(OPERATOR.sign(canonical(payload)))}
                with patch('transcripts.runtime.time.time',return_value=NOW+5),patch('transcripts.runtime.threading.Thread') as thread:
                    health=runtime.operator(body)
                self.assertFalse(health['accepting']);thread.assert_called_once()
                worker=thread.call_args.kwargs['target']
                with patch('transcripts.transport.BankClient',side_effect=AssertionError('no bank replay')),\
                        patch('transcripts.providers.ProviderClient',side_effect=AssertionError('no model replay')),\
                        patch.object(runtime.payment,'sign',side_effect=AssertionError('no new payment signature')),\
                        patch.object(runtime.payment,'broadcast',side_effect=AssertionError('no broadcast')),\
                        patch.object(runtime.coordinator,'reconcile',side_effect=AssertionError('already paid')),\
                        patch.object(second.receipt_signer,'sign',wraps=second.receipt_signer.sign) as receipt_sign:
                    worker()
                final=runtime.dispatch('receipt',{'jobId':job})
                self.assertEqual(final['payload'],second.ledger.archive_record(job))
                self.assertEqual(final['payload']['job']['state'],'paid')
                self.assertEqual(final['payload']['job']['transactionId'],tx)
                self.assertEqual(receipt_sign.call_count,0 if checkpoint=='paid' else 1)
                if checkpoint=='paid':self.assertEqual(final,saved)
                self.assertEqual(archive.records,[final]);self.assertNotIn(job,runtime.pending_records)
                self.assertEqual(second.ledger.payout_identity(job),(raw,tx));self.assertFalse(second._active)
