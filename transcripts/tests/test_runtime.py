"""Synthetic integration/security tests. No live keys, hardware, RPC or cloud use."""
import copy
import hashlib
import threading
import unittest
from unittest.mock import patch
from contextlib import contextmanager
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from verification.common import b64
from transcripts.artifacts import validate_archive_record
from transcripts.channel import Channel
from transcripts.common import Rejected, canonical, digest
from transcripts.epoch import CHAIN_ID, USDC_ADDRESS, MAX_GAS_FUNDING_WEI
from transcripts.ledger import Ledger
from transcripts.providers import SYSTEM_PROMPT
from transcripts.payout import PayoutCoordinator
from transcripts.runtime import Runtime, RPC, SETTLEMENT_MAX_ATTEMPTS, SETTLEMENT_RETRY_SECONDS
from transcripts.server import route, connect_public
from transcripts.transport import HTTPResponse
from transcripts.tests.test_kms_signer import KEY_ID
from transcripts.tests.test_core import Anchor, campaign, request, read, KEY, NOW

OPERATOR = Ed25519PrivateKey.from_private_bytes(b"fixed-public-test-operator-seed!"[:32].ljust(32,b"!"))
PUBLIC_OPERATOR = OPERATOR.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()


class FakeRSA:
    def decrypt(self, wrapped, padding):
        if wrapped != b"synthetic-wrapped": raise ValueError("invalid synthetic wrapping")
        return b"t"*32


def fake_channel():
    # No RSA/private-key generation. AES uses a fixed, public synthetic test key.
    channel=object.__new__(Channel)
    channel.key=FakeRSA();channel.public_key_der=b"synthetic-public-key"
    channel.pending={};channel.lock=threading.Lock()
    return channel


def envelope(context, payload):
    nonce=b"n"*12
    return {"context":copy.deepcopy(context),"wrappedKey":b64(b"synthetic-wrapped"),"nonce":b64(nonce),
            "ciphertext":b64(AESGCM(b"t"*32).encrypt(nonce,canonical(payload),canonical(context)))}


class SigningChannel:
    public_key_der=b"synthetic-public-key"
    def sign(self, record): return {"payload":copy.deepcopy(record),"signature":"synthetic-signature"}


class FakeEpoch:
    epoch_id="1"*32;wallet="0x"+"1"*40
    def __init__(self):
        self.active=True;self.activations=[];self.anchor=Anchor()
        self.ledger=Ledger(":memory:",KEY,anchor=self.anchor)
    def require_active(self):
        if not self.active: raise Rejected("payout_paused")
    def require_admission(self):
        self.require_active()
        if self.ledger.retirement_status()['admissionsClosed']:raise Rejected('admissions_closed')
    def retirement_status(self):return self.ledger.retirement_status()
    def begin_retirement_after_operator_verification(self,epoch_id,*,now):
        if epoch_id != self.epoch_id:raise Rejected('epoch_binding_mismatch')
        return self.ledger.begin_retirement(now)
    def public_descriptor(self):
        return {"version":2,"epochId":self.epoch_id,"payoutWallet":self.wallet,"chainId":CHAIN_ID,
                "usdcContract":USDC_ADDRESS,"budgetMinor":50_000_000,"maxGasFundingWei":MAX_GAS_FUNDING_WEI,
                "payoutKeyCustody":"aws_kms","payoutKeyId":KEY_ID,"operatorRecovery":True,
                "ledgerPersistence":"enclave_ram_only","restartRequiresOperatorReview":True}
    def pause(self):self.active=False
    def resume_after_operator_verification(self, epoch_id):
        if epoch_id != self.epoch_id: raise Rejected("epoch_binding_mismatch")
        self.active=True
    def activate_after_operator_verification(self,*args,**kwargs):
        self.activations.append((args,kwargs));self.active=True
    def accept(self,job_id,reads,grade,now):
        self.require_active()
        return self.ledger.accept(job_id,reads,grade,dedup_key=KEY,now=now)


class FakeArchive:
    def __init__(self,events):self.events=events;self.records=[];self.fail_calls=set();self.calls=0
    def persist(self,record):
        self.calls+=1
        if self.calls in self.fail_calls: raise Rejected("storage_unavailable")
        self.records.append(copy.deepcopy(record));self.events.append("archive")
        return digest(record)


