"""Invented HDFC-shaped records; no bank session, network, inference or payout."""
import base64
import copy
import json
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from transcripts.artifacts import extract_artifact
from transcripts.cli import bank_secret, lint, lookup, preview
from transcripts.common import Rejected, canonical
from transcripts.hdfc_session import (HISTORY_URL, MAX_RESPONSE, ORIGIN, TRANSPORT,
                                      session_parts)
from transcripts.open_source import OpenBankClient, assess, credential_headers, submission_context
from transcripts.policy import validate_campaign
from transcripts.tests.test_open_source import campaign
from transcripts.transport import HTTPResponse

SYNTHETIC_KEY = bytes(range(32))
ACCOUNT = "11223344556677"  # Invented; distinct from synthetic payout wallets.
HEADERS = {"X-Synthetic-Session": "synthetic-private-session", "User-Agent": "synthetic-browser"}
MAPPING = {"paymentId": "$[].id", "amount": "$[].transactionAmountCurrency.amount",
           "timestamp": "$[].bookingDate", "counterparty": "$[].description",
           "currency": "$[].transactionAmountCurrency.currencyCode", "status": "$[].billingStatus"}


def hdfc_campaign():
    return campaign(id="hdfc-open-v1", bankId="in/hdfc", bankName="HDFC Bank", country="IN",
                    sources=[{"origin": "https://hdfc.bank.in", "paths": ["/"], "methods": ["GET", "POST"],
                              "parameterNames": [], "headerNames": []}],
                    openSource={"version": 2, "kind": "open-json-read-v1", "maxReads": 1, "transport": TRANSPORT})


def payload():
    return {"credential": {"origin": ORIGIN, "kind": "hdfc_session", "value": {
        "headers": copy.deepcopy(HEADERS), "aesKey": base64.b64encode(SYNTHETIC_KEY).decode()}},
        "profileId": None, "transcript": [], "notes": "History uses application encryption over TLS.",
        "recipe": {"version": 3, "reads": [{"url": HISTORY_URL, "method": "POST",
                                           "contentType": "application/json", "body": json.dumps({"accountNo": ACCOUNT})}],
                   "identity": {"read": 0, "path": [0, "arrangementId"]}, "history": {"read": 0, "path": []}}}


def records():
    return [{"id": f"synthetic-transaction-{i}", "arrangementId": ACCOUNT,
             "reference": "", "description": f"Synthetic counterparty {i}", "type": "UPI",
             "bookingDate": f"2026-01-0{i}", "valueDate": f"2026-01-0{i}",
             "transactionAmountCurrency": {"amount": "12.50", "currencyCode": "INR"},
             "billingStatus": "BOOKED", "creditDebitIndicator": "DBIT"} for i in range(1, 4)]


def frame(data, key=SYNTHETIC_KEY):
    iv = bytes(range(16))  # Fixed only in synthetic server fixtures.
    return base64.b64encode(iv + AESGCM(key).encrypt(iv, data, None))


class EncryptedBank:
    def __init__(self, rows=None, anonymous=None, response=None):
        self.rows = records() if rows is None else rows
        self.anonymous = anonymous or HTTPResponse(401, b"")
        self.response = response
        self.calls = []

    def check_request(self, url, kwargs):
        self.calls.append((url, copy.deepcopy(kwargs)))
        if url != HISTORY_URL or kwargs["content_type"] != "application/json":
            raise AssertionError("unexpected synthetic read")
        raw = base64.b64decode(kwargs["body"], validate=True)
        body = json.loads(AESGCM(SYNTHETIC_KEY).decrypt(raw[:16], raw[16:], None))
        if body != {"accountNo": ACCOUNT}:
            raise AssertionError("wrong synthetic body")

    def probe_anonymous(self, url, **kwargs):
        self.check_request(url, kwargs)
        if kwargs["headers"] != {"User-Agent": "synthetic-browser", "Accept": "application/json"}:
            raise AssertionError("anonymous probe leaked credential headers")
        return self.anonymous

    def request_bank(self, url, **kwargs):
        self.check_request(url, kwargs)
        if kwargs["headers"].get("X-Synthetic-Session") != HEADERS["X-Synthetic-Session"]:
            raise AssertionError("missing session")
        return self.response or HTTPResponse(200, frame(canonical(self.rows)))


