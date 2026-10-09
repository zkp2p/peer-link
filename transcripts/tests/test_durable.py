"""Durable state safety with real crypto/authority, no AWS, bank, or chain calls."""
import copy
import hashlib
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from transcripts.aws_state import Authority,StateAnchor,MAX_CIPHERTEXT,Credentials,AWS
from transcripts.channel import Channel,ReceiptSigner,encrypt
from transcripts.common import Rejected,canonical,digest
from transcripts.epoch import BootEpoch
from transcripts.eth_payout import BaseUSDCPayoutTransport
from transcripts.artifacts import validate_epoch_descriptor
from transcripts.payout import PayoutCoordinator
from transcripts.runtime import Runtime
from transcripts.client import Client
from transcripts.tests.test_core import campaign,request,read,NOW
from transcripts.tests.test_core_epoch import synthetic_epoch
from transcripts.tests.test_core_eth_payout import SyntheticRPC,receipt,RECIPIENT
from transcripts.tests.test_state_authority import AtomicTable
from transcripts.infra.state_authority import Authority as HostAuthority
from transcripts.tests.test_artifacts import kms_policy
from transcripts.tests.test_runtime import FakeArchive,PUBLIC_OPERATOR
from transcripts.providers import SYSTEM_PROMPT
from verification.common import b64

CONFIG={'kind':'aws_lambda_dynamodb','region':'us-east-1',
        'functionArn':'arn:aws:lambda:us-east-1:000000000000:function:synthetic-authority:1',
        'namespace':'synthetic-public-state','wrappingKeyId':'arn:aws:kms:us-east-1:000000000000:key/22222222-2222-2222-2222-222222222222',
        'credentialRoleArn':'arn:aws:iam::000000000000:role/synthetic-host',
        'maxCiphertextBytes':MAX_CIPHERTEXT,'initialWalletNonce':7}

class SyntheticAWS:
    def __init__(self):
        self.table=AtomicTable();self.server=HostAuthority(self.table,'synthetic',CONFIG['namespace'])
        self.requests=[];self.outage=False;self.lose_ack=False
    def call(self,service,action,payload):
        assert service=='lambda' and action=='Invoke'
        self.requests.append(copy.deepcopy(payload))
        if self.outage:raise Rejected('state_unavailable')
        result=self.server.invoke(payload)
        if self.lose_ack and payload['action']!='load':
            self.lose_ack=False;raise Rejected('http_request_failed')
        return result

class DurableFixture(unittest.TestCase):
    def setUp(self):
        old=synthetic_epoch();self.signer=old._signer;old.close()
        self.policy=kms_policy(campaign(),wallet=self.signer.address.lower())
        self.policy['payoutAuthority']['keyId']=self.signer.key_id
        self.policy.update(stateAuthority=copy.deepcopy(CONFIG),operatorPublicKey=PUBLIC_OPERATOR,
                           promptDigest=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),payoutRpc=SyntheticRPC.endpoint)
        self.aws=SyntheticAWS();self.epochs=[]
    def tearDown(self):
        for epoch in self.epochs:
            try:epoch.close()
            except Exception:pass
    def epoch(self):
        authority=Authority(CONFIG,self.aws);head=authority.load()
        anchor=StateAnchor(CONFIG,digest(self.policy),self.signer.address.lower(),b'fixed-synthetic-master-key-0000000'[:32],
                           b'synthetic-KMS-wrapped-master',authority,head)
        snapshot=anchor.open(head) if head else None
        with patch('transcripts.epoch._require_nsm'),patch('transcripts.epoch.time.time',return_value=NOW+5):
            epoch=BootEpoch.create(self.signer,state_anchor=anchor,initial_snapshot=snapshot)
        self.epochs.append(epoch);return epoch
    def job(self,epoch,wallet=2,account='private-account-1',accept=True):
        cp=self.policy['campaigns'][0];req=request(cp,wallet)
        status=epoch.ledger.reserve(cp,req,NOW);job=status['jobId']
        epoch.ledger.submit(job,status['bindingDigest'],NOW+1);epoch.ledger.begin_verification(job,NOW+1)
        if accept:
            epoch._active=epoch._funded_once=True
            grade={'rubricVersion':'rubric-v1','score':90,'useful':True}
            evidence={'epoch':epoch.public_descriptor(),'modelResult':grade,'policyDigest':digest(self.policy),
                      'inference':{'requestDigest':'a'*64,'responseDigest':digest(grade),'provider':'synthetic',
                                   'model':'synthetic-model','privacyMode':'provider_visible','inputTokens':10,'outputTokens':10}}
            epoch.accept(job,[read(job,account)],grade,now=NOW+3,evidence=evidence,policy=self.policy)
        return job