class FakeCoordinator:
    tx_id="0x"+"a"*64
    def __init__(self,ledger,events):self.ledger,self.events=ledger,events;self.calls=0;self.fail_broadcast_once=False
    def reconcile(self,job_id,now):
        self.calls+=1;self.events.append("reconcile")
        status=self.ledger.status(job_id)
        if status["state"]=="paid":return status
        if status["state"]=="accepted":self.ledger.prepare_payout(job_id,b"fixed-synthetic-transaction",self.tx_id)
        if self.fail_broadcast_once:
            self.fail_broadcast_once=False
            raise Rejected("payout_rpc_unavailable")
        self.events.append("paid")
        return self.ledger.mark_paid(job_id,self.tx_id,now)


class RecoveryTransport:
    """Real coordinator exercise: transfer mines despite a lost RPC response."""
    tx_id='0x'+'b'*64
    signed=b'immutable-synthetic-payment'
    def __init__(self,failure):
        self.failure=failure;self.mined=False;self.signs=0;self.broadcasts=[];self.checks=0
    def sign(self,*args):
        self.signs+=1
        return self.signed,self.tx_id
    def validate(self,signed,tx_id,*args):return (signed,tx_id)==(self.signed,self.tx_id)
    def broadcast(self,signed,tx_id):
        assert self.validate(signed,tx_id)
        self.broadcasts.append((signed,tx_id));self.mined=True
        if self.failure=='lost_broadcast':
            self.failure=None
            raise Rejected('payout_rpc_unavailable')
    def confirmed(self,*args):
        self.checks+=1
        if self.mined and self.failure=='receipt_rpc':
            self.failure=None
            raise Rejected('http_transport_failed')
        return self.mined


class FakeBank:
    instances=[];failure=None
    def __init__(self,policy,credential,**kwargs):
        self.credential=credential.copy();self.closed=False;self.instances.append(self)
    def acquire(self,job_id,recipe,now):
        if self.failure: raise self.failure
        return [read(job_id,acquired_at=now)]
    def close(self):self.closed=True;self.credential.clear()


