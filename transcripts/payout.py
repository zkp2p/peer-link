"""Dependency-injected reconciliation of one immutable, bounded USDC payment."""
import time
from .common import fields, require


class PayoutCoordinator:
    """Transport must validate exact chain, token, recipient, amount and tx hash.

    sign(job_id, recipient, reward_minor) -> (signed_bytes, transaction_id)
    validate(signed_bytes, transaction_id, recipient, reward_minor) -> True
    broadcast(signed_bytes, transaction_id): retries rebroadcast identical bytes
    confirmed(transaction_id, recipient, reward_minor) -> bool

    Confirmed must check a successful finalized receipt and the exact USDC transfer
    event, rather than only a transaction existing. Exceptions leave payout_pending.
    Live transport owns key custody, nonce serialization and gas limits. No fallback
    signer, endpoint or mock-success implementation is provided here.
    """
    def __init__(self, ledger, transport):
        self.ledger, self.transport = ledger, transport

    def reconcile(self, job_id, now=None):
        now = time.time() if now is None else now
        status = self.ledger.status(job_id)
        require(self.ledger.anchor is not None, "payout_anchor_unavailable")
        require(status["state"] in {"accepted", "payout_pending", "paid"}, "payout_ineligible")
        if status["state"] == "paid":
            return status
        recipient, amount = status["payoutAddress"], status["rewardMinor"]
        if status["state"] == "accepted":
            signed, tx_id = self.transport.sign(job_id, recipient, amount)
            require(self.transport.validate(signed, tx_id, recipient, amount) is True, "invalid_transaction")
            # If a competing coordinator has already persisted another identity this
            # fails before either competing transaction can be broadcast here.
            self.ledger.prepare_payout(job_id, signed, tx_id)
        signed, tx_id = self.ledger.payout_identity(job_id)
        require(self.transport.validate(signed, tx_id, recipient, amount) is True, "invalid_transaction")
        if self.transport.confirmed(tx_id, recipient, amount) is True:
            return self.ledger.mark_paid(job_id, tx_id, now)
        self.transport.broadcast(signed, tx_id)
        if self.transport.confirmed(tx_id, recipient, amount) is True:
            return self.ledger.mark_paid(job_id, tx_id, now)
        return self.ledger.status(job_id)


class RetirementCoordinator:
    """One operator-initiated epoch retirement/refund, never a reward or refill.

    Runtime must first call epoch.begin_retirement_after_operator_verification()
    from its existing signed operator control plane and ensure pending archive
    records are empty. Existing financial obligations must finish before this runs.
    New admissions stay permanently closed even if the sweep encounters an error.
    The fixed measured refund recipient cannot be supplied by this interface.
    """
    def __init__(self,epoch,transport):
        self.epoch,self.ledger,self.transport=epoch,epoch.ledger,transport

    def reconcile(self):
        status=self.ledger.retirement_status()
        if status["state"] in {"closing","retired"}:
            for payment in self.ledger.paid_payments():
                require(self.transport.confirmed(payment["transactionId"],payment["payoutAddress"],
                                                 payment["rewardMinor"]) is True,"retirement_payments_uncertain")
        self.epoch.finalize_retirement() # Refuses every unfinished contribution/payment.
        with self.epoch.retirement_guard():
            status=self.ledger.retirement_status()
            if status["state"] == "refunded":
                return self.epoch.retirement_status()
            if status["state"] == "retired":
                amount,_gas=self.transport.funding_balances()
                if amount == 0:
                    self.ledger.finish_empty_refund()
                    return self.epoch.retirement_status()
                signed,tx_id=self.transport.sign_refund(amount)
                require(self.transport.validate_refund(signed,tx_id,amount) is True,"invalid_refund")
                self.ledger.prepare_refund(amount,signed,tx_id) # Before any broadcast.
            signed,tx_id,amount=self.ledger.refund_identity()
            require(self.transport.validate_refund(signed,tx_id,amount) is True,"invalid_refund")
            if self.transport.confirmed_refund(tx_id,amount) is True:
                self.ledger.mark_refunded(tx_id)
                return self.epoch.retirement_status()
            self.transport.broadcast_refund(signed,tx_id)
            if self.transport.confirmed_refund(tx_id,amount) is True:
                self.ledger.mark_refunded(tx_id)
            return self.epoch.retirement_status()