class DurableStateTests(DurableFixture):
    def test_restart_recovers_reserved_accepted_pending_paid_receipts_and_dedup(self):
        first=self.epoch();first.ledger.update_runtime({'fundedOnce':True})
        accepted=self.job(first)
        pending=self.job(first,wallet=3,account='private-account-2')
        reserved=first.ledger.reserve(self.policy['campaigns'][0],request(self.policy['campaigns'][0],4),NOW)['jobId']
        transport=BaseUSDCPayoutTransport(first,SyntheticRPC(),pinned_rpc_url=SyntheticRPC.endpoint)
        signed,tx_id=transport.sign(pending,'0x'+f'{3:040x}',10_000_000)
        first.ledger.prepare_payout(pending,signed,tx_id)
        record=first.ledger.archive_record(accepted);first.ledger.save_receipt(accepted,first.receipt_signer.sign(record))
        second=self.epoch()
        self.assertEqual(second.epoch_id,first.epoch_id);self.assertFalse(second._active)
        self.assertEqual(second.receipt_signer.public_key_der,first.receipt_signer.public_key_der)
        self.assertEqual(second.ledger.status(reserved)['state'],'reserved')
        self.assertEqual(second.ledger.archive_record(accepted),record)
        self.assertEqual(second.ledger.payout_identity(pending),(signed,tx_id))
        restored=BaseUSDCPayoutTransport(second,SyntheticRPC(),pinned_rpc_url=SyntheticRPC.endpoint)
        self.assertEqual(restored._known[tx_id][0],signed)
        restored.check_continuity()
        duplicate=self.job(second,wallet=5,accept=False)
        with self.assertRaisesRegex(Rejected,'duplicate_account'):
            second.ledger.check_account(duplicate,[read(duplicate)],dedup_key=second._dedup_key,now=NOW+3)
        with self.assertRaisesRegex(Rejected,'state_rollback'):first.ledger.status(accepted)
        # Authoritative ciphertext stores neither personal bank values nor ingress key.
        cipher=bytes(self.aws.table.item['ciphertext']['B'])
        self.assertNotIn(b'private-account',cipher)
        self.assertNotIn('channelPrivateKey',canonical(second.ledger.runtime_state()).decode())

    def test_interrupted_jobs_expire_without_regrading_or_budget_leak(self):
        first=self.epoch();job=self.job(first,accept=False)
        second=self.epoch();status=second.ledger.status(job)
        self.assertEqual((status['state'],status['reason']),('rejected','interrupted_execution'))
        replacement=second.ledger.reserve(self.policy['campaigns'][0],request(self.policy['campaigns'][0]),NOW+6)
        self.assertNotEqual(replacement['jobId'],job)

    def test_lost_ack_exact_operation_recovers_and_capability_rejects_host_write(self):
        epoch=self.epoch();self.aws.lose_ack=True
        job=epoch.ledger.reserve(self.policy['campaigns'][0],request(self.policy['campaigns'][0]),NOW)
        mutations=[r for r in self.aws.requests if r['action']=='commit']
        self.assertEqual(mutations[-1]['revision'],1)
        bad=copy.deepcopy(mutations[-1]);bad.update(revision=2,expectedRevision=1,opId='f'*32,
            expectedCiphertextDigest=self.aws.server.load()['ciphertextDigest'],writeCapability='00'*32)
        self.assertEqual(self.aws.server.invoke(bad)['error'],'state_conflict')
        self.assertEqual(epoch.ledger.status(job['jobId'])['state'],'reserved')
        self.assertNotIn('writeCapability',str(self.aws.table.item))

    def test_uncertain_commit_retained_exactly_then_restored_not_rejected(self):
        epoch=self.epoch();self.aws.outage=True
        # Inject outage after the authentic read, at the first actual mutation.
        original=self.aws.call
        self.aws.outage=False
        def outage(service,action,payload):
            if payload['action']=='commit':self.aws.outage=True
            return original(service,action,payload)
        with patch.object(self.aws,'call',side_effect=outage),patch('transcripts.aws_state.time.sleep'):
            with self.assertRaisesRegex(Rejected,'state_commit_uncertain'):
                epoch.ledger.reserve(self.policy['campaigns'][0],request(self.policy['campaigns'][0]),NOW)
        self.assertIsNotNone(epoch.ledger._pending_snapshot)
        prepared=self.aws.requests[-2]
        self.aws.outage=False
        with self.assertRaisesRegex(Rejected,'duplicate_recipient'):
            epoch.ledger.reserve(self.policy['campaigns'][0],request(self.policy['campaigns'][0]),NOW)
        self.assertEqual(len(epoch.ledger.payment_rows()),1)
        commits=[r for r in self.aws.requests if r['action']=='commit']
        self.assertEqual(len({r['opId'] for r in commits}),1)
        self.assertEqual(len({r['ciphertext'] for r in commits}),1)
        self.assertIsNone(epoch.ledger._pending_snapshot)

    def test_policy_generation_and_aad_binding_fail_closed(self):
        first=self.epoch();head=copy.deepcopy(first._anchor.head)
        for field,value in [('revision',1),('writerGeneration',2),('lastOpId','f'*32)]:
            changed={**head,field:value}
            with self.assertRaisesRegex(Rejected,'state_integrity'):first._anchor.open(changed)
        wrong=StateAnchor(CONFIG,'f'*64,first.wallet,b'fixed-synthetic-master-key-0000000'[:32],
                          first._anchor.wrapped,first._anchor.authority,head)
        with self.assertRaisesRegex(Rejected,'state_integrity'):wrong.open(head)
        second=self.epoch()
        self.assertEqual(second._anchor.generation,2)
        with self.assertRaisesRegex(Rejected,'state_rollback'):first.ledger.update_runtime({'active':True})

    def test_operator_nonce_survives_and_storage_allowance_precedes_execution(self):
        first=self.epoch();first.ledger.consume_operator_nonce('a'*64,NOW+100,NOW)
        second=self.epoch()
        with self.assertRaisesRegex(Rejected,'operator_replayed'):second.ledger.consume_operator_nonce('a'*64,NOW+100,NOW+5)
        snapshot={**second.ledger._snapshot(),'mac':second.ledger._anchor_value()[1]}
        # Six live slots reserve their future 48KiB, even with tiny current bodies.
        cp=self.policy['campaigns'][0];req=request(cp)
        row={'campaign':canonical(cp).decode(),'request':canonical(req).decode(),'state':'reserved'}
        snapshot['jobs']=[copy.deepcopy(row) for _ in range(7)]
        with self.assertRaisesRegex(Rejected,'state_capacity'):second._anchor.capacity(snapshot)

    def test_nonce_conflict_and_broadcast_before_durable_signed_identity_reject(self):
        epoch=self.epoch();job=self.job(epoch)
        rpc=SyntheticRPC();transport=BaseUSDCPayoutTransport(epoch,rpc,pinned_rpc_url=rpc.endpoint)
        recipient='0x'+f'{2:040x}'
        rpc.nonce=8
        with self.assertRaisesRegex(Rejected,'payout_nonce_conflict'):transport.sign(job,recipient,10_000_000)
        rpc.nonce=7;signed,tx=transport.sign(job,recipient,10_000_000)
        with self.assertRaisesRegex(Rejected,'payout_identity_mismatch'):transport.broadcast(signed,tx)
        epoch.ledger.prepare_payout(job,signed,tx);transport.broadcast(signed,tx)
        second=self.epoch();second._active=second._funded_once=True
        resumed=BaseUSDCPayoutTransport(second,rpc,pinned_rpc_url=rpc.endpoint)
        resumed.broadcast(signed,tx)
        self.assertEqual(rpc.sent[0],rpc.sent[1])

    def test_fresh_ingress_rejects_old_envelope_durable_receipts_verify(self):
        first=self.epoch();old=Channel();job=self.job(first)
        signed=first.receipt_signer.sign(first.ledger.archive_record(job))
        first.ledger.save_receipt(job,signed)
        second=self.epoch();new=Channel()
        reserved=second.ledger.reserve(self.policy['campaigns'][0],request(self.policy['campaigns'][0],3),NOW)
        with patch('transcripts.channel.time.time',return_value=NOW+5):
            context=old.challenge(reserved,policy_digest=digest(self.policy),epoch_id=second.epoch_id,wallet=second.wallet,
                                  client_nonce='a'*64,receipt_key_digest=hashlib.sha256(first.receipt_signer.public_key_der).hexdigest())
            envelope=encrypt(old.public_key_der,context,{'credential':'private'},consent=True)
            with self.assertRaisesRegex(Rejected,'expired_or_replayed_challenge'):new.decrypt_once(envelope)
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from verification.common import unb64
        key=serialization.load_der_public_key(second.receipt_signer.public_key_der)
        restored=second.ledger.restored_receipt(job)
        key.verify(unb64(restored['signature'],512),canonical(restored['payload']),
                   padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())

