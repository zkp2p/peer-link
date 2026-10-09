"""Paused Nitro epoch with recoverable KMS payout custody and optional durable state.

Durable v3 encrypts the authoritative job/dedup/payment snapshot under a Recipient
KMS key and uses fenced, capability-authenticated Lambda CAS. Restart restores
that exact policy/namespace, keeps the receipt signer, creates fresh ingress keys,
and requires signed operator review before new admissions or payment signing.
Legacy v2 remains explicitly RAM-only. Every descriptor is attestation-bound.
"""
import hashlib
import os
import platform
import secrets
import threading
import time
from contextlib import contextmanager
from .common import address, digest, fields, hex_digest, integer, require
from .ledger import Ledger
from .policy import MAX_BUDGET

CHAIN_ID = 8453
DEPLOYER_REFUND_ADDRESS = "0x84e113087c97cd80ea9d78983d4b8ff61eca1929"
USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
MAX_GAS_FUNDING_WEI = 3_000_000_000_000_000  # 0.003 ETH; no automatic refill


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
    """Construct only inside Nitro with a measured KMS signing authority.

    Internal enclave code receives ledger, accept(), and sign_transaction(). Public
    endpoints may return only public_descriptor(); never expose Python attributes.
    activate_after_operator_verification() is an internal control-plane operation,
    never a contributor API. Caller must verify operator authorization and fresh
    attestation for this descriptor, then independently inspect funding evidence.
    """
    def __init__(self, payout_signer, *, budget_minor=MAX_BUDGET, state_anchor=None, initial_snapshot=None):
        _require_nsm()
        from .kms_signer import KmsSigner
        require(isinstance(payout_signer, KmsSigner), "kms_signer_required")
        self.budget_minor = integer(budget_minor, 5_000_000, MAX_BUDGET, "invalid_pilot_budget")
        self._lock = threading.RLock()
        self._alive, self._active, self._funded_once = True, False, False
        self._integrity_key, self._dedup_key = secrets.token_bytes(32), secrets.token_bytes(32)
        self._signer = payout_signer
        self.epoch_id = secrets.token_hex(16)
        self.wallet = self._signer.address.lower()
        self._anchor = state_anchor or _EpochAnchor()
        self.durable=state_anchor is not None
        if self.durable:
            from .channel import ReceiptSigner
            self._integrity_key=state_anchor.keys['integrity'];self._dedup_key=state_anchor.keys['dedup']
            previous=initial_snapshot['runtime'] if initial_snapshot else None
            self.receipt_signer=ReceiptSigner(bytes.fromhex(previous['receiptPrivateKey']) if previous else None)
            if previous:self.epoch_id=previous['epochId'];self._funded_once=previous['fundedOnce']
            runtime={'epochId':self.epoch_id,'receiptPrivateKey':self.receipt_signer.private_der().hex(),
                     'fundedOnce':self._funded_once,'active':False,'operatorNonces':{},'bootId':secrets.token_hex(16)}
            self.ledger=Ledger(':memory:',self._integrity_key,global_budget_minor=self.budget_minor,anchor=state_anchor,
                               initial_snapshot=initial_snapshot,initial_runtime=runtime)
            if previous:self.ledger.recover_restart(int(time.time()),runtime['bootId'])
        else:self.ledger = Ledger(":memory:", self._integrity_key, global_budget_minor=self.budget_minor, anchor=self._anchor)

    @classmethod
    def create(cls, payout_signer, *, budget_minor=MAX_BUDGET, state_anchor=None, initial_snapshot=None):
        return cls(payout_signer, budget_minor=budget_minor,state_anchor=state_anchor,initial_snapshot=initial_snapshot)

    def public_descriptor(self):
        with self._lock:
            require(self._alive, "epoch_closed")
            result={"version": 2, "epochId": self.epoch_id, "payoutWallet": self.wallet,
                    "chainId": CHAIN_ID, "usdcContract": USDC_ADDRESS, "budgetMinor": self.budget_minor,
                    "maxGasFundingWei": MAX_GAS_FUNDING_WEI, "payoutKeyCustody": "aws_kms",
                    "payoutKeyId": self._signer.key_id, "operatorRecovery": True,
                    "ledgerPersistence": "enclave_ram_only", "restartRequiresOperatorReview": True}
            if self.durable:
                result.update(version=3,ledgerPersistence='aws_dynamodb_encrypted_snapshot',
                              stateNamespace=self._anchor.config['namespace'],stateAuthorityArn=self._anchor.config['functionArn'],
                              stateWrappingKeyId=self._anchor.config['wrappingKeyId'])
            return result

    def check_payout_signing(self, nonce):
        """Operator-only pre-funding probe. Sign a one-unit refund without broadcast.

        This validates real KMS signing against the measured public wallet while
        paused. No raw transaction is returned or broadcast by this method. The
        trusted host sees the digest and signature and can reconstruct it, just
        as its IAM authority can sign independently of this enclave.
        """
        from .eth_payout import refund_data
        with self._lock:
            require(self._alive and not self._active, "preflight_requires_paused")
            transaction = {"type": 2, "chainId": CHAIN_ID, "nonce": nonce,
                           "to": USDC_ADDRESS, "value": 0, "data": refund_data(1),
                           "gas": 100000, "maxFeePerGas": 10000000,
                           "maxPriorityFeePerGas": 1000000, "accessList": []}
            signed = self._signer.sign_transaction(transaction)
            return {"keyId": self._signer.key_id, "wallet": self.wallet,
                    "signingVerified": True, "broadcast": False,
                    "transactionHash": "0x" + bytes(signed.hash).hex()}

    def binding_digest(self):
        return digest(self.public_descriptor())

    def activate_after_operator_verification(self, epoch_id, wallet, *, usdc_balance_minor, gas_balance_wei):
        with self._lock:
            require(self._alive and epoch_id == self.epoch_id and address(wallet) == self.wallet, "epoch_binding_mismatch")
            require(not self.ledger.retirement_status()["admissionsClosed"],"admissions_closed")
            require(not self._funded_once, "epoch_already_funded")
            require(usdc_balance_minor == self.budget_minor, "epoch_funding_mismatch")
            integer(gas_balance_wei, 1, MAX_GAS_FUNDING_WEI, "epoch_gas_funding_mismatch")
            if self.durable:self.ledger.update_runtime({'fundedOnce':True,'active':True})
            self._funded_once, self._active = True, True

    def pause(self):
        with self._lock:
            self._active = False
            if self.durable:self.ledger.update_runtime({'active':False})

    def resume_after_operator_verification(self, epoch_id):
        with self._lock:
            require(self._alive and self._funded_once and epoch_id == self.epoch_id, "epoch_binding_mismatch")
            require(self.ledger.retirement_status()["state"] in {"open","closing"},"epoch_retired")
            if self.durable:self.ledger.update_runtime({'active':True})
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

    def accept(self, job_id, reads, model_result, *, now, evidence=None, policy=None):
        with self._lock:
            self.require_active()
            return self.ledger.accept(job_id, reads, model_result, dedup_key=self._dedup_key, now=now,evidence=evidence,policy=policy)

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
                # Drop local references. Payout custody remains in operator KMS;
                # durable private state stays encrypted under Recipient-only KMS.
                self._signer = self._integrity_key = self._dedup_key = None

    def __repr__(self):
        return "<BootEpoch private state redacted>"

    def __reduce__(self):
        raise TypeError("epoch_not_serializable")