class FakeProvider:
    instances=[];extra_grade=None;unsafe_metadata=False
    def __init__(self,policy,reservation,api_key,**kwargs):
        self.api_key=api_key;self.closed=False;self.instances.append(self)
    def grade(self,artifact,now):
        grade={"rubricVersion":"rubric-v1","score":90,"useful":True}
        if self.extra_grade:grade.update(self.extra_grade)
        self.metadata={"requestDigest":"d"*64,"responseDigest":digest(grade),"provider":"synthetic",
                       "model":"synthetic-model","privacyMode":"provider_visible","inputTokens":10,"outputTokens":10}
        if self.unsafe_metadata:self.metadata["rawCredential"]="SECRET-INFERENCE-KEY"
        return grade
    def close(self):self.api_key=None;self.closed=True


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock=patch("transcripts.runtime.time.time",return_value=NOW+3);self.clock.start()
        self.monotonic_now=0
        self.monotonic=patch('transcripts.runtime.time.monotonic',side_effect=lambda:self.monotonic_now);self.monotonic.start()
        self.sleep=patch('transcripts.runtime.time.sleep',side_effect=self.advance_time);self.sleep_mock=self.sleep.start()
        self.events=[];self.epoch=FakeEpoch();self.archive=FakeArchive(self.events)
        self.policy={"promptDigest":hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),"payoutRpc":"https://rpc.example",
                     "campaigns":[campaign()],"operatorPublicKey":PUBLIC_OPERATOR,"pilotBudgetMinor":50_000_000,
                     "payoutAuthority":{"kind":"aws_kms","keyId":KEY_ID,"wallet":self.epoch.wallet}}
        with patch("transcripts.runtime.Channel",return_value=SigningChannel()):
            self.runtime=Runtime(self.policy,self.epoch,object(),self.archive,attester=lambda *args:b"synthetic-quote")
        self.coordinator=FakeCoordinator(self.epoch.ledger,self.events);self.runtime.coordinator=self.coordinator
        self.runtime.payment=type("FakeFunding",(),{"funding_balances":lambda _: (50_000_000,10**12)})()
        FakeBank.instances=[];FakeBank.failure=None
        FakeProvider.instances=[];FakeProvider.extra_grade=None;FakeProvider.unsafe_metadata=False
    def advance_time(self,seconds):self.monotonic_now+=seconds
    def tearDown(self):
        self.epoch.ledger.close();self.clock.stop();self.monotonic.stop();self.sleep.stop()
    def job(self):
        status=self.runtime.dispatch("reserve",request(self.policy["campaigns"][0]))
        self.epoch.ledger.submit(status["jobId"],status["bindingDigest"],NOW+3)
        return status["jobId"]
    def process(self,job_id):
        payload={"credential":{"origin":"https://bank.example","kind":"bearer","value":"SECRET-BANK-CREDENTIAL"},
                 "profileId":"1","recipe":{"version":1,"reads":[]},"inferenceKey":"SECRET-INFERENCE-KEY",
                 "notes":"SECRET-LOCAL-NOTES","transcript":{"rawBankMemo":"SECRET-LOCAL-TRANSCRIPT"}}
        self.runtime.jobs.acquire()
        with patch("transcripts.transport.BankClient",FakeBank),patch("transcripts.providers.ProviderClient",FakeProvider):
            self.runtime.process(job_id,payload)
        self.assertEqual(payload,{})
        return payload
    def operator_message(self,action="pause",nonce="b"*64,**changes):
        value={"action":action,"epochId":self.epoch.epoch_id,"wallet":self.epoch.wallet,"nonce":nonce,"expiresAt":NOW+60}
        value.update(changes)
        return {"payload":value,"signature":b64(OPERATOR.sign(canonical(value)))}
    def test_operator_preflight_exercises_rpc_and_signing_without_activation(self):
        self.epoch.pause()
        probe={"keyId":KEY_ID,"wallet":self.epoch.wallet,"signingVerified":True,"broadcast":False,
               "transactionHash":"0x"+"e"*64}
        with patch.object(self.runtime.payment,'funding_balances',return_value=(0,0)), \
             patch.object(self.epoch,'check_payout_signing',return_value=probe,create=True) as check, \
             patch.object(self.runtime.rpc,'call',return_value='0x0') as rpc:
            value=self.runtime.operator(self.operator_message('preflight'))
        check.assert_called_once_with(0)
        rpc.assert_called_once_with('eth_getTransactionCount',[self.epoch.wallet,'pending'])
        self.assertFalse(value['health']['accepting'])
        self.assertEqual(value['preflight']['usdcBalanceMinor'],0)
        self.assertTrue(value['preflight']['signingVerified'])
        self.assertEqual(self.epoch.activations,[])
    def test_preflight_rejects_a_funded_wallet_before_signing(self):
        self.epoch.pause()
        with patch.object(self.epoch,'check_payout_signing',create=True) as check:
            with self.assertRaisesRegex(Rejected,'preflight_requires_unfunded'):
                self.runtime.operator(self.operator_message('preflight'))
        check.assert_not_called()
    def test_archive_before_payment_and_exports_only_redacted_data(self):
        job_id=self.job();self.process(job_id)
        self.assertEqual(self.epoch.ledger.status(job_id)["state"],"paid")
        self.assertEqual(self.events,["archive","reconcile","paid","archive"])
        self.assertNotIn(job_id,self.runtime.pending_records)
        for archived in self.archive.records:
            validate_archive_record(self.policy["campaigns"][0],archived["payload"],policy=self.policy)
            encoded=canonical(archived).decode()
            for secret in ("SECRET-BANK-CREDENTIAL","SECRET-INFERENCE-KEY","SECRET-LOCAL-NOTES","SECRET-LOCAL-TRANSCRIPT",
                           "private-account-1","private-transaction-id","private-name-key","private-memo","secret-query-value"):
                self.assertNotIn(secret,encoded)
        self.assertTrue(FakeBank.instances[0].closed);self.assertEqual(FakeBank.instances[0].credential,{})
        self.assertTrue(FakeProvider.instances[0].closed);self.assertIsNone(FakeProvider.instances[0].api_key)
    def test_archive_validator_rejects_nested_raw_content_and_wrong_bindings(self):
        job_id=self.job();self.process(job_id)
        original=self.archive.records[0]["payload"]
        modifications=[
            ("epoch","privateKey","SECRET-KEY"),
            ("job","rawAccount","SECRET-ACCOUNT"),
            ("modelResult","prose","SECRET-MODEL-TEXT"),
            ("inference","apiKey","SECRET-INFERENCE-KEY"),
            ("inference","model","unapproved-secret-model"),
            ("job","artifactDigest","0"*64),
            ("job","rewardMinor",50_000_000),
            ("epoch","chainId",1),
        ]
        for section,key,value in modifications:
            candidate=copy.deepcopy(original);candidate[section][key]=value
            with self.assertRaises(Rejected):validate_archive_record(self.policy["campaigns"][0],candidate,policy=self.policy)
        candidate=copy.deepcopy(original)
        candidate["artifact"]["endpoints"][0]["path"]="/api/accounts/SECRET-ACCOUNT/transactions"
        with self.assertRaises(Rejected):validate_archive_record(self.policy["campaigns"][0],candidate,policy=self.policy)
    def test_initial_archive_transient_retries_before_payment_without_new_credentials(self):
        self.archive.fail_calls={1};job_id=self.job();self.process(job_id)
        self.assertEqual(self.epoch.ledger.status(job_id)["state"],"paid")
        self.assertEqual(self.coordinator.calls,1)
        self.assertEqual(self.events,['archive','reconcile','paid','archive'])
        self.assertEqual(self.archive.calls,3)
        self.assertEqual(len(FakeBank.instances),1);self.assertEqual(len(FakeProvider.instances),1)
    def assert_mined_failure_recovers(self,failure):
        transport=RecoveryTransport(failure)
        self.runtime.coordinator=PayoutCoordinator(self.epoch.ledger,transport)
        job_id=self.job();self.process(job_id)
        self.assertEqual(self.epoch.ledger.status(job_id)["state"],"paid")
        self.assertEqual(self.epoch.ledger.payout_identity(job_id),(transport.signed,transport.tx_id))
        self.assertEqual(transport.signs,1);self.assertEqual(len(transport.broadcasts),1)
        self.assertNotIn(job_id,self.runtime.pending_records)
        self.assertEqual(len(FakeBank.instances),1);self.assertEqual(len(FakeProvider.instances),1)
    def test_mined_payment_lost_broadcast_response_recovers_automatically(self):
        self.assert_mined_failure_recovers('lost_broadcast')
    def test_mined_payment_receipt_rpc_transient_recovers_automatically(self):
        self.assert_mined_failure_recovers('receipt_rpc')
    def test_post_payment_archive_failure_automatically_retries_without_payment_again(self):
        self.archive.fail_calls={2};job_id=self.job();self.process(job_id)
        self.assertEqual(self.epoch.ledger.status(job_id)["state"],"paid")
        self.assertEqual(self.events.count("paid"),1)
        self.assertEqual(self.coordinator.calls,1);self.assertEqual(self.archive.calls,3)
        self.assertNotIn(job_id,self.runtime.pending_records)
        self.assertEqual(self.archive.records[-1]["payload"]["job"]["state"],"paid")
        self.assertEqual(len(FakeBank.instances),1);self.assertEqual(len(FakeProvider.instances),1)
    def test_retry_attempt_bound_retains_obligation_for_manual_reconcile(self):
        self.archive.fail_calls=set(range(1,SETTLEMENT_MAX_ATTEMPTS+1))
        job_id=self.job();self.process(job_id)
        self.assertEqual(self.archive.calls,SETTLEMENT_MAX_ATTEMPTS)
        self.assertEqual(self.epoch.ledger.status(job_id)['state'],'accepted')
        self.assertIn(job_id,self.runtime.pending_records);self.assertEqual(self.coordinator.calls,0)
        self.archive.fail_calls.clear();self.runtime.reconcile_pending()
        self.assertEqual(self.epoch.ledger.status(job_id)['state'],'paid')
        self.assertEqual(len(FakeBank.instances),1);self.assertEqual(len(FakeProvider.instances),1)
    def test_retry_deadline_includes_transport_time_and_does_not_start_another_attempt(self):
        def unavailable(record):
            self.monotonic_now+=SETTLEMENT_RETRY_SECONDS+1
            raise OSError('synthetic unavailable archive')
        with patch.object(self.archive,'persist',side_effect=unavailable) as archive:
            job_id=self.job();self.process(job_id)
        self.assertEqual(archive.call_count,1);self.sleep_mock.assert_not_called()
        self.assertEqual(self.epoch.ledger.status(job_id)['state'],'accepted')
        self.assertIn(job_id,self.runtime.pending_records)
    def test_pause_during_retry_stops_automatic_payment_until_operator_resume(self):
        transport=RecoveryTransport('lost_broadcast')
        original=transport.broadcast
        def broadcast(*args):
            self.epoch.pause()
            original(*args)
        transport.broadcast=broadcast
        self.runtime.coordinator=PayoutCoordinator(self.epoch.ledger,transport)
        job_id=self.job();self.process(job_id)
        self.assertEqual(self.epoch.ledger.status(job_id)['state'],'payout_pending')
        self.assertEqual(transport.signs,1);self.assertEqual(len(transport.broadcasts),1)
        self.assertIn(job_id,self.runtime.pending_records)
        self.runtime.operator(self.operator_message('resume'))
        self.runtime.reconcile_pending()
        self.assertEqual(self.epoch.ledger.status(job_id)['state'],'paid')
        self.assertEqual(len(transport.broadcasts),1)
    def test_permanent_validation_failure_is_not_retried(self):
        with patch.object(self.coordinator,'reconcile',side_effect=Rejected('invalid_transaction')) as reconcile:
            job_id=self.job();self.process(job_id)
        self.assertEqual(reconcile.call_count,1);self.sleep_mock.assert_not_called()
        self.assertIn(job_id,self.runtime.pending_records)
    def test_failed_final_archive_preserves_published_signed_payload_snapshot(self):
        class AliasingChannel(SigningChannel):
            def sign(self,record):return {'payload':record,'signature':'synthetic-signature'}
        self.runtime.channel=AliasingChannel()
        self.archive.fail_calls=set(range(2,SETTLEMENT_MAX_ATTEMPTS+2))
        job_id=self.job();self.process(job_id)
        self.assertEqual(self.epoch.ledger.status(job_id)['state'],'paid')
        self.assertEqual(self.runtime.receipts[job_id]['payload']['job']['state'],'accepted')
        self.assertEqual(self.runtime.pending_records[job_id]['job']['state'],'paid')
        self.assertIn(job_id,self.runtime.pending_records)
        self.assertEqual(self.coordinator.calls,1)
    def test_paused_settlement_never_archives_or_pays(self):
        self.archive.fail_calls=set(range(1,SETTLEMENT_MAX_ATTEMPTS+1));job_id=self.job();self.process(job_id)
        self.epoch.pause()
        with self.assertRaisesRegex(Rejected,"payout_paused"):self.runtime.settle(job_id)
        self.assertEqual(self.coordinator.calls,0)
    def test_bank_failures_and_model_injection_use_fixed_safe_rejections(self):
        FakeBank.failure=Rejected("SECRET-BANK-CREDENTIAL-IN-ERROR");job_id=self.job();self.process(job_id)
        self.assertEqual(self.epoch.ledger.status(job_id)["reason"],"invalid_submission")
        self.assertEqual(self.archive.records,[])
        self.assertTrue(FakeBank.instances[0].closed)
        FakeBank.failure=None;FakeProvider.extra_grade={"instructions":"SECRET-MODEL-PROSE"}
        next_job=self.job();self.process(next_job)
        self.assertEqual(self.epoch.ledger.status(next_job)["state"],"rejected")
        self.assertEqual(self.coordinator.calls,0);self.assertEqual(self.archive.records,[])
    def test_unsafe_metadata_cannot_be_archived_or_paid(self):
        FakeProvider.unsafe_metadata=True;job_id=self.job();self.process(job_id)
        self.assertEqual(self.archive.records,[]);self.assertEqual(self.coordinator.calls,0)
    def test_genuine_operator_signature_replay_tamper_and_epoch_binding(self):
        message=self.operator_message();self.runtime.operator(message)
        self.assertFalse(self.epoch.active)
        with self.assertRaisesRegex(Rejected,"operator_replayed"):self.runtime.operator(message)
        tampered=self.operator_message(action="resume",nonce="c"*64);tampered["payload"]["nonce"]="d"*64
        with self.assertRaisesRegex(Rejected,"operator_signature_invalid"):self.runtime.operator(tampered)
        with self.assertRaisesRegex(Rejected,"epoch_binding_mismatch"):
            self.runtime.operator(self.operator_message(action="resume",nonce="e"*64,epochId="old"))
        with self.assertRaisesRegex(Rejected,"operator_expired"):
            self.runtime.operator(self.operator_message(action="resume",nonce="f"*64,expiresAt=NOW))
        self.runtime.operator(self.operator_message(action="resume",nonce="a"*64))
        self.assertTrue(self.epoch.active)
    def test_activation_requires_successful_preflight_for_this_epoch(self):
        self.epoch.pause()
        with self.assertRaisesRegex(Rejected,'funding_preflight_required'):
            self.runtime.operator(self.operator_message('activate'))
        with patch.object(self.runtime.payment,'funding_balances',return_value=(0,0)), \
             patch.object(self.epoch,'check_payout_signing',side_effect=Rejected('kms_broker_unavailable'),create=True), \
             patch.object(self.runtime.rpc,'call',return_value='0x0'):
            with self.assertRaisesRegex(Rejected,'kms_broker_unavailable'):
                self.runtime.operator(self.operator_message('preflight',nonce='a'*64))
        self.assertIsNone(self.runtime.funding_preflight)
        with self.assertRaisesRegex(Rejected,'funding_preflight_required'):
            self.runtime.operator(self.operator_message('activate',nonce='c'*64))
        self.runtime.funding_preflight='0'*64
        with self.assertRaisesRegex(Rejected,'funding_preflight_required'):
            self.runtime.operator(self.operator_message('activate',nonce='d'*64))
        self.assertEqual(self.epoch.activations,[])
    def test_activation_reads_chain_balances_and_reconcile_requires_signature(self):
        self.epoch.pause()
        with patch.object(self.runtime.payment,'funding_balances',return_value=(0,0)), \
             patch.object(self.epoch,'check_payout_signing',return_value={},create=True), \
             patch.object(self.runtime.rpc,'call',return_value='0x0'):
            self.runtime.operator(self.operator_message('preflight',nonce='a'*64))
        self.runtime.operator(self.operator_message(action="activate"))
        self.assertEqual(self.epoch.activations[0][1],{"usdc_balance_minor":50_000_000,"gas_balance_wei":10**12})
        with patch("transcripts.runtime.threading.Thread") as worker:
            self.runtime.operator(self.operator_message(action="reconcile",nonce="c"*64))
            self.assertEqual(worker.call_args.kwargs["target"],self.runtime.reconcile_pending)
            worker.return_value.start.assert_called_once()
    def test_reservation_unfunded_and_wrong_policy_fail_before_inference(self):
        self.epoch.pause()
        with self.assertRaisesRegex(Rejected,"payout_paused"):self.runtime.dispatch("reserve",request(self.policy["campaigns"][0]))
        self.epoch.active=True;candidate=request(self.policy["campaigns"][0]);candidate["policyDigest"]="0"*64
        with self.assertRaisesRegex(Rejected,"policy_mismatch"):self.runtime.dispatch("reserve",candidate)
        self.assertEqual(FakeProvider.instances,[])

    def test_signed_retirement_closes_admissions_before_background_refund(self):
        reservation=self.runtime.dispatch('reserve',request(self.policy['campaigns'][0]))
        with patch('transcripts.runtime.threading.Thread') as worker:
            result=self.runtime.operator(self.operator_message(action='retire'))
            self.assertFalse(result['accepting'])
            self.assertTrue(result['retirement']['admissionsClosed'])
            self.assertEqual(worker.call_args.kwargs['target'],self.runtime.reconcile_retirement)
        with self.assertRaisesRegex(Rejected,'admissions_closed'):
            self.runtime.dispatch('reserve',request(self.policy['campaigns'][0]))
        self.assertNotEqual(self.epoch.ledger.status(reservation['jobId'])['state'],'reserved')

    def test_refund_waits_for_pending_archive_and_never_discards_obligation(self):
        from unittest.mock import Mock
        job_id=self.job();self.archive.fail_calls=set(range(1,2*SETTLEMENT_MAX_ATTEMPTS+1));self.process(job_id)
        self.runtime.retirement=Mock()
        self.runtime.reconcile_retirement()
        self.runtime.retirement.reconcile.assert_not_called()
        self.assertIn(job_id,self.runtime.pending_records)


