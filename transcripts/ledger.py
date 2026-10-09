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
from .artifacts import account_fingerprint, account_fingerprints, extract_artifact
from .recipe import validate_live_reads

NONPAYMENT = {"rejected", "expired", "cancelled"}
RESERVED = {"reserved", "submitted", "verifying", "accepted", "payout_pending", "paid"}
REASONS = {"insufficient_evidence", "insufficient_history", "duplicate_account", "duplicate_recipient",
           "bank_read_failed", "unauthenticated_source", "source_not_allowed", "model_rejected",
           "model_result_invalid", "unsafe_artifact", "job_expired", "cancelled", "provider_failed",
           "invalid_submission", "consent_required", "account_evidence_missing", "ambiguous_account",
           "policy_mismatch", "stale_evidence", "limits_exceeded", "storage_unavailable"}
REASONS.add("interrupted_execution")
from .acquisition import SOURCE_FAILURES
REASONS.update(SOURCE_FAILURES)


def _locked(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return invoke


class Ledger:
    def __init__(self, path, integrity_key, *, global_budget_minor=MAX_BUDGET, anchor=None,
                 initial_snapshot=None, initial_runtime=None):
        require(isinstance(integrity_key, bytes) and len(integrity_key) >= 32, "state_key_unavailable")
        integer(global_budget_minor, 1, MAX_BUDGET, "invalid_budget")
        self.key, self.anchor = integrity_key, anchor
        self._pending_snapshot=None
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
          artifact TEXT, artifact_digest TEXT, tx_id TEXT UNIQUE, signed_tx BLOB, paid_at INTEGER,
          evidence TEXT, receipt_job TEXT, receipt_signature TEXT, payout_intent TEXT, account_aliases TEXT);
        CREATE TABLE IF NOT EXISTS retirement (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL,
          amount INTEGER, tx_id TEXT, signed_tx BLOB);
        CREATE TABLE IF NOT EXISTS runtime (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS accepted_account ON jobs(campaign_id,account_hmac)
          WHERE state IN ('accepted','payout_pending','paid');
        CREATE UNIQUE INDEX IF NOT EXISTS accepted_recipient ON jobs(campaign_id,recipient)
          WHERE state IN ('accepted','payout_pending','paid');
        """)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if initial_snapshot is not None:self._restore(initial_snapshot)
            meta = self.db.execute("SELECT * FROM meta WHERE id=1").fetchone()
            if meta is None:
                require(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0, "state_integrity")
                # An existing external anchor makes a newly empty database a replay.
                require(anchor is None or anchor.read() is None, "state_rollback")
                self.db.execute("INSERT INTO meta VALUES (1,0,?, '')", (global_budget_minor,))
                self.db.execute("INSERT INTO retirement VALUES (1,'open',NULL,NULL,NULL)")
                self.db.execute("INSERT INTO runtime VALUES (1,?)",(canonical(initial_runtime or {}).decode(),))
                self.db.execute("UPDATE meta SET mac=? WHERE id=1", (self._mac(),))
                if anchor is not None:
                    if getattr(anchor,'durable',False):
                        anchor.commit_snapshot(None,self._anchor_value(),{**self._snapshot(),'mac':self._anchor_value()[1]})
                    else:anchor.advance(None, self._anchor_value())
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
        runtime=self.db.execute("SELECT value FROM runtime WHERE id=1").fetchone()
        require(runtime is not None,'state_integrity')
        return {"revision": meta["revision"], "budget": meta["budget"], "jobs": rows, "retirement": retirement,
                "runtime":json.loads(runtime['value'])}

    def _restore(self,snapshot):
        fields(snapshot,{'revision','budget','jobs','retirement','runtime','mac'})
        integer(snapshot['revision'],0,2**63-1,'state_integrity')
        self.db.execute('INSERT INTO meta VALUES (1,?,?,?)',(snapshot['revision'],snapshot['budget'],snapshot['mac']))
        self.db.execute('INSERT INTO runtime VALUES (1,?)',(canonical(snapshot['runtime']).decode(),))
        columns=[row[1] for row in self.db.execute('PRAGMA table_info(jobs)')]
        require(isinstance(snapshot['jobs'],list) and len(snapshot['jobs'])<=64,'state_integrity')
        for original in snapshot['jobs']:
            fields(original,set(columns));row=dict(original)
            if row['signed_tx'] is not None:row['signed_tx']=bytes.fromhex(row['signed_tx'])
            self.db.execute('INSERT INTO jobs ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                            tuple(row[column] for column in columns))
        row=dict(snapshot['retirement']);fields(row,{'id','state','amount','tx_id','signed_tx'})
        if row['signed_tx'] is not None:row['signed_tx']=bytes.fromhex(row['signed_tx'])
        self.db.execute('INSERT INTO retirement VALUES (?,?,?,?,?)',tuple(row[k] for k in ('id','state','amount','tx_id','signed_tx')))

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
    def _transaction(self,*,takeover=False):
        if self._pending_snapshot is not None:self._resolve_pending()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._verify()
            old_anchor = self._anchor_value()
            yield
            self.db.execute("UPDATE meta SET revision=revision+1 WHERE id=1")
            self.db.execute("UPDATE meta SET mac=? WHERE id=1", (self._mac(),))
            new_anchor = self._anchor_value()
            if getattr(self.anchor,'durable',False):
                # The only authoritative commit atomically contains the entire
                # encrypted snapshot and revision. SQLite is an enclave RAM cache.
                prepared={**self._snapshot(),'mac':new_anchor[1]}
                try:self.anchor.commit_snapshot(old_anchor,new_anchor,prepared,takeover=takeover)
                except BaseException:
                    if self.anchor.pending is not None:self._pending_snapshot=(old_anchor,new_anchor,prepared,takeover)
                    raise
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        if self.anchor is not None and not getattr(self.anchor,'durable',False):
            # Crash after commit leaves anchor mismatch. Availability is sacrificed
            # for explicit reconciliation; no live payment can proceed on a replay.
            self.anchor.advance(old_anchor, new_anchor)

    def _resolve_pending(self):
        # A completed grade/accepted obligation is retained as the exact staged
        # snapshot across an authority outage. Never reject, rebill, or perform
        # another mutation until its original CAS outcome is authenticated.
        old,new,snapshot,takeover=self._pending_snapshot
        self.anchor.commit_snapshot(old,new,snapshot,takeover=takeover)
        require(not self.db.in_transaction,'state_commit_uncertain')
        owned=True
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for table in ('jobs','meta','retirement','runtime'):self.db.execute('DELETE FROM '+table)
            self._restore(snapshot)
            if owned:self.db.execute('COMMIT')
            self._pending_snapshot=None
        except BaseException:
            if owned and self.db.in_transaction:self.db.execute('ROLLBACK')
            raise

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
            if getattr(self.anchor,'durable',False):
                # Job IDs are random and never reused; ingress/challenge keys are
                # fresh after restart. Removing expired nonpayment rows cannot
                # make an old ciphertext valid or revive its financial budget.
                self.db.execute("DELETE FROM jobs WHERE expires_at<=? AND state IN ('rejected','expired','cancelled')",(now,))
                require(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0]<64,'state_capacity')
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
        if self._pending_snapshot is not None:self._resolve_pending()
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
        if self._pending_snapshot is not None:self._resolve_pending()
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
    def accept(self, job_id, reads, model_result, *, dedup_key, now, evidence=None, policy=None):
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
            aliases=account_fingerprints(dedup_key,campaign,reads,account_id)
            self._check_aliases(campaign['id'],aliases)
            require(self.db.execute("SELECT 1 FROM jobs WHERE campaign_id=? AND account_hmac=? AND state IN "
                                    "('accepted','payout_pending','paid')", (campaign["id"],fingerprint)).fetchone() is None,
                    "duplicate_account")
            self.db.execute("UPDATE jobs SET state='accepted',account_hmac=?,artifact=?,artifact_digest=?,account_aliases=? WHERE id=?",
                            (fingerprint,canonical(artifact).decode(),digest(artifact),canonical(aliases).decode(),job_id))
            if getattr(self.anchor,'durable',False):
                require(evidence is not None,'state_evidence_missing')
                fields(evidence,{'epoch','modelResult','inference','policyDigest'})
                require(evidence['modelResult']==model_result,'model_result_invalid')
                record={'version':1,**evidence,'artifact':artifact,'job':self._status_row(self._job(job_id))}
                from .artifacts import validate_archive_record
                validate_archive_record(campaign,record,policy=policy)
                from .aws_state import MAX_RECORD
                require(len(canonical(record))<=MAX_RECORD,'state_capacity')
                self.db.execute('UPDATE jobs SET evidence=? WHERE id=?',(canonical(evidence).decode(),job_id))
        return self.status(job_id)

    def _status_row(self,row):
        return {'jobId':row['id'],'campaignId':row['campaign_id'],'state':row['state'],'bindingDigest':row['binding'],
                'expiresAt':row['expires_at'],'rewardMinor':row['reward'],'payoutAddress':row['recipient'],'reason':row['reason'],
                'artifactDigest':row['artifact_digest'],'transactionId':row['tx_id']}

    @_locked
    def check_account(self,job_id,reads,*,dedup_key,now):
        with self._read():
            row=self._job(job_id);require(row['state']=='verifying','invalid_transition')
            campaign,request=json.loads(row['campaign']),json.loads(row['request'])
            account=validate_live_reads(campaign,reads,job_id,row['submitted_at'],now,request['limits']['maxBankReads'])
            fingerprint=account_fingerprint(dedup_key,campaign['id'],account)
            self._check_aliases(campaign['id'],account_fingerprints(dedup_key,campaign,reads,account))
            require(self.db.execute("SELECT 1 FROM jobs WHERE campaign_id=? AND account_hmac=? AND state IN ('accepted','payout_pending','paid')",
                                    (campaign['id'],fingerprint)).fetchone() is None,'duplicate_account')

    def _check_aliases(self,campaign_id,aliases):
        fingerprints=set(aliases)
        for row in self.db.execute("SELECT account_hmac,account_aliases FROM jobs WHERE campaign_id=? AND state IN ('accepted','payout_pending','paid')",(campaign_id,)):
            old=json.loads(row['account_aliases']) if row['account_aliases'] is not None else [row['account_hmac']]
            require(not fingerprints.intersection(old),'duplicate_account')

    @_locked
    def runtime_state(self):
        with self._read():return json.loads(self.db.execute('SELECT value FROM runtime WHERE id=1').fetchone()[0])

    @_locked
    def update_runtime(self,updates):
        with self._transaction():
            value=json.loads(self.db.execute('SELECT value FROM runtime WHERE id=1').fetchone()[0]);value.update(updates)
            self.db.execute('UPDATE runtime SET value=? WHERE id=1',(canonical(value).decode(),))

    @_locked
    def recover_restart(self,now,boot_id):
        with self._transaction(takeover=True):
            self.db.execute("UPDATE jobs SET state='rejected',reason='interrupted_execution' WHERE state IN ('submitted','verifying')")
            self.db.execute("UPDATE jobs SET state='expired',reason='job_expired' WHERE state='reserved' AND expires_at<=?",(now,))
            value=json.loads(self.db.execute('SELECT value FROM runtime WHERE id=1').fetchone()[0])
            value.update(active=False,bootId=boot_id)
            value['operatorNonces']={nonce:expiry for nonce,expiry in value.get('operatorNonces',{}).items() if expiry>now}
            self.db.execute('UPDATE runtime SET value=? WHERE id=1',(canonical(value).decode(),))

    @_locked
    def archive_record(self,job_id):
        with self._read():
            row=self._job(job_id);require(row['evidence'] is not None,'state_evidence_missing')
            return {'version':1,**json.loads(row['evidence']),'artifact':json.loads(row['artifact']),'job':self._status_row(row)}

    @_locked
    def recovery_jobs(self):
        with self._read():
            return [row['id'] for row in self.db.execute("SELECT id FROM jobs WHERE state IN ('accepted','payout_pending','paid') ORDER BY created_at,id")]

    @_locked
    def save_receipt(self,job_id,signed):
        with self._transaction():
            require(signed['payload']['job']==self._status_row(self._job(job_id)),'receipt_mismatch')
            self.db.execute('UPDATE jobs SET receipt_job=?,receipt_signature=? WHERE id=?',
                (canonical(signed['payload']['job']).decode(),signed['signature'],job_id))

    @_locked
    def restored_receipt(self,job_id):
        with self._read():
            row=self._job(job_id)
            if row['receipt_signature'] is None:return None
            return {'payload':{'version':1,**json.loads(row['evidence']),'artifact':json.loads(row['artifact']),
                               'job':json.loads(row['receipt_job'])},'signature':row['receipt_signature']}

    @_locked
    def payout_intent(self,job_id):
        with self._read():
            row=self._job(job_id);return json.loads(row['payout_intent']) if row['payout_intent'] else None

    @_locked
    def prepare_intent(self,job_id,intent):
        with self._transaction():
            row=self._job(job_id);require(row['state']=='accepted','payout_ineligible')
            if row['payout_intent'] is not None:require(json.loads(row['payout_intent'])==intent,'payout_identity_mismatch')
            else:
                state=json.loads(self.db.execute('SELECT value FROM runtime WHERE id=1').fetchone()[0])
                initial=self.anchor.config['initialWalletNonce']
                require(intent['nonce']==state.get('nonceWitness',initial),'payout_nonce_conflict')
                state['nonceWitness']=intent['nonce']+1
                self.db.execute('UPDATE runtime SET value=? WHERE id=1',(canonical(state).decode(),))
                self.db.execute('UPDATE jobs SET payout_intent=? WHERE id=?',(canonical(intent).decode(),job_id))

    @_locked
    def payment_rows(self):
        with self._read():return self._snapshot()['jobs']

    @_locked
    def assert_signed_payment(self,signed,tx_id):
        with self._read():
            row=self.db.execute("SELECT signed_tx FROM jobs WHERE tx_id=? AND state IN ('payout_pending','paid')",(tx_id,)).fetchone()
            require(row is not None and bytes(row[0])==signed,'payout_identity_mismatch')

    @_locked
    def consume_operator_nonce(self,nonce,expiry,now):
        with self._transaction():
            value=json.loads(self.db.execute('SELECT value FROM runtime WHERE id=1').fetchone()[0])
            used={key:end for key,end in value.get('operatorNonces',{}).items() if end>now}
            require(nonce not in used and len(used)<32,'operator_replayed')
            used[nonce]=expiry;value['operatorNonces']=used
            self.db.execute('UPDATE runtime SET value=? WHERE id=1',(canonical(value).decode(),))

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
                if getattr(self.anchor,'durable',False):
                    require(row['payout_intent'] is not None,'payout_intent_missing')
                    self._verify_signed_intent(signed_tx,tx_id,json.loads(row['payout_intent']))
                    from .eth_payout import transfer_data
                    require(bytes.fromhex(json.loads(row['payout_intent'])['data'][2:])==transfer_data(row['recipient'],row['reward']),
                            'payout_identity_mismatch')
                self.db.execute("UPDATE jobs SET state='payout_pending',signed_tx=?,tx_id=? WHERE id=?",
                                (signed_tx,tx_id,job_id))
        return self.status(job_id)

    def _verify_signed_intent(self,signed,tx_id,intent):
        import rlp
        from eth_account import Account
        from eth_utils import keccak
        from .kms_signer import _unsigned_fields
        require(isinstance(signed,bytes) and 1<len(signed)<=1024 and signed[0]==2,'invalid_transaction')
        transaction={**intent,'data':bytes.fromhex(intent['data'][2:])}
        decoded=rlp.decode(signed[1:],strict=True)
        require(len(decoded)==12 and rlp.encode(decoded[:9])==rlp.encode(_unsigned_fields(transaction))
                and tx_id=='0x'+keccak(signed).hex()
                and Account.recover_transaction(signed).lower()==self.anchor.binding['wallet'],'payout_identity_mismatch')

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
                if getattr(self.anchor,'durable',False):
                    intent=json.loads(self.db.execute('SELECT value FROM runtime WHERE id=1').fetchone()[0]).get('refundIntent')
                    require(intent is not None,'payout_intent_missing')
                    self._verify_signed_intent(signed_tx,tx_id,intent)
                    from .eth_payout import refund_data
                    require(bytes.fromhex(intent['data'][2:])==refund_data(amount),'refund_identity_mismatch')
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
