"""Synthetic retirement/refund tests: no new real wallets, RPC or transfers."""
import unittest
from transcripts.common import Rejected
from transcripts.epoch import DEPLOYER_REFUND_ADDRESS
from transcripts.eth_payout import BaseUSDCPayoutTransport,transfer_data,refund_data,TRANSFER_TOPIC
from transcripts.payout import RetirementCoordinator
from transcripts.tests.test_core import campaign,request,read,NOW
from transcripts.tests.test_core_epoch import synthetic_epoch
from transcripts.tests.test_core_eth_payout import SyntheticRPC,BLOCKHASH


class FakeRefundTransport:
    def __init__(self,ledger,amount=45_000_000):
        self.ledger,self.amount=ledger,amount;self.signs=0;self.broadcasts=[];self.balance_reads=0
        self.refund_confirmed=False;self.fail_once=False;self.validate_result=True;self.payment_confirmed=True
        self.tx_id="0x"+"f"*64
    def funding_balances(self):self.balance_reads+=1;return self.amount,10**12
    def sign_refund(self,amount):self.signs+=1;return b"fixed-synthetic-refund",self.tx_id
    def validate_refund(self,*args):return self.validate_result
    def confirmed(self,*args):return self.payment_confirmed
    def confirmed_refund(self,*args):return self.refund_confirmed
    def broadcast_refund(self,signed,tx_id):
        self.assert_persisted=(self.ledger.refund_identity()==(signed,tx_id,self.amount))
        self.broadcasts.append((signed,tx_id))
        if self.fail_once:self.fail_once=False;raise Rejected("payout_rpc_unavailable")
        self.refund_confirmed=True


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.epoch=synthetic_epoch()
        self.epoch.activate_after_operator_verification(self.epoch.epoch_id,self.epoch.wallet,
                                                        usdc_balance_minor=50_000_000,gas_balance_wei=10**12)
    def tearDown(self):self.epoch.close()
    def reserve(self):
        policy=campaign();return self.epoch.ledger.reserve(policy,request(policy),NOW)
    def begin(self):
        return self.epoch.begin_retirement_after_operator_verification(self.epoch.epoch_id,now=NOW+3)
    def submitted_job(self):
        status=self.reserve();self.epoch.ledger.submit(status["jobId"],status["bindingDigest"],NOW+1)
        return status["jobId"]
    def test_closure_cancels_unused_reservations_and_cannot_reopen(self):
        reserved=self.reserve();status=self.begin()
        self.assertEqual(status["state"],"closing")
        self.assertEqual(self.epoch.ledger.status(reserved["jobId"])["state"],"cancelled")
        with self.assertRaisesRegex(Rejected,"admissions_closed"):self.epoch.require_admission()
        with self.assertRaisesRegex(Rejected,"admissions_closed"):self.reserve()
        self.epoch.pause();self.epoch.resume_after_operator_verification(self.epoch.epoch_id)
        self.epoch.require_active() # Existing obligations may still settle.
        with self.assertRaisesRegex(Rejected,"admissions_closed"):self.epoch.require_admission()
        self.epoch.finalize_retirement()
        with self.assertRaises(Rejected):self.epoch.resume_after_operator_verification(self.epoch.epoch_id)
        with self.assertRaises(Rejected):
            self.epoch.activate_after_operator_verification(self.epoch.epoch_id,self.epoch.wallet,
                                                            usdc_balance_minor=50_000_000,gas_balance_wei=1)
        with self.assertRaises(Rejected):self.epoch.sign_transaction({})
    def test_expired_unused_reservation_remains_expired(self):
        reserved=self.reserve()
        self.epoch.begin_retirement_after_operator_verification(self.epoch.epoch_id,now=NOW+700)
        self.assertEqual(self.epoch.ledger.status(reserved["jobId"])["state"],"expired")
    def test_submitted_verifying_accepted_uncertain_payments_all_block_sweep(self):
        job_id=self.submitted_job();self.begin()
        for transition in ("submitted","verifying","accepted","payout_pending"):
            with self.assertRaisesRegex(Rejected,"retirement_obligations_pending"):self.epoch.finalize_retirement()
            self.assertEqual(self.epoch.ledger.status(job_id)["state"],transition)
            if transition=="submitted":self.epoch.ledger.begin_verification(job_id,NOW+2)
            elif transition=="verifying":
                self.epoch.accept(job_id,[read(job_id)],{"rubricVersion":"rubric-v1","score":90,"useful":True},now=NOW+3)
            elif transition=="accepted":self.epoch.ledger.prepare_payout(job_id,b"fixed-payout","0x"+"a"*64)
        self.epoch.ledger.mark_paid(job_id,"0x"+"a"*64,NOW+4)
        self.assertEqual(self.epoch.finalize_retirement()["state"],"retired")
    def test_refund_identity_persisted_before_broadcast_lost_response_retry_once(self):
        self.begin();transport=FakeRefundTransport(self.epoch.ledger);transport.fail_once=True
        coordinator=RetirementCoordinator(self.epoch,transport)
        with self.assertRaisesRegex(Rejected,"payout_rpc_unavailable"):coordinator.reconcile()
        self.assertTrue(transport.assert_persisted)
        self.assertEqual(self.epoch.retirement_status()["state"],"refund_pending")
        identity=self.epoch.ledger.refund_identity()
        self.assertEqual(coordinator.reconcile()["state"],"refunded")
        self.assertEqual(coordinator.reconcile()["state"],"refunded")
        self.assertEqual(transport.signs,1);self.assertEqual(transport.balance_reads,1)
        self.assertEqual(transport.broadcasts[0],transport.broadcasts[1])
        self.assertEqual(self.epoch.ledger.refund_identity(),identity)
        with self.assertRaisesRegex(Rejected,"refund_identity_mismatch"):
            self.epoch.ledger.prepare_refund(40_000_000,b"another",transport.tx_id)
    def test_newly_uncertain_previously_paid_transfer_blocks_refund(self):
        job_id=self.submitted_job();self.epoch.ledger.begin_verification(job_id,NOW+2)
        self.epoch.accept(job_id,[read(job_id)],{"rubricVersion":"rubric-v1","score":90,"useful":True},now=NOW+3)
        self.epoch.ledger.prepare_payout(job_id,b"fixed-payout","0x"+"a"*64)
        self.epoch.ledger.mark_paid(job_id,"0x"+"a"*64,NOW+4)
        self.begin();transport=FakeRefundTransport(self.epoch.ledger);transport.payment_confirmed=False
        with self.assertRaisesRegex(Rejected,"retirement_payments_uncertain"):
            RetirementCoordinator(self.epoch,transport).reconcile()
        self.assertEqual(transport.signs,0);self.assertEqual(transport.broadcasts,[])
        self.assertEqual(self.epoch.retirement_status()["state"],"closing")
    def test_zero_balance_finishes_without_any_transaction_and_bad_tx_never_broadcast(self):
        self.begin();transport=FakeRefundTransport(self.epoch.ledger,amount=0)
        status=RetirementCoordinator(self.epoch,transport).reconcile()
        self.assertEqual(status["state"],"refunded");self.assertEqual(status["amountMinor"],0)
        self.assertEqual(status["refundAddress"],DEPLOYER_REFUND_ADDRESS)
        self.assertEqual(transport.signs,0);self.assertEqual(transport.broadcasts,[])
    def test_invalid_refund_and_wrong_epoch_fail_closed(self):
        with self.assertRaisesRegex(Rejected,"epoch_binding_mismatch"):
            self.epoch.begin_retirement_after_operator_verification("wrong",now=NOW)
        with self.assertRaisesRegex(Rejected,"admissions_not_closed"):
            RetirementCoordinator(self.epoch,FakeRefundTransport(self.epoch.ledger)).reconcile()
        self.begin();transport=FakeRefundTransport(self.epoch.ledger);transport.validate_result=False
        with self.assertRaisesRegex(Rejected,"invalid_refund"):RetirementCoordinator(self.epoch,transport).reconcile()
        self.assertEqual(transport.broadcasts,[])
        self.assertEqual(self.epoch.retirement_status()["state"],"retired")
    def test_actual_synthetic_signed_refund_targets_fixed_deployer_and_exact_balance(self):
        self.begin();self.epoch.finalize_retirement();rpc=SyntheticRPC()
        transport=BaseUSDCPayoutTransport(self.epoch,rpc,pinned_rpc_url=rpc.endpoint)
        signed,tx_id=transport.sign_refund(45_000_000)
        self.assertTrue(transport.validate_refund(signed,tx_id,45_000_000))
        self.assertFalse(transport.validate_refund(signed,tx_id,40_000_000))
        self.assertEqual(transport.sign_refund(45_000_000),(signed,tx_id))
        with self.assertRaisesRegex(Rejected,"refund_identity_mismatch"):transport.sign_refund(40_000_000)
        import rlp
        decoded=rlp.decode(signed[1:])
        self.assertEqual(decoded[7],refund_data(45_000_000))
        self.assertEqual(decoded[7][4:36],bytes.fromhex(DEPLOYER_REFUND_ADDRESS[2:]).rjust(32,b"\0"))
        transport.broadcast_refund(signed,tx_id);transport.broadcast_refund(signed,tx_id)
        self.assertEqual(rpc.sent[0],rpc.sent[1])
        with self.assertRaises(Rejected):transport.sign("new-job",DEPLOYER_REFUND_ADDRESS,5_000_000)
        rpc.receipt={"transactionHash":tx_id,"status":"0x1","from":self.epoch.wallet,"to":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                     "blockNumber":"0x64","blockHash":BLOCKHASH,"logs":[{
                         "address":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","transactionHash":tx_id,"blockHash":BLOCKHASH,
                         "topics":[TRANSFER_TOPIC,"0x"+self.epoch.wallet[2:].rjust(64,"0"),
                                   "0x"+DEPLOYER_REFUND_ADDRESS[2:].rjust(64,"0")],"data":"0x"+f"{45_000_000:064x}"}]}
        self.assertTrue(transport.confirmed_refund(tx_id,45_000_000))
        rpc.receipt["logs"][0]["topics"][2]="0x"+"0"*24+"2"*40
        with self.assertRaises(Rejected):transport.confirmed_refund(tx_id,45_000_000)

if __name__ == "__main__":unittest.main()