class ChannelBoundaryTests(unittest.TestCase):
    def setUp(self):self.channel=fake_channel()
    def challenge(self,expires_at=NOW+60):
        status={"state":"reserved","jobId":"a"*32,"bindingDigest":"b"*64,"expiresAt":expires_at}
        with patch("transcripts.channel.time.time",return_value=NOW):
            return self.channel.challenge(status,policy_digest="c"*64,epoch_id="d"*32,wallet="0x"+"1"*40,client_nonce="e"*64)
    def test_ciphertext_authentication_injection_cannot_burn_challenge(self):
        context=self.challenge();valid=envelope(context,{"notes":"synthetic"});invalid=copy.deepcopy(valid)
        invalid["ciphertext"]=b64(b"corrupt-ciphertext")
        with patch("transcripts.channel.time.time",return_value=NOW):
            with self.assertRaisesRegex(Rejected,"invalid_envelope"):self.channel.decrypt_once(invalid)
            self.assertEqual(self.channel.decrypt_once(valid),{"notes":"synthetic"})
            with self.assertRaisesRegex(Rejected,"expired_or_replayed_challenge"):self.channel.decrypt_once(valid)
    def test_context_injection_cannot_consume_or_change_job_binding(self):
        context=self.challenge();valid=envelope(context,{"notes":"synthetic"})
        for field,value in (("bindingDigest","0"*64),("wallet","0x"+"2"*40),("epochId","f"*32),("clientNonce","a"*64)):
            invalid=copy.deepcopy(valid);invalid["context"][field]=value
            with patch("transcripts.channel.time.time",return_value=NOW):
                with self.assertRaisesRegex(Rejected,"expired_or_replayed_challenge"):self.channel.decrypt_once(invalid)
        with patch("transcripts.channel.time.time",return_value=NOW):self.channel.decrypt_once(valid)
    def test_expired_reservation_and_challenge_reject(self):
        with self.assertRaisesRegex(Rejected,"job_expired"):self.challenge(expires_at=NOW)
        context=self.challenge();valid=envelope(context,{})
        with patch("transcripts.channel.time.time",return_value=NOW+61):
            with self.assertRaisesRegex(Rejected,"expired_or_replayed_challenge"):self.channel.decrypt_once(valid)
    def test_concurrent_replay_only_one_authenticated_submit(self):
        context=self.challenge();valid=envelope(context,{"notes":"synthetic"});results=[]
        def decrypt():
            try:self.channel.decrypt_once(valid);results.append("success")
            except Rejected:results.append("replay")
        with patch("transcripts.channel.time.time",return_value=NOW):
            threads=[threading.Thread(target=decrypt) for _ in range(2)]
            for worker in threads:worker.start()
            for worker in threads:worker.join()
        self.assertCountEqual(results,["success","replay"])


