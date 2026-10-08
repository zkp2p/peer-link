"""Synthetic non-restorable epoch tests; no live key generation or funding."""
import copy
import pickle
import unittest
from unittest.mock import patch
from transcripts.common import Rejected
from transcripts.epoch import BootEpoch, MAX_GAS_FUNDING_WEI, _EpochAnchor
from transcripts.tests.test_core import campaign, request, NOW


def synthetic_epoch(index=1):
    # Fixed public test fixtures; never call the real wallet entropy source here.
    with patch("transcripts.epoch._require_nsm"), patch("transcripts.epoch.secrets.token_bytes",
            side_effect=[b"i"*32,b"d"*32,index.to_bytes(32,"big")]), \
            patch("transcripts.epoch.secrets.token_hex",return_value=f"{index:032x}"):
        return BootEpoch.create()


class EpochTests(unittest.TestCase):
    def test_normal_host_refuses_before_wallet_generation(self):
        with patch("transcripts.epoch.platform.system",return_value="Darwin"), \
                patch("transcripts.epoch.secrets.token_bytes",side_effect=AssertionError("must not generate")):
            with self.assertRaisesRegex(Rejected,"epoch_requires_nitro"): BootEpoch.create()
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
            self.assertNotIn("key",str(descriptor).lower())
            self.assertTrue(descriptor["nonRestorable"])
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
    def test_anchor_rejects_replay_revision_jump_and_cannot_serialize(self):
        anchor=_EpochAnchor();anchor.advance(None,(0,"0"*64))
        with self.assertRaisesRegex(Rejected,"state_rollback"): anchor.advance(None,(0,"0"*64))
        with self.assertRaisesRegex(Rejected,"state_rollback"): anchor.advance((0,"0"*64),(2,"1"*64))
        anchor.advance((0,"0"*64),(1,"1"*64))
        with self.assertRaises(TypeError): pickle.dumps(anchor)
        anchor._close()
        with self.assertRaisesRegex(Rejected,"epoch_closed"): anchor.read()

if __name__ == "__main__": unittest.main()