def acquire(bank=None, data=None):
    data = data or payload()
    policy = hdfc_campaign()
    context = submission_context(policy, data)
    client = OpenBankClient(policy, data["credential"], bank or EncryptedBank())
    try:
        reads = client.acquire("synthetic-hdfc-job", data["recipe"], 1791849600)
        return reads, extract_artifact(policy, reads, context)
    finally:
        client.close()


class HDFCSessionTests(unittest.TestCase):
    def test_encrypted_acquisition_redaction_and_mapping(self):
        bank = EncryptedBank()
        reads, artifact = acquire(bank)
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0].body, records())
        encoded = canonical(artifact).decode()
        for private in (ACCOUNT, HEADERS["X-Synthetic-Session"], base64.b64encode(SYNTHETIC_KEY).decode(),
                        "synthetic-transaction-1", "Synthetic counterparty 1", "12.50"):
            self.assertNotIn(private, encoded)
        self.assertEqual(len(bank.calls), 2)
        self.assertNotEqual(bank.calls[0][1]["body"], bank.calls[1][1]["body"])
        self.assertNotIn(ACCOUNT, bank.calls[1][1]["body"])
        self.assertNotIn("aesKey", str(bank.calls))
        result = assess(hdfc_campaign(), reads, submission_context(hdfc_campaign(), payload()), artifact,
                        {"mapping": MAPPING, "completedStatus": []})
        self.assertTrue(result["useful"])
        self.assertEqual(result["score"], 100)

    def test_campaign_opt_in_cannot_be_reused_for_other_banks(self):
        validate_campaign(hdfc_campaign())
        for field, value in (("bankId", "us/example"), ("country", "US")):
            policy = hdfc_campaign(); policy[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, "invalid_policy"):
                validate_campaign(policy)
        for change in ({"version": 1}, {"transport": "arbitrary-codec"}, {"maxReads": 2}, {"version": True}):
            policy = hdfc_campaign(); policy["openSource"].update(change)
            with self.subTest(change=change), self.assertRaises(Rejected):
                validate_campaign(policy)
        policy = hdfc_campaign(); policy["sources"][0]["origin"] = "https://example.com"
        with self.assertRaisesRegex(Rejected, "invalid_policy"):
            validate_campaign(policy)
        policy = hdfc_campaign(); policy["sources"][0]["methods"] = ["GET"]
        with self.assertRaisesRegex(Rejected, "invalid_policy"):
            validate_campaign(policy)

    def test_key_is_not_accepted_by_ordinary_campaign_or_sent_as_header(self):
        data = payload()
        self.assertEqual(credential_headers(data["credential"], ORIGIN), HEADERS)
        policy = hdfc_campaign(); policy["openSource"] = {"version": 1, "kind": "open-json-read-v1", "maxReads": 1}
        with self.assertRaisesRegex(Rejected, "invalid_credential"):
            OpenBankClient(policy, data["credential"], EncryptedBank())
        for kind in ("headers", "bearer", None, [], {}):
            data = payload(); data["credential"]["kind"] = kind
            with self.subTest(kind=kind), self.assertRaisesRegex(Rejected, "invalid_credential"):
                submission_context(hdfc_campaign(), data)
        for credential in (None, [], "not-a-credential"):
            data = payload(); data["credential"] = credential
            with self.subTest(credential=credential), self.assertRaisesRegex(Rejected, "invalid_credential"):
                submission_context(hdfc_campaign(), data)

    def test_key_validation_and_header_guard(self):
        for invalid in (None, {}, {"headers": {}}, {"headers": {}, "aesKey": 1},
                        {"headers": {}, "aesKey": "x" * 44},
                        {"headers": {}, "aesKey": base64.b64encode(bytes(24)).decode()},
                        {"headers": {}, "aesKey": "!" * 44},
                        {"headers": [], "aesKey": base64.b64encode(SYNTHETIC_KEY).decode()}):
            with self.subTest(valueType=type(invalid).__name__), self.assertRaisesRegex(Rejected, "bank_encryption_credential"):
                session_parts(invalid)
        for name in ("Host", "X-HTTP-Method-Override", "Content-Type", "Accept-Encoding"):
            data = payload(); data["credential"]["value"]["headers"][name] = "synthetic"
            with self.subTest(name=name), self.assertRaisesRegex(Rejected, "credential_headers_invalid"):
                submission_context(hdfc_campaign(), data)

    def test_session_key_cannot_be_copied_into_notes(self):
        # A base64 AES-128 key can be shorter than the generic long-token rule.
        for length in (16, 32):
            data = payload()
            key = base64.b64encode(bytes(range(65, 65 + length))).decode()
            data["credential"]["value"]["aesKey"] = key
            data["notes"] = "Session material " + key
            with self.subTest(length=length), self.assertRaisesRegex(Rejected, "unsafe_notes"):
                submission_context(hdfc_campaign(), data)

    def test_exact_read_only_route_body_and_selectors(self):
        mutations = [lambda r: r["reads"][0].update(url=ORIGIN + "/api/payments/send"),
                     lambda r: r["reads"][0].update(url=HISTORY_URL + "?operation=send"),
                     lambda r: r["reads"][0].update(url=HISTORY_URL.replace("api-now.", "other.")),
                     lambda r: r["reads"][0].update(body=json.dumps({"accountNo": ACCOUNT, "operation": "send"})),
                     lambda r: r["reads"][0].update(body=json.dumps({"accountNo": "not-an-account"})),
                     lambda r: r["reads"][0].update(body="opaque-ciphertext"),
                     lambda r: r["reads"][0].update(body=json.dumps({"accountNo": 1})),
                     lambda r: r["reads"][0].update(contentType="application/x-www-form-urlencoded"),
                     lambda r: r["reads"].append(copy.deepcopy(r["reads"][0])),
                     lambda r: r.update(identity={"read": 0, "path": [0, "id"]}),
                     lambda r: r.update(history={"read": 0, "path": [0]})]
        for index, mutation in enumerate(mutations):
            data = payload(); mutation(data["recipe"])
            with self.subTest(index=index), self.assertRaises(Rejected):
                submission_context(hdfc_campaign(), data)

    def test_all_records_must_match_requested_account(self):
        for replacement in ("00000000000002", None, 1):
            rows = records(); rows[1]["arrangementId"] = replacement
            with self.subTest(replacement=replacement), self.assertRaisesRegex(Rejected, "bank_account_mismatch"):
                acquire(EncryptedBank(rows=rows))
        for rows in ({"records": records()}, [None], ["not-a-record"]):
            with self.assertRaisesRegex(Rejected, "bank_account_mismatch"):
                acquire(EncryptedBank(rows=rows))

    def test_anonymous_plain_or_encrypted_history_is_rejected(self):
        for body in (canonical(records()), frame(canonical(records()))):
            bank = EncryptedBank(anonymous=HTTPResponse(200, body))
            with self.assertRaisesRegex(Rejected, "anonymous_access_allowed"):
                acquire(bank)
            self.assertEqual(len(bank.calls), 1)
        with self.assertRaisesRegex(Rejected, "bank_encryption_invalid"):
            acquire(EncryptedBank(anonymous=HTTPResponse(200, b"unreadable-success")))

    def test_authenticated_plaintext_tampering_wrong_key_and_invalid_json_fail_closed(self):
        good = frame(canonical(records()))
        raw = bytearray(base64.b64decode(good)); raw[-1] ^= 1
        cases = [canonical(records()), b"!", b"", base64.b64encode(bytes(16)), good + b"\n",
                 base64.b64encode(raw), frame(canonical(records()), bytes(32)), frame(b"not-json"),
                 frame(b'{"duplicate":1,"duplicate":2}')]
        for body in cases:
            with self.subTest(length=len(body)), self.assertRaisesRegex(Rejected, "bank_encryption_invalid"):
                acquire(EncryptedBank(response=HTTPResponse(200, body)))

    def test_tls_status_size_history_limits_and_close(self):
        for response, code in ((HTTPResponse(200, frame(canonical(records())), tls_verified=False), "unauthenticated_source"),
                               (HTTPResponse(201, frame(canonical(records()))), "bank_http_unexpected_status"),
                               (HTTPResponse(200, b"A" * (MAX_RESPONSE + 1)), "response_size"),
                               (HTTPResponse(200, "not-bytes"), "response_size")):
            with self.subTest(code=code), self.assertRaisesRegex(Rejected, code):
                acquire(EncryptedBank(response=response))
        with self.assertRaisesRegex(Rejected, "insufficient_history"):
            acquire(EncryptedBank(rows=records()[:2]))
        with self.assertRaisesRegex(Rejected, "history_path_invalid"):
            acquire(EncryptedBank(rows=records() * 668))
        client = OpenBankClient(hdfc_campaign(), payload()["credential"], EncryptedBank())
        client.close()
        self.assertEqual(client.headers, {})
        self.assertIsNone(client.encrypted_transport._cipher)
        with self.assertRaisesRegex(Rejected, "invalid_credential"):
            client.acquire("synthetic-hdfc-job", payload()["recipe"], 1791849600)

    def test_cli_check_env_preview_and_lookup(self):
        policy = {"campaigns": [hdfc_campaign()]}
        data = payload(); secret = data["credential"].pop("value")
        self.assertTrue(lint(policy, "hdfc-open-v1", data)["ok"])
        bank_secret(data, json.dumps(secret))
        with patch("transcripts.transport.HTTPTransport", return_value=EncryptedBank()):
            result = preview(policy, "hdfc-open-v1", data, MAPPING)
        self.assertTrue(result["assessment"]["useful"])
        with self.assertRaisesRegex(Rejected, "encrypted_lookup_unavailable"):
            lookup(policy, "hdfc-open-v1", data, 0, [0, "arrangementId"])

    def test_runtime_model_archive_duplicates_and_fixed_failure(self):
        # Reuse the synthetic runtime harness, but exercise the real HDFC bank
        # dispatch, provider prompt, assessment, archive validation and ledger.
        from transcripts.artifacts import validate_archive_record
        from transcripts.runtime import Runtime
        from transcripts.tests.test_open_source import Bank, RuntimeTests
        from transcripts.tests.test_runtime import FakeCoordinator, SigningChannel

        class EncryptedService(EncryptedBank):
            request_provider = Bank.request_provider
            model = {"rubricVersion": "transcript-mapping-v1", "mapping": MAPPING, "completedStatus": []}
            provider_failures = ()

        harness = RuntimeTests()
        harness.setUp()
        self.addCleanup(harness.tearDown)
        harness.policy["campaigns"][:] = [hdfc_campaign()]
        bank = EncryptedService()
        with patch("transcripts.runtime.Channel", return_value=SigningChannel()):
            harness.runtime = Runtime(harness.policy, harness.epoch, bank, harness.archive,
                                      attester=lambda *args: b"synthetic-quote")
        harness.runtime.coordinator = FakeCoordinator(harness.epoch.ledger, harness.events)

        def body():
            return {**payload(), "inferenceKey": "synthetic-inference-key"}

        _, status = harness.run_job(body=body())
        self.assertEqual(status["state"], "paid")  # Synthetic coordinator only.
        public_outputs = [call[3].decode() for call in bank.calls if call[0] == "provider"]
        self.assertEqual(len(public_outputs), 1)
        for archived in harness.archive.records:
            validate_archive_record(hdfc_campaign(), archived["payload"], policy=harness.policy)
            public_outputs.append(canonical(archived).decode())
        for output in public_outputs:
            for private in (ACCOUNT, HEADERS["X-Synthetic-Session"], base64.b64encode(SYNTHETIC_KEY).decode(),
                            "synthetic-transaction-1", "Synthetic counterparty 1", "12.50", "synthetic-inference-key"):
                self.assertNotIn(private, output)
        _, status = harness.run_job(wallet=2, body=body())
        self.assertEqual((status["state"], status["reason"]), ("rejected", "duplicate_account"))
        bank.response = HTTPResponse(200, b"invalid-encrypted-response")
        _, status = harness.run_job(wallet=3, body=body())
        self.assertEqual((status["state"], status["reason"]), ("rejected", "bank_encryption_invalid"))
