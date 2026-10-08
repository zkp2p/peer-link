"""Non-restorable, RAM-only Nitro payout epoch for the capped pilot.

This deliberately offers no recovery/restore/seal/import API. Enclave restart loses
keys, account dedup history and pending-payment reconciliation. A new epoch starts
paused with a new unfunded wallet; operator approval is required for every funding.
The public descriptor MUST be bound into independently verified Nitro attestation.
"""
import hashlib
import os
import platform
import secrets
import threading
from contextlib import contextmanager
from .common import address, digest, fields, hex_digest, integer, require
from .ledger import Ledger
from .policy import MAX_BUDGET

CHAIN_ID = 8453
DEPLOYER_REFUND_ADDRESS = "0x84e113087c97cd80ea9d78983d4b8ff61eca1929"
USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
MAX_GAS_FUNDING_WEI = 3_000_000_000_000_000  # 0.003 ETH; no automatic refill
SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _require_nsm():
    require(platform.system() == "Linux" and platform.machine() == "x86_64" and os.path.exists("/dev/nsm"),
            "epoch_requires_nitro")
    from verification.nsm import attest
    # This checks driver availability, not release authenticity. Contributors and
    # the funding operator independently verify the descriptor-bound real quote.
    attest(secrets.token_bytes(32), b"peer-link-epoch-bootstrap", hashlib.sha256(b"peer-link-epoch-v1").digest())


class _EpochAnchor:
    """Monotonic RAM authority valid only while its owning enclave epoch survives."""
    def __init__(self):
        self._value, self._alive, self._lock = None, True, threading.RLock()
    def read(self):
        with self._lock:
            require(self._alive, "epoch_closed")
            return self._value
    def advance(self, expected, value):
        with self._lock:
            require(self._alive and self._value == expected, "state_rollback")
            require(isinstance(value, tuple) and len(value) == 2, "state_rollback")
            integer(value[0], 0, 2**63-1, "state_rollback")
            hex_digest(value[1])
            require(value[0] == (0 if expected is None else expected[0]+1), "state_rollback")
            self._value = value
    def _close(self):
        with self._lock:
            self._alive, self._value = False, None
    def __reduce__(self):
        raise TypeError("epoch_not_serializable")