class RelayBoundaryTests(unittest.TestCase):
    def test_routing_allows_only_known_routes_and_opaque_job_ids(self):
        self.assertEqual(route("GET","/v1/jobs/"+"a"*32,{})["command"],"status")
        for method,path in (("POST","/v1/jobs/"+"a"*32),("GET","/v1/jobs/private-account"),
                            ("GET","/v1/jobs/"+"a"*32+"/credential"),("GET","/health?secret=x"),
                            ("GET","/%68ealth"),("DELETE","/v1/reservations")):
            with self.assertRaises(Rejected):route(method,path,{})
    def test_egress_rejects_private_dns_and_mixed_answers_before_connect(self):
        public=(2,1,6,"",("93.184.216.34",443))
        private=(2,1,6,"",("127.0.0.1",443))
        with patch("transcripts.server.socket.getaddrinfo",return_value=[public,private]),patch("transcripts.server.socket.socket") as socket:
            with self.assertRaisesRegex(Rejected,"egress_denied"):connect_public("rpc.example")
            socket.assert_not_called()
    def test_rpc_rejects_tls_error_and_wrong_response_id(self):
        class Transport:
            def __init__(self,tls=True):self.tls=tls
            def request(self,*args,**kwargs):
                return HTTPResponse(200,canonical({"jsonrpc":"2.0","id":"wrong","result":"0x1"}),tls_verified=self.tls)
        for tls in (True,False):
            with self.assertRaisesRegex(Rejected,"payout_rpc_unavailable"):RPC("https://rpc.example",Transport(tls)).call("eth_chainId",[])

if __name__ == "__main__":unittest.main()