if __name__=='__main__':unittest.main()

class DurableClientTests(DurableFixture):
    def runtime(self,epoch):
        runtime=Runtime(self.policy,epoch,None,FakeArchive([]),attester=lambda nonce,key,user:nonce)
        return runtime
    def client(self,runtime,release=None):
        release=release or {'status':'approved','serviceUrl':'https://synthetic.invalid','expiresAt':NOW+1000,
                           'policyDigest':digest(self.policy),'measurements':{'0':'a'*96,'1':'b'*96,'2':'c'*96,'8':'d'*96}}
        client=Client(release['serviceUrl'],release,self.policy)
        def call(path,body=None):
            mapping={'/v1/attest':'attest','/v1/reservations':'reserve','/v1/challenges':'challenge','/v1/submissions':'submit'}
            if path in mapping:return runtime.dispatch(mapping[path],body)
            if path.endswith('/receipt'):return runtime.dispatch('receipt',{'jobId':path.split('/')[-2]})
            if path.startswith('/v1/jobs/'):return runtime.dispatch('status',{'jobId':path.split('/')[-1]})
            raise AssertionError(path)
        client.call=call
        return client
    def quote_verifier(self,raw,*,nonce,public_key_der,release):self.assertEqual(raw,nonce)

    def test_paid_restore_fresh_quote_and_stable_signer_without_model_or_second_sign(self):
        with patch('transcripts.client.time.time',return_value=NOW+5),patch('transcripts.runtime.time.time',return_value=NOW+5),\
                patch('transcripts.client.verify_document',side_effect=self.quote_verifier):
            first=self.epoch();first.ledger.update_runtime({'fundedOnce':True});job=self.job(first)
            rpc=SyntheticRPC();payment=BaseUSDCPayoutTransport(first,rpc,pinned_rpc_url=rpc.endpoint)
            signed,tx=payment.sign(job,'0x'+f'{2:040x}',10_000_000);first.ledger.prepare_payout(job,signed,tx)
            first.ledger.mark_paid(job,tx,NOW+4)
            runtime=self.runtime(first);runtime.archive_settlement(job,self.policy['campaigns'][0],first.ledger.archive_record(job))
            client=self.client(runtime);client.preflight()
            client.job={'version':2,'jobId':job,'campaignId':self.policy['campaigns'][0]['id'],
                        'request':request(self.policy['campaigns'][0],2),'bindingDigest':first.ledger.status(job)['bindingDigest'],
                        'epoch':first.public_descriptor(),'receiptPublicKey':b64(first.receipt_signer.public_key_der),
                        'policyDigest':digest(self.policy)}
            from transcripts.client import release_identity
            client.job['releaseDigest']=release_identity(client.release)
            saved=copy.deepcopy(client.job);original=client.receipt(job)
            second=self.epoch();new_runtime=self.runtime(second)
            self.assertNotEqual(runtime.channel.public_key_der,new_runtime.channel.public_key_der)
            restored=self.client(new_runtime);restored.restore(saved)
            result=restored.status(job)
            self.assertEqual(result['state'],'paid');self.assertTrue(result['verified'])
            self.assertEqual(result['receipt'],original)
            self.assertEqual(second.ledger.payout_identity(job),(signed,tx))
            self.assertEqual(new_runtime.payment._known[tx][0],signed)

    def test_signer_substitution_old_context_and_renewal_only_expiry(self):
        with patch('transcripts.client.time.time',return_value=NOW),patch('transcripts.runtime.time.time',return_value=NOW),\
                patch('transcripts.client.verify_document',side_effect=self.quote_verifier):
            first=self.epoch();first._funded_once=first._active=True
            runtime=self.runtime(first);client=self.client(runtime)
            client.reserve(self.policy['campaigns'][0]['id'],'0x'+f'{2:040x}','synthetic','synthetic-model','provider_visible',consent=True)
            saved=copy.deepcopy(client.job)
            renewed={**client.release,'expiresAt':NOW+2000}
            restored=self.client(runtime,renewed);restored.restore(saved);restored.preflight()
            for change in ({'serviceUrl':'https://other.invalid'},{'measurements':{**renewed['measurements'],'0':'f'*96}},
                           {'policyDigest':'f'*64},{'status':'unreleased'}):
                changed={**renewed,**change}
                with self.assertRaises(Rejected):
                    changed_client=Client(changed['serviceUrl'],changed,self.policy);changed_client.restore(saved)
            runtime.receipt_signer=ReceiptSigner()
            with self.assertRaisesRegex(Rejected,'receipt_signer_changed'):restored.preflight()
            runtime.receipt_signer=first.receipt_signer
            old_call=restored.call
            def old_context(path,body=None):
                value=old_call(path,body)
                if path=='/v1/attest':
                    value['context'].pop('receiptPublicKey');value['context']['protocol']='peerlink-epoch-v1'
                return value
            restored.call=old_context
            with self.assertRaises(Rejected):restored.preflight()

    def test_reserve_before_credentials_and_explicit_resume_uses_fresh_ingress(self):
        with patch('transcripts.client.time.time',return_value=NOW),patch('transcripts.runtime.time.time',return_value=NOW),\
                patch('transcripts.client.verify_document',side_effect=self.quote_verifier):
            first=self.epoch();first._funded_once=first._active=True
            first.ledger.update_runtime({'fundedOnce':True})
            runtime=self.runtime(first);client=self.client(runtime);saved=[]
            client.reserve(self.policy['campaigns'][0]['id'],'0x'+f'{2:040x}','synthetic','synthetic-model',
                           'provider_visible',consent=True,on_reserved=saved.append)
            self.assertEqual(len(saved),1);self.assertEqual(first.ledger.status(saved[0]['jobId'])['state'],'reserved')
            self.assertNotIn('credential',canonical(saved[0]).decode())
            second=self.epoch();second._active=True;new_runtime=self.runtime(second)
            restored=self.client(new_runtime);restored.restore(saved[0])
            payload={'credential':{'value':'SYNTHETIC-BANK-SECRET'},'profileId':None,'recipe':{},
                     'inferenceKey':'SYNTHETIC-INFERENCE-SECRET','notes':'','transcript':{}}
            # Prevent launching the bank worker; encrypted submission/ledger transition
            # still run through the real runtime and fresh channel.
            with patch('transcripts.runtime.threading.Thread') as thread:
                result=restored.submit_reserved(payload,consent=True)
            self.assertEqual(result['reportedState'],'submitted')
            thread.assert_called_once()
            self.assertNotEqual(client.key,restored.key)

