"""Atomic admission, authenticated persistence and immutable payout identities.

SQLite serializes replicas sharing this file. Independent database copies are not
an admission authority: live payouts require a trusted external monotonic anchor.
A lost anchor update fails closed and needs operator reconciliation, never resets.
"""
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from functools import wraps
from contextlib import contextmanager
from .common import canonical, digest, fields, hex_digest, integer, opaque_id, require
from .policy import MAX_BUDGET, validate_reservation
from .artifacts import account_fingerprint, extract_artifact
from .recipe import validate_live_reads

NONPAYMENT = {"rejected", "expired", "cancelled"}
RESERVED = {"reserved", "submitted", "verifying", "accepted", "payout_pending", "paid"}
REASONS = {"insufficient_evidence", "insufficient_history", "duplicate_account", "duplicate_recipient",
           "bank_read_failed", "unauthenticated_source", "source_not_allowed", "model_rejected",
           "model_result_invalid", "unsafe_artifact", "job_expired", "cancelled", "provider_failed",
           "invalid_submission", "consent_required", "account_evidence_missing", "ambiguous_account",
           "policy_mismatch", "stale_evidence", "limits_exceeded", "storage_unavailable"}


def _locked(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return invoke


class Ledger:
    def __init__(self, path, integrity_key, *, global_budget_minor=MAX_BUDGET, anchor=None):
        require(isinstance(integrity_key, bytes) and len(integrity_key) >= 32, "state_key_unavailable")
        integer(global_budget_minor, 1, MAX_BUDGET, "invalid_budget")
        self.key, self.anchor = integrity_key, anchor
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
                                         budget INTEGER NOT NULL, mac TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL,
          state TEXT NOT NULL, campaign TEXT NOT NULL, request TEXT NOT NULL, binding TEXT NOT NULL,
          created_at INTEGER NOT NULL, submitted_at INTEGER, expires_at INTEGER NOT NULL,
          reward INTEGER NOT NULL, recipient TEXT NOT NULL, reason TEXT, account_hmac TEXT,
          artifact TEXT, artifact_digest TEXT, tx_id TEXT UNIQUE, signed_tx BLOB, paid_at INTEGER);
        CREATE TABLE IF NOT EXISTS retirement (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL,
          amount INTEGER, tx_id TEXT, signed_tx BLOB);
        CREATE UNIQUE INDEX IF NOT EXISTS accepted_account ON jobs(campaign_id,account_hmac)
          WHERE state IN ('accepted','payout_pending','paid');
        CREATE UNIQUE INDEX IF NOT EXISTS accepted_recipient ON jobs(campaign_id,recipient)
          WHERE state IN ('accepted','payout_pending','paid');
        """)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            meta = self.db.execute("SELECT * FROM meta WHERE id=1").fetchone()
            if meta is None:
                require(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0, "state_integrity")
                # An existing external anchor makes a newly empty database a replay.
                require(anchor is None or anchor.read() is None, "state_rollback")
                self.db.execute("INSERT INTO meta VALUES (1,0,?, '')", (global_budget_minor,))
                self.db.execute("INSERT INTO retirement VALUES (1,'open',NULL,NULL,NULL)")
                self.db.execute("UPDATE meta SET mac=? WHERE id=1", (self._mac(),))
                if anchor is not None:
                    anchor.advance(None, self._anchor_value())
            else:
                require(meta["budget"] == global_budget_minor, "budget_mismatch")
                self._verify()
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @_locked
    def close(self):
        self.db.close()

    def _snapshot(self):
        meta = self.db.execute("SELECT revision,budget FROM meta WHERE id=1").fetchone()
        rows = []
        for row in self.db.execute("SELECT * FROM jobs ORDER BY id"):
            item = dict(row)
            if item["signed_tx"] is not None:
                item["signed_tx"] = bytes(item["signed_tx"]).hex()
            rows.append(item)
        retirement = self.db.execute("SELECT * FROM retirement WHERE id=1").fetchone()
        require(retirement is not None, "state_integrity")
        retirement = dict(retirement)
        if retirement["signed_tx"] is not None:
            retirement["signed_tx"] = bytes(retirement["signed_tx"]).hex()
        return {"revision": meta["revision"], "budget": meta["budget"], "jobs": rows, "retirement": retirement}

    def _mac(self):
        return hmac.new(self.key, b"peer-link-ledger-v1\0" + canonical(self._snapshot()), hashlib.sha256).hexdigest()

    def _anchor_value(self):
        meta = self.db.execute("SELECT revision,mac FROM meta WHERE id=1").fetchone()
        return (meta["revision"], meta["mac"])

    def _verify(self):
        meta = self.db.execute("SELECT mac FROM meta WHERE id=1").fetchone()
        require(meta is not None and hmac.compare_digest(meta["mac"], self._mac()), "state_integrity")
        require(self.anchor is None or self.anchor.read() == self._anchor_value(), "state_rollback")

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._verify()
            old_anchor = self._anchor_value()
            yield
            self.db.execute("UPDATE meta SET revision=revision+1 WHERE id=1")
            self.db.execute("UPDATE meta SET mac=? WHERE id=1", (self._mac(),))
            new_anchor = self._anchor_value()
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        if self.anchor is not None:
            # Crash after commit leaves anchor mismatch. Availability is sacrificed
            # for explicit reconciliation; no live payment can proceed on a replay.
            self.anchor.advance(old_anchor, new_anchor)

    def _job(self, job_id):
        opaque_id(job_id)
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        require(row is not None, "job_not_found")
        return row

    @_locked
    def reserve(self, campaign, request, now):
        validate_reservation(campaign, request, now)
        with self._transaction():
            require(self.db.execute("SELECT state FROM retirement WHERE id=1").fetchone()[0] == "open",
                    "admissions_closed")
            self.db.execute("UPDATE jobs SET state='expired',reason='job_expired' WHERE expires_at<=? "
                            "AND state IN ('reserved','submitted','verifying')", (now,))
            active = self.db.execute("SELECT count(*) FROM jobs WHERE campaign_id=? AND state IN "
                                    "('reserved','submitted','verifying','accepted','payout_pending','paid')",
                                    (campaign["id"],)).fetchone()[0]
            require(active < campaign["maxContributors"], "campaign_capacity")
            spent = self.db.execute("SELECT COALESCE(sum(reward),0) FROM jobs WHERE state IN "
                                   "('reserved','submitted','verifying','accepted','payout_pending','paid')").fetchone()[0]
            budget = self.db.execute("SELECT budget FROM meta WHERE id=1").fetchone()[0]
            require(spent + campaign["rewardMinor"] <= budget, "budget_exhausted")
            recipient = request["payoutAddress"].lower()
            require(self.db.execute("SELECT 1 FROM jobs WHERE campaign_id=? AND recipient=? AND state IN "
                                    "('reserved','submitted','verifying','accepted','payout_pending','paid')",
                                    (campaign["id"], recipient)).fetchone() is None, "duplicate_recipient")
            job_id = secrets.token_hex(16)
            binding = digest({"jobId": job_id, "campaign": campaign, "request": request})
            self.db.execute("INSERT INTO jobs (id,campaign_id,state,campaign,request,binding,created_at,expires_at,reward,recipient) "
                            "VALUES (?,?,'reserved',?,?,?,?,?,?,?)", (job_id,campaign["id"],canonical(campaign).decode(),
                            canonical(request).decode(),binding,int(now),request["expiresAt"],campaign["rewardMinor"],recipient))
        return self.status(job_id)

    @_locked
    def status(self, job_id):
        # Read under a SQLite snapshot to avoid MAC/revision races with other replicas.
        self.db.execute("BEGIN")
        try:
            self._verify()
            row = self._job(job_id)
            result = {"jobId": row["id"], "campaignId": row["campaign_id"], "state": row["state"],
                      "bindingDigest": row["binding"], "expiresAt": row["expires_at"],
                      "rewardMinor": row["reward"], "payoutAddress": row["recipient"], "reason": row["reason"],
                      "artifactDigest": row["artifact_digest"], "transactionId": row["tx_id"]}
            self.db.execute("COMMIT")
            return result
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @contextmanager
    def _read(self):
        self.db.execute("BEGIN")
        try:
            self._verify()
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @_locked
    def terms(self, job_id):
        with self._read():
            row = self._job(job_id)
            return {"campaign": json.loads(row["campaign"]), "request": json.loads(row["request"]),
                    "submittedAt": row["submitted_at"], "createdAt": row["created_at"]}

    @_locked
    def submit(self, job_id, binding_digest, now):
        with self._transaction():
            row = self._job(job_id)
            require(row["state"] == "reserved", "job_replayed")
            require(row["expires_at"] > now, "job_expired")
            require(row["binding"] == binding_digest, "binding_mismatch")
            self.db.execute("UPDATE jobs SET state='submitted',submitted_at=? WHERE id=?", (int(now),job_id))
        return self.status(job_id)

    @_locked
    def begin_verification(self, job_id, now):
        with self._transaction():
            row = self._job(job_id)
            require(row["state"] == "submitted", "invalid_transition")
            require(row["expires_at"] > now, "job_expired")
            self.db.execute("UPDATE jobs SET state='verifying' WHERE id=?", (job_id,))
        return self.status(job_id)

    @_locked
    def reject(self, job_id, reason):
        require(reason in REASONS, "invalid_reason")
        with self._transaction():
            row = self._job(job_id)
            require(row["state"] in {"reserved","submitted","verifying"}, "invalid_transition")
            self.db.execute("UPDATE jobs SET state='rejected',reason=? WHERE id=?", (reason,job_id))
        return self.status(job_id)

    @_locked
    def cancel(self, job_id):
        with self._transaction():
            require(self._job(job_id)["state"] in {"reserved","submitted"}, "invalid_transition")
            self.db.execute("UPDATE jobs SET state='cancelled',reason='cancelled' WHERE id=?", (job_id,))
        return self.status(job_id)

    @_locked
    def accept(self, job_id, reads, model_result, *, dedup_key, now):
        with self._transaction():
            row = self._job(job_id)
            require(row["state"] == "verifying", "invalid_transition")
            require(row["expires_at"] > now, "job_expired")
            campaign, request = json.loads(row["campaign"]), json.loads(row["request"])
            account_id = validate_live_reads(campaign, reads, job_id, row["submitted_at"], now,
                                             request["limits"]["maxBankReads"])
            artifact = extract_artifact(campaign, reads)
            fields(model_result, {"rubricVersion", "score", "useful"})
            require(model_result["rubricVersion"] == campaign["rubricVersion"], "model_result_invalid")
            integer(model_result["score"], 0, 100, "model_result_invalid")
            require(type(model_result["useful"]) is bool, "model_result_invalid")
            require(model_result["useful"] and model_result["score"] >= campaign["evidenceRequirements"]["minScore"],
                    "model_rejected")
            fingerprint = account_fingerprint(dedup_key, campaign["id"], account_id)
            require(self.db.execute("SELECT 1 FROM jobs WHERE campaign_id=? AND account_hmac=? AND state IN "
                                    "('accepted','payout_pending','paid')", (campaign["id"],fingerprint)).fetchone() is None,
                    "duplicate_account")
            self.db.execute("UPDATE jobs SET state='accepted',account_hmac=?,artifact=?,artifact_digest=? WHERE id=?",
                            (fingerprint,canonical(artifact).decode(),digest(artifact),job_id))
        return self.status(job_id)

    @_locked
    def artifact(self, job_id):
        with self._read():
            row = self._job(job_id)
            require(row["artifact"] is not None, "artifact_unavailable")
            return json.loads(row["artifact"])

    @_locked
    def prepare_payout(self, job_id, signed_tx, tx_id):
        require(self.anchor is not None, "payout_anchor_unavailable")
        require(isinstance(signed_tx, bytes) and 1 <= len(signed_tx) <= 65536, "invalid_transaction")
        require(isinstance(tx_id, str) and 1 <= len(tx_id) <= 100, "invalid_transaction")
        with self._transaction():
            row = self._job(job_id)
            if row["state"] in {"payout_pending","paid"}:
                require(bytes(row["signed_tx"]) == signed_tx and row["tx_id"] == tx_id, "payout_identity_mismatch")
            else:
                require(row["state"] == "accepted" and row["artifact_digest"] is not None, "payout_ineligible")
                self.db.execute("UPDATE jobs SET state='payout_pending',signed_tx=?,tx_id=? WHERE id=?",
                                (signed_tx,tx_id,job_id))
        return self.status(job_id)

    @_locked
    def payout_identity(self, job_id):
        require(self.anchor is not None, "payout_anchor_unavailable")
        with self._read():
            row = self._job(job_id)
            require(row["state"] in {"payout_pending","paid"}, "payout_ineligible")
            return bytes(row["signed_tx"]), row["tx_id"]

    @_locked
    def mark_paid(self, job_id, tx_id, now):
        require(self.anchor is not None, "payout_anchor_unavailable")
        with self._transaction():
            row = self._job(job_id)
            require(row["state"] in {"payout_pending","paid"} and row["tx_id"] == tx_id, "payout_identity_mismatch")
            if row["state"] == "payout_pending":
                self.db.execute("UPDATE jobs SET state='paid',paid_at=? WHERE id=?", (int(now),job_id))
        return self.status(job_id)


    @_locked
    def begin_retirement(self, now):
        """Permanent admission closure; unused reservations are safely cancelled.
        Existing submitted/verification/payment obligations must settle normally.
        """
        require(self.anchor is not None, "payout_anchor_unavailable")
        with self._transaction():
            state = self.db.execute("SELECT state FROM retirement WHERE id=1").fetchone()[0]
            if state == "open":
                self.db.execute("UPDATE retirement SET state='closing' WHERE id=1")
                self.db.execute("UPDATE jobs SET state=CASE WHEN expires_at<=? THEN 'expired' ELSE 'cancelled' END, "
                                "reason=CASE WHEN expires_at<=? THEN 'job_expired' ELSE 'cancelled' END "
                                "WHERE state='reserved'", (now,now))
        return self.retirement_status()

    @_locked
    def retirement_status(self):
        with self._read():
            row = self.db.execute("SELECT * FROM retirement WHERE id=1").fetchone()
            obligations = self.db.execute("SELECT count(*) FROM jobs WHERE state IN "
                "('reserved','submitted','verifying','accepted','payout_pending')").fetchone()[0]
            return {"state":row["state"], "amountMinor":row["amount"], "transactionId":row["tx_id"],
                    "obligations":obligations, "admissionsClosed":row["state"] != "open"}

    @_locked
    def finalize_retirement(self):
        require(self.anchor is not None, "payout_anchor_unavailable")
        with self._transaction():
            state = self.db.execute("SELECT state FROM retirement WHERE id=1").fetchone()[0]
            require(state != "open", "admissions_not_closed")
            require(self.db.execute("SELECT count(*) FROM jobs WHERE state IN "
                "('reserved','submitted','verifying','accepted','payout_pending')").fetchone()[0] == 0,
                "retirement_obligations_pending")
            if state == "closing":
                self.db.execute("UPDATE retirement SET state='retired' WHERE id=1")
        return self.retirement_status()

    @_locked
    def prepare_refund(self, amount, signed_tx, tx_id):
        require(self.anchor is not None, "payout_anchor_unavailable")
        integer(amount,1,MAX_BUDGET,"invalid_refund")
        require(isinstance(signed_tx,bytes) and 1 <= len(signed_tx) <= 65536
                and isinstance(tx_id,str) and 1 <= len(tx_id) <= 100,"invalid_refund")
        with self._transaction():
            row = self.db.execute("SELECT * FROM retirement WHERE id=1").fetchone()
            if row["state"] in {"refund_pending","refunded"}:
                require(row["amount"] == amount and row["tx_id"] == tx_id and row["signed_tx"] is not None
                        and bytes(row["signed_tx"]) == signed_tx,"refund_identity_mismatch")
            else:
                require(row["state"] == "retired","retirement_ineligible")
                self.db.execute("UPDATE retirement SET state='refund_pending',amount=?,signed_tx=?,tx_id=? WHERE id=1",
                                (amount,signed_tx,tx_id))
        return self.retirement_status()

    @_locked
    def refund_identity(self):
        require(self.anchor is not None,"payout_anchor_unavailable")
        with self._read():
            row = self.db.execute("SELECT * FROM retirement WHERE id=1").fetchone()
            require(row["state"] in {"refund_pending","refunded"} and row["signed_tx"] is not None,
                    "retirement_ineligible")
            return bytes(row["signed_tx"]),row["tx_id"],row["amount"]

    @_locked
    def mark_refunded(self, tx_id):
        require(self.anchor is not None,"payout_anchor_unavailable")
        with self._transaction():
            row = self.db.execute("SELECT * FROM retirement WHERE id=1").fetchone()
            require(row["state"] in {"refund_pending","refunded"} and row["tx_id"] == tx_id,
                    "refund_identity_mismatch")
            self.db.execute("UPDATE retirement SET state='refunded' WHERE id=1")
        return self.retirement_status()

    @_locked
    def finish_empty_refund(self):
        require(self.anchor is not None,"payout_anchor_unavailable")
        with self._transaction():
            require(self.db.execute("SELECT state FROM retirement WHERE id=1").fetchone()[0] == "retired",
                    "retirement_ineligible")
            self.db.execute("UPDATE retirement SET state='refunded',amount=0 WHERE id=1")
        return self.retirement_status()


    @_locked
    def paid_payments(self):
        """Public transfer identities for a final canonical-receipt check."""
        with self._read():
            return [{"transactionId":row["tx_id"],"payoutAddress":row["recipient"],"rewardMinor":row["reward"]}
                    for row in self.db.execute("SELECT tx_id,recipient,reward FROM jobs WHERE state='paid'")]