class BootEpoch:
    """Construct only inside Nitro; no private-key/configuration inputs accepted.

    Internal enclave code receives ledger, accept(), and sign_transaction(). Public
    endpoints may return only public_descriptor(); never expose Python attributes.
    activate_after_operator_verification() is an internal control-plane operation,
    never a contributor API. Caller must verify operator authorization and fresh
    attestation for this descriptor, then independently inspect funding evidence.
    """
    def __init__(self):
        _require_nsm()  # Fail before generating any wallet on a normal host.
        from eth_account import Account
        self._lock = threading.RLock()
        self._alive, self._active, self._funded_once = True, False, False
        self._integrity_key, self._dedup_key = secrets.token_bytes(32), secrets.token_bytes(32)
        key = secrets.token_bytes(32)
        while not 0 < int.from_bytes(key, "big") < SECP256K1_ORDER:
            key = secrets.token_bytes(32)
        self._signer = Account.from_key(key)
        self.epoch_id = secrets.token_hex(16)
        self.wallet = self._signer.address.lower()
        self._anchor = _EpochAnchor()
        self.ledger = Ledger(":memory:", self._integrity_key, global_budget_minor=MAX_BUDGET, anchor=self._anchor)

    @classmethod
    def create(cls):
        return cls()

    def public_descriptor(self):
        with self._lock:
            require(self._alive, "epoch_closed")
            return {"version": 1, "epochId": self.epoch_id, "payoutWallet": self.wallet,
                    "chainId": CHAIN_ID, "usdcContract": USDC_ADDRESS, "budgetMinor": MAX_BUDGET,
                    "maxGasFundingWei": MAX_GAS_FUNDING_WEI, "nonRestorable": True,
                    "persistence": "enclave_ram_only"}

    def binding_digest(self):
        return digest(self.public_descriptor())

    def activate_after_operator_verification(self, epoch_id, wallet, *, usdc_balance_minor, gas_balance_wei):
        with self._lock:
            require(self._alive and epoch_id == self.epoch_id and address(wallet) == self.wallet, "epoch_binding_mismatch")
            require(not self.ledger.retirement_status()["admissionsClosed"],"admissions_closed")
            require(not self._funded_once, "epoch_already_funded")
            require(usdc_balance_minor == MAX_BUDGET, "epoch_funding_mismatch")
            integer(gas_balance_wei, 1, MAX_GAS_FUNDING_WEI, "epoch_gas_funding_mismatch")
            self._funded_once, self._active = True, True

    def pause(self):
        with self._lock:
            self._active = False

    def resume_after_operator_verification(self, epoch_id):
        with self._lock:
            require(self._alive and self._funded_once and epoch_id == self.epoch_id, "epoch_binding_mismatch")
            require(self.ledger.retirement_status()["state"] in {"open","closing"},"epoch_retired")
            self._active = True

    def require_admission(self):
        with self._lock:
            self.require_active()
            require(not self.ledger.retirement_status()["admissionsClosed"],"admissions_closed")

    def begin_retirement_after_operator_verification(self, epoch_id, *, now):
        with self._lock:
            require(self._alive and epoch_id == self.epoch_id,"epoch_binding_mismatch")
            return self.ledger.begin_retirement(now)

    def finalize_retirement(self):
        with self._lock:
            require(self._alive,"epoch_closed")
            status=self.ledger.finalize_retirement()
            self._active=False
            return status

    def retirement_status(self):
        return {**self.ledger.retirement_status(),"refundAddress":DEPLOYER_REFUND_ADDRESS}

    @contextmanager
    def retirement_guard(self):
        with self._lock:
            require(self._alive and self.ledger.retirement_status()["state"] in
                    {"retired","refund_pending","refunded"},"retirement_ineligible")
            require(self.ledger.retirement_status()["obligations"] == 0,"retirement_obligations_pending")
            yield

    def sign_retirement_transaction(self,transaction):
        with self.retirement_guard():
            from .eth_payout import refund_data,MAX_FEE_WEI,MAX_PRIORITY_FEE_WEI,MAX_GAS
            fields(transaction,{"type","chainId","nonce","to","value","data","gas","maxFeePerGas",
                                "maxPriorityFeePerGas","accessList"})
            require(type(transaction["type"]) is int and transaction["type"] == 2
                    and type(transaction["chainId"]) is int and transaction["chainId"] == CHAIN_ID
                    and address(transaction["to"]) == USDC_ADDRESS and transaction["value"] == 0
                    and transaction["accessList"] == [],"invalid_refund")
            data=transaction["data"]
            require(isinstance(data,bytes) and len(data) == 68,"invalid_refund")
            require(data == refund_data(int.from_bytes(data[-32:],"big")),"invalid_refund")
            integer(transaction["nonce"],0,2**64-1,"invalid_refund")
            integer(transaction["gas"],21000,MAX_GAS,"invalid_refund")
            fee=integer(transaction["maxFeePerGas"],1,MAX_FEE_WEI,"invalid_refund")
            integer(transaction["maxPriorityFeePerGas"],0,min(fee,MAX_PRIORITY_FEE_WEI),"invalid_refund")
            return self._signer.sign_transaction(transaction)

    def require_active(self):
        with self._lock:
            require(self._alive and self._funded_once and self._active, "payout_paused")
            require(self.ledger.retirement_status()["state"] in {"open","closing"},"epoch_retired")

    @contextmanager
    def payment_guard(self):
        """Serialize pause against signing/broadcast. Control-plane pause returns
        only after an already-authorized in-flight operation has completed.
        """
        with self._lock:
            self.require_active()
            yield

    def accept(self, job_id, reads, model_result, *, now):
        with self._lock:
            self.require_active()
            return self.ledger.accept(job_id, reads, model_result, dedup_key=self._dedup_key, now=now)

    def sign_transaction(self, transaction):
        with self._lock:
            self.require_active()
            return self._signer.sign_transaction(transaction)

    def close(self):
        with self._lock:
            if self._alive:
                self._active, self._alive = False, False
                self.ledger.close()
                self._anchor._close()
                # Drop references. Python does not guarantee zeroization; enclave
                # destruction is the key-erasure boundary, not this convenience.
                self._signer = self._integrity_key = self._dedup_key = None

    def __repr__(self):
        return "<BootEpoch private state redacted>"

    def __reduce__(self):
        raise TypeError("epoch_not_serializable")