class DurablePaymentEdges(DurableFixture):
    def test_missing_head_requires_fixed_initial_nonce_and_zero_token_balance(self):
        from transcripts.runtime import bootstrap_wallet_gate
        rpc=SyntheticRPC();wallet=self.signer.address.lower()
        with self.assertRaisesRegex(Rejected,'state_bootstrap_wallet_used'):bootstrap_wallet_gate(CONFIG,wallet,rpc)
        old=rpc.call
        rpc.call=lambda method,params:('0x'+'0'*64) if method=='eth_call' else old(method,params)
        bootstrap_wallet_gate(CONFIG,wallet,rpc)
        rpc.nonce=8
        with self.assertRaisesRegex(Rejected,'state_bootstrap_wallet_used'):bootstrap_wallet_gate(CONFIG,wallet,rpc)
        rpc.nonce=6
        with self.assertRaisesRegex(Rejected,'state_bootstrap_wallet_used'):bootstrap_wallet_gate(CONFIG,wallet,rpc)

    def test_accept_outage_retains_grade_snapshot_and_restart_restores_obligation(self):
        epoch=self.epoch();job=self.job(epoch,accept=False);epoch._funded_once=epoch._active=True
        grade={'rubricVersion':'rubric-v1','score':90,'useful':True}
        evidence={'epoch':epoch.public_descriptor(),'modelResult':grade,'policyDigest':digest(self.policy),
                  'inference':{'requestDigest':'a'*64,'responseDigest':digest(grade),'provider':'synthetic',
                               'model':'synthetic-model','privacyMode':'provider_visible','inputTokens':10,'outputTokens':10}}
        original=self.aws.call
        def outage(service,action,payload):
            if payload['action']=='commit':self.aws.outage=True
            return original(service,action,payload)
        with patch.object(self.aws,'call',side_effect=outage),patch('transcripts.aws_state.time.sleep'):
            with self.assertRaisesRegex(Rejected,'state_commit_uncertain'):
                epoch.accept(job,[read(job)],grade,now=NOW+3,evidence=evidence,policy=self.policy)
        staged=epoch.ledger._pending_snapshot[2]
        self.assertEqual(staged['jobs'][0]['state'],'accepted')
        self.assertNotIn('private-account',canonical(staged).decode())
        self.aws.outage=False
        self.assertEqual(epoch.ledger.status(job)['state'],'accepted')
        restored=self.epoch()
        self.assertEqual(restored.ledger.archive_record(job)['modelResult'],grade)
        self.assertEqual(restored.ledger.status(job)['state'],'accepted')

    def test_paid_final_archive_recovers_while_restart_paused(self):
        first=self.epoch();job=self.job(first)
        payment=BaseUSDCPayoutTransport(first,SyntheticRPC(),pinned_rpc_url=SyntheticRPC.endpoint)
        signed,tx=payment.sign(job,'0x'+f'{2:040x}',10_000_000)
        first.ledger.prepare_payout(job,signed,tx);first.ledger.mark_paid(job,tx,NOW+4)
        second=self.epoch();archive=FakeArchive([])
        runtime=Runtime(self.policy,second,None,archive,attester=lambda nonce,key,user:nonce)
        self.assertFalse(second._active)
        with patch.object(runtime.payment,'broadcast',side_effect=AssertionError('no new broadcast')):
            self.assertTrue(runtime.settle_attempt(job))
        self.assertEqual(archive.records[-1]['payload']['job']['state'],'paid')
        self.assertNotIn(job,runtime.pending_records)

    def test_refund_intent_and_exact_signed_identity_survive_restart(self):
        from transcripts.payout import RetirementCoordinator
        epoch=self.epoch();epoch.ledger.begin_retirement(NOW)
        epoch.finalize_retirement()
        rpc=SyntheticRPC();transport=BaseUSDCPayoutTransport(epoch,rpc,pinned_rpc_url=rpc.endpoint)
        signed,tx=transport.sign_refund(1_000_000)
        with self.assertRaisesRegex(Rejected,'retirement_ineligible'):transport.broadcast_refund(signed,tx)
        epoch.ledger.prepare_refund(1_000_000,signed,tx)
        second=self.epoch();restored=BaseUSDCPayoutTransport(second,rpc,pinned_rpc_url=rpc.endpoint)
        self.assertEqual(second.ledger.refund_identity(),(signed,tx,1_000_000))
        restored.broadcast_refund(signed,tx)
        self.assertEqual(rpc.sent,['0x'+signed.hex()])
        self.assertTrue(second.ledger.retirement_status()['admissionsClosed'])
        with self.assertRaises(Rejected):second.resume_after_operator_verification(second.epoch_id)
