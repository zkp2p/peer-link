"""Synthetic KMS-custody epoch tests; no live keys, hardware, AWS or funding."""
import copy
import pickle
import unittest
from unittest.mock import patch
from transcripts.common import Rejected
from transcripts.epoch import BootEpoch, MAX_GAS_FUNDING_WEI, _EpochAnchor
from transcripts.tests.test_core import campaign, request, NOW
from transcripts.kms_signer import KmsSigner
from transcripts.tests.test_kms_signer import KEY_ID
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from eth_keys import keys
import base64


def synthetic_epoch(index=1, budget_minor=50_000_000):
    private = keys.PrivateKey(index.to_bytes(32,"big"))
    public = ec.derive_private_key(index,ec.SECP256K1()).public_key().public_bytes(
        serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    def exchange(request):
        signature = private.sign_msg_hash(bytes.fromhex(request['digest']))
        return {'version':1,'keyId':KEY_ID,'publicKey':base64.b64encode(public).decode(),
                'signature':base64.b64encode(utils.encode_dss_signature(signature.r,signature.s)).decode()}
    signer=KmsSigner(KEY_ID,private.public_key.to_checksum_address(),exchange)
    with patch("transcripts.epoch._require_nsm"), patch("transcripts.epoch.secrets.token_bytes",
            side_effect=[b"i"*32,b"d"*32]), \
            patch("transcripts.epoch.secrets.token_hex",return_value=f"{index:032x}"):
        return BootEpoch.create(signer,budget_minor=budget_minor)


class EpochTests(unittest.TestCase):
    def test_normal_host_refuses_before_wallet_generation(self):
        with patch("transcripts.epoch.platform.system",return_value="Darwin"), \
                patch("transcripts.epoch.secrets.token_bytes",side_effect=AssertionError("must not generate")):
            with self.assertRaisesRegex(Rejected,"epoch_requires_nitro"): BootEpoch.create(None)
    def test_no_key_or_state_import_and_no_serialization(self):
        with self.assertRaises(TypeError): BootEpoch(private_key=b"fixture")
        with self.assertRaises(TypeError): BootEpoch.create(state={})
        epoch=synthetic_epoch()
        try:
            for action in (pickle.dumps,copy.copy,copy.deepcopy):
                with self.assertRaises(TypeError): action(epoch)
            for name in ("restore","seal","export","from_key","load"):
                self.assertFalse(hasattr(epoch,name))
            descriptor=epoch.public_descriptor()
            self.assertEqual(descriptor["version"],2)
            self.assertEqual(descriptor["payoutKeyCustody"],"aws_kms")
            self.assertEqual(descriptor["payoutKeyId"],KEY_ID)
            self.assertTrue(descriptor["operatorRecovery"])
            self.assertTrue(descriptor["restartRequiresOperatorReview"])
            self.assertEqual(descriptor["ledgerPersistence"],"enclave_ram_only")
            self.assertEqual(epoch.ledger.db.execute("PRAGMA database_list").fetchone()[2],"")
        finally: epoch.close()
    def test_new_epoch_is_paused_distinct_wallet_and_no_history(self):
        first,second=synthetic_epoch(1),synthetic_epoch(2)
        try:
            self.assertNotEqual(first.wallet,second.wallet)
            self.assertNotEqual(first.binding_digest(),second.binding_digest())
            for epoch in (first,second):
                with self.assertRaisesRegex(Rejected,"payout_paused"): epoch.require_active()
            policy=campaign()
            first.ledger.reserve(policy,request(policy),NOW)
            self.assertEqual(second.ledger.db.execute("SELECT count(*) FROM jobs").fetchone()[0],0)
            # Existing HMAC key/state cannot be inserted into fresh epoch authority.
            with self.assertRaisesRegex(Rejected,"state_rollback"):
                second._anchor.advance(None,first._anchor.read())
        finally: first.close(); second.close()
    def test_activation_exact_binding_funding_and_no_refill(self):
        epoch=synthetic_epoch()
        try:
            with self.assertRaisesRegex(Rejected,"epoch_binding_mismatch"):
                epoch.activate_after_operator_verification("old",epoch.wallet,usdc_balance_minor=50_000_000,gas_balance_wei=1)
            for balance in (0,49_000_000,51_000_000):
                with self.assertRaisesRegex(Rejected,"epoch_funding_mismatch"):
                    epoch.activate_after_operator_verification(epoch.epoch_id,epoch.wallet,usdc_balance_minor=balance,gas_balance_wei=1)
            with self.assertRaisesRegex(Rejected,"epoch_gas_funding_mismatch"):
                epoch.activate_after_operator_verification(epoch.epoch_id,epoch.wallet,usdc_balance_minor=50_000_000,
                                                          gas_balance_wei=MAX_GAS_FUNDING_WEI+1)
            epoch.activate_after_operator_verification(epoch.epoch_id,epoch.wallet,usdc_balance_minor=50_000_000,gas_balance_wei=1)
            epoch.require_active();epoch.pause()
            with self.assertRaisesRegex(Rejected,"payout_paused"): epoch.require_active()
            epoch.resume_after_operator_verification(epoch.epoch_id);epoch.require_active()
            with self.assertRaisesRegex(Rejected,"epoch_already_funded"):
                epoch.activate_after_operator_verification(epoch.epoch_id,epoch.wallet,usdc_balance_minor=50_000_000,gas_balance_wei=1)
            epoch.close()
            with self.assertRaisesRegex(Rejected,"epoch_closed"): epoch.public_descriptor()
            with self.assertRaisesRegex(Rejected,"payout_paused"): epoch.require_active()
        finally: epoch.close()
    def test_external_key_survives_closed_epoch_but_new_ledger_is_paused(self):
        first=synthetic_epoch();signer=first._signer;first.close()
        with patch("transcripts.epoch._require_nsm"):
            second=BootEpoch.create(signer)
        try:
            self.assertEqual(first.wallet,second.wallet)
            with self.assertRaisesRegex(Rejected,"payout_paused"):second.require_active()
            proof=second.check_payout_signing(0)
            self.assertTrue(proof['signingVerified']);self.assertFalse(proof['broadcast'])
            self.assertEqual(proof['wallet'],second.wallet)
            self.assertEqual(set(proof),{'keyId','wallet','signingVerified','broadcast','transactionHash'})
            second.activate_after_operator_verification(second.epoch_id,second.wallet,
                usdc_balance_minor=50_000_000,gas_balance_wei=1)
            with self.assertRaisesRegex(Rejected,'preflight_requires_paused'):second.check_payout_signing(0)
        finally:second.close()
    def test_smaller_measured_budget_limits_reservations_to_actual_funding(self):
        epoch=synthetic_epoch(budget_minor=5_000_000)
        try:
            self.assertEqual(epoch.public_descriptor()['budgetMinor'],5_000_000)
            with self.assertRaisesRegex(Rejected,'epoch_funding_mismatch'):
                epoch.activate_after_operator_verification(epoch.epoch_id,epoch.wallet,
                    usdc_balance_minor=50_000_000,gas_balance_wei=1)
            epoch.activate_after_operator_verification(epoch.epoch_id,epoch.wallet,
                usdc_balance_minor=5_000_000,gas_balance_wei=1)
            policy=campaign();policy["rewardMinor"]=5_000_000;epoch.ledger.reserve(policy,request(policy),NOW)
            second=request(policy);second['payoutAddress']='0x'+'3'*40
            with self.assertRaisesRegex(Rejected,'budget_exhausted'):
                epoch.ledger.reserve(policy,second,NOW)
        finally:epoch.close()
    def test_arbitrary_local_signer_rejected(self):
        with patch("transcripts.epoch._require_nsm"):
            with self.assertRaisesRegex(Rejected,'kms_signer_required'):BootEpoch.create(object())
    def test_anchor_rejects_replay_revision_jump_and_cannot_serialize(self):
        anchor=_EpochAnchor();anchor.advance(None,(0,"0"*64))
        with self.assertRaisesRegex(Rejected,"state_rollback"): anchor.advance(None,(0,"0"*64))
        with self.assertRaisesRegex(Rejected,"state_rollback"): anchor.advance((0,"0"*64),(2,"1"*64))
        anchor.advance((0,"0"*64),(1,"1"*64))
        with self.assertRaises(TypeError): pickle.dumps(anchor)
        anchor._close()
        with self.assertRaisesRegex(Rejected,"epoch_closed"): anchor.read()

if __name__ == "__main__": unittest.main()
