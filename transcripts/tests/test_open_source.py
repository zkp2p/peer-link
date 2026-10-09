"""Open-recipe campaigns: synthetic bank, synthetic model, no network or keys."""
import copy
import hashlib
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from transcripts.artifacts import extract_artifact, validate_archive_record, validate_artifact
from transcripts.client import campaign_limits
from transcripts.common import Rejected, canonical, digest
from transcripts.ledger import Ledger
from transcripts.open_source import (OpenBankClient, ROLE_WEIGHTS, assess, check_assessment, credential_headers,
                                     parse_proposal, submission_context, validate_model_result, validate_notes,
                                     validate_open_recipe, value_format)
from transcripts.policy import validate_campaign, validate_reservation
from transcripts.providers import OPEN_PREFIX, OPEN_SUFFIX, SYSTEM_PROMPT, ProviderClient, open_prompt_digest
from transcripts.runtime import Runtime
from transcripts.server import egress_permitted
from transcripts.transport import BankClient, HTTPResponse
from transcripts.tests.test_core import KEY, NOW
from transcripts.tests.test_runtime import (FakeArchive, FakeCoordinator, FakeEpoch, PUBLIC_OPERATOR, SigningChannel)
from transcripts.tests.test_kms_signer import KEY_ID

ORIGIN = "https://bank.example"
BASE = "https://inference.example/v1"
SESSION = "SYNTHETIC-SESSION-COOKIE"
CSRF = "SYNTHETIC-CSRF"
COOKIE = "Cookie"  # Header names are variables so the repository privacy scan sees no literal pair.
INFERENCE = "SYNTHETIC-INFERENCE-KEY"
PRIVATE = ("Alice Example", "alice@example.com", "user-48213377", "4821337700", "Dinner with Bob", "acct-9912-7731",
           "txn-00017", "bob_handle", "Springfield", SESSION, INFERENCE)


def campaign(**changes):
    value = {"version": 1, "id": "synthetic-open-v1", "bankId": "xx/synthetic", "bankName": "Synthetic Bank",
             "country": "XX", "issueUrl": "https://github.com/example/example/issues/1", "status": "active",
             "rewardMinor": 5_000_000, "maxContributors": 2,
             "sources": [{"origin": ORIGIN, "paths": ["/"], "methods": ["GET", "POST"], "parameterNames": [],
                          "headerNames": []}],
             "inferenceRoutes": [{"provider": name, "models": ["*"], "privacyModes": ["provider_visible"]}
                                 for name in ("openai", "near", "openai_compatible")],
             "rubricVersion": "transcript-mapping-v1", "safeSchemaFields": [],
             "evidenceRequirements": {"historyPath": [], "minRecords": 3,
                                      "requiredFields": ["paymentId", "amount", "timestamp", "counterparty"],
                                      "minScore": 85},
             "openSource": {"version": 1, "kind": "open-json-read-v1", "maxReads": 4}}
    value.update(changes)
    return value


def reservation(policy, wallet=1, provider="openai_compatible", model="any/model-1", **changes):
    value = {"version": 1, "campaignId": policy["id"], "payoutAddress": "0x" + f"{wallet:040x}", "provider": provider,
             "model": model, "privacyMode": "provider_visible", "consent": True, "policyDigest": digest(policy),
             "expiresAt": NOW + 600, "limits": {**campaign_limits(policy), "maxInputTokens": 60000}}
    if provider == "openai_compatible":
        value["inferenceBaseUrl"] = BASE
    value.update(changes)
    return value


ME = {"user": {"id": "user-48213377", "email": "alice@example.com", "displayName": "Alice Example",
               "address": {"city": "Springfield", "state": "Illinois"}, "kind": "personal"}}
HISTORY = {"activity": {"items": [
    {"id": "txn-00017", "amount": "-12.50", "currency": "USD", "createdAt": "2026-09-30T10:11:12Z",
     "status": "completed", "counterparty": {"handle": "bob_handle", "name": "Bob Example"}, "memo": "Dinner with Bob"},
    {"id": "txn-00018", "amount": "-40.00", "currency": "USD", "createdAt": "2026-10-01T08:00:00Z",
     "status": "pending", "counterparty": {"handle": "carol77", "name": "Carol Example"}, "memo": ""},
    {"id": "txn-00019", "amount": "7.25", "currency": "USD", "createdAt": "2026-10-02T09:30:00Z",
     "status": "completed", "counterparty": {"handle": "dave.x", "name": "Dave Example"}, "memo": "Refund"},
], "byAccount": {"acct-9912-7731": {"balance": 10.5}, "acct-9912-7732": {"balance": 2.0},
                 "acct-9912-7733": {"balance": 3.0}, "acct-9912-7734": {"balance": 4.0},
                 "acct-9912-7735": {"balance": 5.0}}}}
MAPPING = {"paymentId": "$.activity.items[].id", "amount": "$.activity.items[].amount",
           "timestamp": "$.activity.items[].createdAt", "counterparty": "$.activity.items[].counterparty.handle",
           "currency": "$.activity.items[].currency", "status": "$.activity.items[].status"}


def recipe():
    return {"version": 3, "reads": [{"url": ORIGIN + "/api/v2/me"},
                                    {"url": ORIGIN + "/api/v2/users/user-48213377/activity?limit=20&cursor=4821337700"}],
            "identity": {"read": 0, "path": ["user", "id"]}, "history": {"read": 1, "path": ["activity", "items"]}}


def payload(**changes):
    value = {"credential": {"origin": ORIGIN, "kind": "headers",
                            "value": {COOKIE: SESSION, "X-CSRF-Token": CSRF, "X-Client-Version": "web",
                                      "User-Agent": "Mozilla/5.0"}},
             "profileId": None, "recipe": recipe(), "inferenceKey": INFERENCE, "transcript": [],
             "notes": "Activity list is newest first. The handle under counterparty is what a payer types to send."}
    value.update(changes)
    return value


class Bank:
    """Transport double: authenticated JSON, a configurable anonymous answer, one model reply."""
    def __init__(self, *, anonymous=(401, None), model=None, bodies=None, provider_failures=()):
        self.anonymous, self.model, self.calls = anonymous, model, []
        self.bodies = bodies or {"/api/v2/me": ME, "/api/v2/users/user-48213377/activity": HISTORY}
        self.provider_failures = list(provider_failures)
    def probe_anonymous(self, url, *, headers=None, timeout=15, body=None, content_type=None):
        self.calls.append(("probe", url, dict(headers or {}), body))
        status, served = self.anonymous
        if served is None or not 200 <= status < 300:
            return HTTPResponse(status, b"", ())
        path = url[len(urlsplit(url).scheme) + 3 + len(urlsplit(url).netloc):].split("?")[0]
        answer = self.bodies[path] if served == "same" else served
        return HTTPResponse(status, canonical(answer), (("content-type", "json"),))
    def request_bank(self, url, *, headers, timeout=15, max_bytes=0, open_headers=False, body=None, content_type=None):
        self.calls.append(("bank", url, dict(headers), body, content_type))
        path = url[len(urlsplit(url).scheme) + 3 + len(urlsplit(url).netloc):].split("?")[0]
        if path not in self.bodies:
            raise Rejected("bank_http_client_error")
        return HTTPResponse(200, canonical(self.bodies[path]), (("content-type", "application/json"),))
    def request_provider(self, url, *, headers, body, timeout=15, max_bytes=0):
        self.calls.append(("provider", url, dict(headers), body))
        if self.provider_failures:
            raise Rejected(self.provider_failures.pop(0))
        reply = self.model if self.model is not None else {"rubricVersion": "transcript-mapping-v1",
                                                         "mapping": MAPPING, "completedStatus": ["completed"]}
        if isinstance(reply, dict) and "choices" in reply:
            return HTTPResponse(200, canonical(reply), ())
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return HTTPResponse(200, canonical({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": content}}], "usage": {"prompt_tokens": 900, "completion_tokens": 80}}), ())


def acquired(policy=None, bank=None, body=None):
    policy = policy or campaign()
    body = body or payload()
    context = submission_context(policy, body)
    client = BankClient(policy, body["credential"], transport=bank or Bank(), profile_id=None, max_reads=4)
    reads = client.acquire("0" * 32, body["recipe"], NOW + 2)
    return policy, context, reads, extract_artifact(policy, reads, context)


class PolicyTests(unittest.TestCase):
    def test_open_campaign_and_wildcard_routes_validate(self):
        policy = campaign()
        validate_campaign(policy)
        validate_reservation(policy, reservation(policy), NOW)
        validate_reservation(policy, reservation(policy, provider="openai", model="gpt-anything"), NOW)
    def test_open_campaign_cannot_pin_paths_or_mix_descriptors(self):
        for change in ({"sources": [{"origin": ORIGIN, "paths": ["/api"], "methods": ["GET"], "parameterNames": [],
                                     "headerNames": []}]},
                       {"sources": [{"origin": ORIGIN, "paths": ["/"], "methods": ["POST"], "parameterNames": [],
                                     "headerNames": []}]},
                       {"safeSchemaFields": ["id"]}, {"rubricVersion": "rubric-v1"},
                       {"openSource": {"version": 1, "kind": "open-json-read-v1", "maxReads": 99}},
                       {"sourceDescriptor": {}}):
            with self.assertRaises(Rejected):
                validate_campaign(campaign(**change))
        bad = campaign()
        bad["evidenceRequirements"]["requiredFields"] = ["paymentId", "wallet"]
        with self.assertRaises(Rejected):
            validate_campaign(bad)
    def test_custom_endpoint_is_required_bounded_and_bound_to_the_reservation(self):
        policy = campaign()
        missing = reservation(policy)
        del missing["inferenceBaseUrl"]
        with self.assertRaises(Rejected):
            validate_reservation(policy, missing, NOW)
        for url in ("http://inference.example/v1", "https://user:pw@inference.example/v1", "https://inference.example:8443/v1",
                    "https://inference.example/v1?key=1", "https://inference.example/v1/", "https://inference.example/../x"):
            with self.assertRaisesRegex(Rejected, "invalid_provider"):
                validate_reservation(policy, reservation(policy, inferenceBaseUrl=url), NOW)
        named = reservation(policy, provider="openai", model="gpt-anything", inferenceBaseUrl=BASE)
        with self.assertRaises(Rejected):
            validate_reservation(policy, named, NOW)
        for url in ("https://169.254.169.254/latest", "https://localhost/v1", "https://kms.us-east-1.amazonaws.com/v1",
                    "https://mainnet.base.org/v1", "https://gateway.example/v1/0123456789abcdef0123456789abcdef",
                    "https://inference.example/acct/48213377001"):
            with self.assertRaisesRegex(Rejected, "invalid_provider"):
                validate_reservation(policy, reservation(policy, inferenceBaseUrl=url), NOW)
        for model in ("alice@example.com", "tel:+14155550101"):
            with self.assertRaisesRegex(Rejected, "provider_not_allowed"):
                validate_reservation(policy, reservation(policy, model=model), NOW)
        validate_reservation(policy, reservation(policy, model="claude-3-5-sonnet-20241022"), NOW)
        with self.assertRaisesRegex(Rejected, "provider_not_allowed"):
            validate_reservation(policy, reservation(policy, model="*"), NOW)
        with self.assertRaisesRegex(Rejected, "provider_not_allowed"):
            validate_reservation(policy, reservation(policy, model="bad model name"), NOW)


class RecipeTests(unittest.TestCase):
    def test_recipe_is_pinned_to_one_campaign_origin(self):
        policy = campaign()
        validate_open_recipe(policy, recipe(), 4)
        for url in ("https://evil.example/api", "https://bank.example:8443/api", "http://bank.example/api",
                    ORIGIN + "/a/../b", ORIGIN + "/a%2Fb", ORIGIN + "/a?x=1&x=2", ORIGIN + "/a#frag"):
            bad = recipe()
            bad["reads"][0]["url"] = url
            with self.assertRaises(Rejected):
                validate_open_recipe(policy, bad, 4)
        many = recipe()
        many["reads"] = [{"url": ORIGIN + "/api/v2/me"}] * 5
        with self.assertRaisesRegex(Rejected, "recipe_limits"):
            validate_open_recipe(policy, many, 4)
        with self.assertRaisesRegex(Rejected, "recipe_version"):
            validate_open_recipe(policy, {**recipe(), "version": 1}, 4)
    def post(self, url, body, content_type="application/json"):
        value = recipe()
        value["reads"][1] = {"url": url, "method": "POST", "contentType": content_type, "body": body}
        return value
    def test_post_reads_refuse_recognisable_state_changes(self):
        policy = campaign()
        graphql = ORIGIN + "/api/graphql"
        query = "query Q { a }"
        refused = [
            (ORIGIN + "/api/transfer", "{}"), (ORIGIN + "/api/payments/send", "{}"),
            (ORIGIN + "/api/v1/transfers", "{}"), (ORIGIN + "/api/payments", "{}"),
            (ORIGIN + "/api/payments/sendMoney", "{}"), (ORIGIN + "/api/transfer.do", "{}"),
            (ORIGIN + "/api/transfer/now", "{}"), (ORIGIN + "/api/payments/send/4821", "{}"),
            (ORIGIN + "/api/payBill", "{}"),
            (graphql, json.dumps({"query": "mutation Pay { pay }"})),
            (graphql, json.dumps({"query": "mutation@x{ pay }"})),
            (graphql, json.dumps({"query": ",\ufeff mutation { pay }"})),
            (graphql, json.dumps({"operationName": "CreatePayment", "query": query})),
            (graphql, json.dumps({"operationName": "ActivityMutation", "query": query})),
            (graphql, json.dumps({"operationName": "SetLimit", "query": query})),
            (graphql, json.dumps({"operationName": "sendMoney", "query": query})),
            (graphql, json.dumps({"operationName": "add_payee", "query": query})),
            (graphql, json.dumps({"operationName": "TransferFunds", "extensions": {"persistedQuery": {"version": 1}}})),
            (graphql, json.dumps({"id": "a1b2", "operationName": "ApprovePayment"})),
            (ORIGIN + "/rpc", json.dumps({"jsonrpc": "2.0", "method": "transfer.create", "params": {}})),
            (ORIGIN + "/rpc", json.dumps({"method": "moveFunds"})),
            (ORIGIN + "/pisp/domestic-payments", "{}"), (ORIGIN + "/bill-payments", "{}"),
            (ORIGIN + "/wire-transfers", "{}"), (ORIGIN + "/standing-orders", "{}"), (ORIGIN + "/moneyTransfer", "{}"),
            (ORIGIN + "/p2pSend", "{}"), (ORIGIN + "/transfer/4821", "{}"), (ORIGIN + "/payment/4821/capture", "{}"),
            (ORIGIN + "/beneficiaries", "{}"), (ORIGIN + "/cards/4821/freeze", "{}"), (ORIGIN + "/refund", "{}"),
            (ORIGIN + "/moveMoney", "{}"),
            (graphql, json.dumps({"query": "query A { a } mutation B { pay }", "operationName": "B"})),
            (graphql, json.dumps({"id": "a1b2"})), (graphql, json.dumps({"doc_id": "77"})),
            (graphql, json.dumps({"sha256Hash": "ab", "operationName": "MoveMoney"})),
        ]
        for url, body in refused:
            with self.assertRaisesRegex(Rejected, "write_request_refused", msg=url + " " + body):
                validate_open_recipe(policy, self.post(url, body), 4)
        with self.assertRaisesRegex(Rejected, "write_request_refused"):
            validate_open_recipe(policy, self.post(graphql, "query=mutation%20Pay%20%7B%20pay%20%7D",
                                                   "application/x-www-form-urlencoded"), 4)
    def test_post_reads_accept_real_history_requests(self):
        policy = campaign()
        graphql = ORIGIN + "/api/graphql"
        allowed = [
            (ORIGIN + "/svc/rr/payments/secure/v1/quickpay/payment/activity/list", "{}"),
            (ORIGIN + "/ogateway/payment-activity/api/v4/activity", json.dumps({"filter": {"pageSize": 20}})),
            (ORIGIN + "/gcgapi/prod/public/v1/p2ppayments/activityTransactionDetail", "{}"),
            (ORIGIN + "/api/transfer/history", "{}"),
            (graphql, json.dumps({"operationName": "GetPayAnyoneActivityDetailsQuery", "query": "query Q { a }"})),
            (graphql, json.dumps({"operationName": "SendMoneyActivityQuery", "query": "query Q { a }"})),
            (graphql, json.dumps({"operationName": "PermutationsQuery", "query": "{ mutation }"})),
            (graphql, json.dumps({"operationName": "SettingsQuery", "query": "query Q { a }"})),
            (graphql, json.dumps({"operationName": "AddressBookQuery", "query": "# list\nquery Q {\n  a\n}"}, indent=2)),
            (graphql, json.dumps({"operationName": "ActivityQuery", "extensions": {"persistedQuery": {"version": 1}}})),
            (graphql, json.dumps({"operationName": "PaymentHistory", "query": "query Q { a }"})),
            (graphql, json.dumps({"operationName": "TransferDetails", "query": "query Q { a }"})),
            (graphql, json.dumps({"query": "fragment F on T { a } query Q { ...F }"})),
            (ORIGIN + "/paymentHistory", "{}"), (ORIGIN + "/payment-history", "{}"),
            (ORIGIN + "/transferActivity", "{}"), (ORIGIN + "/order-history", "{}"),
            (ORIGIN + "/newTransactions", "{}"), (ORIGIN + "/pay/activity/v2", "{}"),
            (ORIGIN + "/deposit/accounts/4821/postedTransactions", "{}"), (ORIGIN + "/register/entries", "{}"),
            (ORIGIN + "/rpc", json.dumps({"method": "payment.list"})),
        ]
        for url, body in allowed:
            validate_open_recipe(policy, self.post(url, body), 4)
        validate_open_recipe(policy, self.post(ORIGIN + "/activity/list", "page=1&size=20",
                                               "application/x-www-form-urlencoded"), 4)
        get_only = campaign()
        get_only["sources"][0]["methods"] = ["GET"]
        with self.assertRaisesRegex(Rejected, "source_not_allowed"):
            validate_open_recipe(get_only, self.post(ORIGIN + "/activity/list", "{}"), 4)
        for change in ({"method": "PUT"}, {"contentType": ["application/json"]}, {"contentType": "text/plain"},
                       {"body": "\x00"}, {"body": 5}, {"body": "a=" + chr(0xD800)}):
            bad = self.post(ORIGIN + "/activity/list", "{}")
            bad["reads"][1].update(change)
            with self.assertRaisesRegex(Rejected, "recipe_invalid"):
                validate_open_recipe(policy, bad, 4)
        for url in (5, None, "https://[bad/x"):
            bad = self.post(ORIGIN + "/activity/list", "{}")
            bad["reads"][1]["url"] = url
            with self.assertRaises(Rejected):
                validate_open_recipe(policy, bad, 4)
        validate_open_recipe(policy, {**recipe(), "reads": [{"url": ORIGIN + "/api/v2/me"},
                             {"url": ORIGIN + "/odata/Activity?$top=50&expand"}]}, 4)
    def test_credential_headers_exclude_transport_control(self):
        bearer = credential_headers({"origin": ORIGIN, "kind": "bearer", "value": "abc"}, ORIGIN)
        self.assertEqual(list(bearer.items()), [("Authorization", "Bearer abc")])
        for value in ({"Host": "evil.example"}, {"Content-Length": "0"}, {COOKIE: "a", COOKIE.lower(): "b"},
                      {"X Bad": "a"}, {COOKIE: "line\nbreak"}, {COOKIE: ""}, {},
                      {COOKIE: "a", "X-HTTP-Method-Override": "DELETE"}, {COOKIE: "a", "content-type": "text/plain"},
                      {COOKIE: "a", "X-Acct-4821337711": "1"}):
            with self.assertRaisesRegex(Rejected, "credential_headers_invalid"):
                credential_headers({"origin": ORIGIN, "kind": "headers", "value": value}, ORIGIN)
        with self.assertRaisesRegex(Rejected, "invalid_credential"):
            credential_headers({"origin": "https://evil.example", "kind": "bearer", "value": "abc"}, ORIGIN)
    def test_notes_reject_identifiers_and_secrets(self):
        validate_notes("Amounts are decimal strings; negative means sent.")
        for text in ("account 123456789", "mail alice@example.com", "Bearer abcdef", "eyJhbGciOiJIUzI1NiJ9",
                     "token " + "a" * 30, "x" * 4001, "bell\x07"):
            with self.assertRaisesRegex(Rejected, "unsafe_notes"):
                validate_notes(text)


class AcquisitionTests(unittest.TestCase):
    def test_session_headers_reach_only_the_bank_and_the_probe_gets_only_public_ones(self):
        bank = Bank()
        _, _, reads, artifact = acquired(bank=bank)
        self.assertEqual([call[0] for call in bank.calls], ["probe", "probe", "bank", "bank"])
        for call in bank.calls:
            self.assertTrue(call[1].startswith(ORIGIN + "/"))
            if call[0] == "bank":
                self.assertEqual((call[2][COOKIE], call[2]["X-CSRF-Token"]), (SESSION, CSRF))
            else:
                # Only what any browser sends; every custom header is treated as part of the session.
                self.assertEqual(call[2], {"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        self.assertEqual({read.account_id for read in reads}, {"open:" + ORIGIN + ":user-48213377"})
        self.assertNotIn("user-48213377", repr(reads))
        self.assertEqual([request["gated"] for request in artifact["requests"]], [True, True])
    def test_data_served_without_the_secret_headers_is_refused(self):
        # The same rows come back to a caller holding only the public headers.
        with self.assertRaisesRegex(Rejected, "anonymous_access_allowed"):
            acquired(bank=Bank(anonymous=(200, "same")))
        # A 2xx JSON error envelope, a login page or a redirect is not the data.
        acquired(bank=Bank(anonymous=(200, {"error": "login_required"})))
        acquired(bank=Bank(anonymous=(200, None)))
        acquired(bank=Bank(anonymous=(302, None)))
    def test_a_credential_with_no_secret_bearing_header_is_not_a_session(self):
        body = payload()
        body["credential"]["value"] = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en", "Referer": ORIGIN + "/"}
        with self.assertRaisesRegex(Rejected, "credential_not_secret"):
            acquired(body=body)
        # A session header the service has never heard of still counts and is kept out of the probe.
        body["credential"]["value"] = {"User-Agent": "Mozilla/5.0", "X-Passcode": "SYNTHETIC"}
        bank = Bank()
        acquired(bank=bank, body=body)
        self.assertNotIn("X-Passcode", bank.calls[0][2])
    def test_sandbox_and_malformed_hosts_are_not_the_bank(self):
        policy = campaign()
        for host in ("sandbox.bank.example", "api-test.bank.example", "developer.bank.example",
                     "apisandbox.bank.example", "sandbox2.bank.example", "devportal.bank.example", "stg.bank.example",
                     "beta.bank.example", "uat1.bank.example", "nonprod.bank.example", "playground.bank.example",
                     "evil.com%2f.bank.example", "evil.com\\.bank.example"):
            bad = recipe()
            bad["reads"] = [{"url": "https://" + host + "/v1/me"}, {"url": "https://" + host + "/v1/activity"}]
            with self.assertRaises(Rejected):
                validate_open_recipe(policy, bad, 4)
    def test_identity_and_history_must_resolve(self):
        body = payload()
        body["recipe"]["identity"]["path"] = ["user", "missing"]
        with self.assertRaisesRegex(Rejected, "identity_path_invalid"):
            acquired(body=body)
        body = payload()
        body["recipe"]["history"]["path"] = ["activity"]
        with self.assertRaisesRegex(Rejected, "history_path_invalid"):
            acquired(body=body)
        few = copy.deepcopy(HISTORY)
        few["activity"]["items"] = few["activity"]["items"][:2]
        with self.assertRaisesRegex(Rejected, "insufficient_history"):
            acquired(bank=Bank(bodies={"/api/v2/me": ME, "/api/v2/users/user-48213377/activity": few}))
    def test_post_read_replays_the_exact_body_without_credentials_in_the_probe(self):
        body = payload()
        document = json.dumps({"operationName": "GetActivityQuery", "query": "query GetActivityQuery {\n  a\n}"})
        body["recipe"]["reads"][1] = {"url": ORIGIN + "/api/graphql", "method": "POST",
                                      "contentType": "application/json", "body": document}
        bank = Bank(bodies={"/api/v2/me": ME, "/api/graphql": HISTORY})
        _, _, reads, artifact = acquired(bank=bank, body=body)
        self.assertEqual(reads[1].method, "POST")
        self.assertEqual(bank.calls[-1][3:], (document, "application/json"))
        probe = bank.calls[1]
        self.assertEqual((probe[0], probe[1], probe[3]), ("probe", ORIGIN + "/api/graphql", document))
        self.assertNotIn(COOKIE, probe[2])
        request = artifact["requests"][1]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["body"]["fields"]["$.operationName"]["values"], ["GetActivityQuery"])
        self.assertNotIn("query GetActivityQuery", canonical(artifact).decode())
    def test_slow_peer_cannot_hold_a_request_past_its_deadline(self):
        from transcripts import transport as module
        from transcripts.transport import HTTPTransport
        client, server = socket.socketpair()
        class PassThrough:
            minimum_version = None
            def wrap_socket(self, raw, server_hostname=None):
                return raw
        def peer():
            try:
                server.recv(65536)
                for byte in b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * 200:
                    server.sendall(bytes([byte]))
                    time.sleep(0.05)
            except OSError:
                pass
        threading.Thread(target=peer, daemon=True).start()
        def fake(host, port=443, timeout=15):
            client.settimeout(timeout)
            return client
        started = time.monotonic()
        try:
            with patch.object(module, "public_socket", fake), \
                    patch.object(module.ssl, "create_default_context", lambda: PassThrough()):
                with self.assertRaisesRegex(Rejected, "request_timeout"):
                    HTTPTransport("direct").request_provider("https://inference.example/v1/chat/completions",
                                                             headers={"Accept": "application/json"}, body=b"{}",
                                                             timeout=0.4)
        finally:
            client.close()
            server.close()
        self.assertLess(time.monotonic() - started, 2.0)


class TranscriptTests(unittest.TestCase):
    def test_transcript_keeps_names_and_shapes_but_no_bank_values(self):
        policy, _, _, artifact = acquired()
        validate_artifact(policy, artifact)
        encoded = canonical(artifact).decode()
        for secret in PRIVATE + ("Illinois", "Bob Example", "carol77", "12.50", "2026-09-30", "SYNTHETIC-CSRF"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(artifact["credentialHeaders"], ["cookie", "user-agent", "x-client-version", "x-csrf-token"])
        history = artifact["requests"][1]
        self.assertEqual(history["path"], "/api/v2/users/{id}/activity")
        self.assertEqual(history["query"], [{"name": "limit", "value": "20"}, {"name": "cursor", "value": "{digits:10}"}])
        shapes = history["fields"]
        self.assertEqual(shapes["$.activity.items[].amount"], {"types": ["string"], "formats": ["decimal:neg:2", "decimal:pos:2"]})
        self.assertEqual(shapes["$.activity.items[].createdAt"]["formats"], ["datetime:iso8601:utc"])
        self.assertEqual(shapes["$.activity.items[].status"]["values"], ["completed", "pending"])
        self.assertEqual(shapes["$.activity.items[].currency"]["values"], ["USD"])
        # Account numbers used as object keys collapse to a wildcard.
        self.assertIn("$.activity.byAccount.{key}.balance", shapes)
        self.assertEqual(artifact["identity"], {"step": 1, "path": "$.user.id"})
        self.assertEqual(artifact["history"], {"step": 2, "path": "$.activity.items"})
    def test_status_like_keys_under_personal_objects_and_tainted_tokens_are_withheld(self):
        _, _, _, artifact = acquired()
        profile = artifact["requests"][0]["fields"]
        self.assertNotIn("values", profile["$.user.address.state"])
        self.assertNotIn("values", profile["$.user.kind"])  # also under a personal ancestor
        leaky = copy.deepcopy(HISTORY)
        for row in leaky["activity"]["items"]:
            row["memo"] = "completed"
        _, _, _, artifact = acquired(bank=Bank(bodies={"/api/v2/me": ME, "/api/v2/users/user-48213377/activity": leaky}))
        status = artifact["requests"][1]["fields"]["$.activity.items[].status"]
        self.assertEqual((status["values"], status["valuesIncomplete"]), (["pending"], True))
    def test_notes_cannot_carry_values_seen_in_the_responses(self):
        with self.assertRaisesRegex(Rejected, "unsafe_notes"):
            acquired(body=payload(notes="my handle carol77 works"))
        with self.assertRaisesRegex(Rejected, "unsafe_notes"):
            acquired(body=payload(notes="identity is user-48213377"))
    def test_validator_rejects_injected_values(self):
        policy, _, _, artifact = acquired()
        for mutate in (lambda a: a["requests"][1]["fields"].update({"$.activity.items[].alice@example.com": {"types": ["string"]}}),
                       lambda a: a["requests"][1]["fields"]["$.activity.items[].memo"].update(values=["Dinner"]),
                       lambda a: a["requests"][1]["fields"]["$.activity.items[].amount"].update(formats=["-12.50"]),
                       lambda a: a["requests"][1].update(path="/api/v2/users/user-48213377/activity"),
                       lambda a: a["requests"][1]["query"].append({"name": "cursor", "value": "4821337700"}),
                       lambda a: a.update(notes="call 4155551234567"),
                       lambda a: a["requests"][1]["fields"].update({"$.activity.items[].acct_4821337700": {"types": ["string"]}}),
                       lambda a: a["requests"][1]["fields"].update({"$.activity.items[].abcdefabcdefabcdefab": {"types": ["string"]}}),
                       lambda a: a["requests"][0]["fields"]["$.user.address.state"].update(values=["Illinois"]),
                       lambda a: a["requests"][1]["fields"]["$.activity.items[].status"].update(values=["acct-9912-7731"]),
                       lambda a: a["requests"][1].update(path="/api/v2/users/alice.example/activity"),
                       lambda a: a["requests"][1]["query"].append({"name": "type", "value": "user-48213377"}),
                       lambda a: a.update(sourceOrigins=["https://evil.com\\.bank.example"]),
                       lambda a: a.update(sourceOrigins=["https://acme-plumbing.bank.example"]),
                       lambda a: a["requests"][1].update(gated=False),
                       lambda a: a.update(credentialHeaders=["cookie", "host"]),
                       lambda a: a.update(rawBody={"x": 1})):
            candidate = copy.deepcopy(artifact)
            mutate(candidate)
            with self.assertRaises(Rejected):
                validate_artifact(policy, candidate)
    def leak_check(self, me=None, history=None, url=None, secrets=()):
        body = payload()
        bodies = {"/api/v2/me": me or ME, "/api/v2/users/user-48213377/activity": history or HISTORY}
        if url:
            body["recipe"]["reads"][1]["url"] = url
            bodies[url[len(ORIGIN):].split("?")[0]] = history or HISTORY
        policy, _, _, artifact = acquired(bank=Bank(bodies=bodies), body=body)
        validate_artifact(policy, artifact)
        encoded = canonical(artifact).decode()
        for secret in secrets:
            self.assertNotIn(secret, encoded)
        return artifact
    def test_data_used_as_object_keys_is_collapsed(self):
        me = copy.deepcopy(ME)
        me["user"]["sharedWith"] = {"alicesmith": True, "bobjones": True, "carolwhite": False}
        me["user"]["contacts"] = {"gracehall": {"since": "2020", "tag": "x"}, "heidiklum": {"since": "2021"},
                                  "ivanpetrov": {"since": "2022", "note": "y", "extra": 1}}
        me["user"]["accounts"] = {"kQzmW7pLxa": {"balance": 1.5}}
        me["user"]["byRef"] = {"abcdefabcdefabcdefab": {"balance": 2.5}}
        self.leak_check(me=me, secrets=("alicesmith", "bobjones", "gracehall", "ivanpetrov", "kQzmW7pLxa",
                                         "abcdefabcdefabcdefab"))
    def test_status_like_values_outside_payment_rows_are_never_kept(self):
        me = copy.deepcopy(ME)
        me["user"].update(maritalStatus="Married", residencyState="Kansas", accountType="Premier",
                          billing={"state": "Illinois"}, defaultPaymentMethod="Visa-4242")
        history = copy.deepcopy(HISTORY)
        for row in history["activity"]["items"]:
            row.update(merchantState="Nevada", addressState="Oregon", holderType="Widow", type="card-4242",
                       state="Texas", toState="Ohio", paymentMethod="alicesavings")
        artifact = self.leak_check(me=me, history=history, secrets=("Married", "Kansas", "Premier", "Illinois",
                                   "Visa-4242", "Nevada", "Oregon", "Widow", "card-4242", "Texas", "Ohio",
                                   "alicesavings"))
        self.assertTrue(all("values" not in entry for entry in artifact["requests"][0]["fields"].values()))
    def test_url_identifiers_and_tokens_are_templated(self):
        for url, secrets, path in (
                (ORIGIN + "/orgs/acme-plumbing-llc/activity?limit=20", ("acme-plumbing-llc",), "/orgs/{id}/activity"),
                (ORIGIN + "/accounts/kQzmW7pLxa/history", ("kQzmW7pLxa",), "/accounts/{id}/history"),
                (ORIGIN + "/u/alice.smith/activity", ("alice.smith",), "/u/{id}/activity"),
                (ORIGIN + "/workspaces/acme-plumbing/activity", ("acme-plumbing",), "/workspaces/{id}/activity"),
                (ORIGIN + "/2026Q4/alicesmith/feed", ("alicesmith",), "/2026Q4/{id}/feed"),
                (ORIGIN + "/api/2026-10-01/svc/quickpay/activity", (), "/api/2026-10-01/svc/quickpay/activity"),
                (ORIGIN + "/api/activity?state=Zx81TokenValue&type=CHK-0048213377&acct_4821337711=1&view=alicesmith",
                 ("Zx81TokenValue", "CHK-0048213377", "acct_4821337711", "alicesmith"), "/api/activity")):
            artifact = self.leak_check(url=url, secrets=secrets)
            self.assertEqual(artifact["requests"][1]["path"], path)
    def test_tenant_host_labels_are_not_recorded(self):
        policy = campaign()
        body = payload()
        body["credential"]["origin"] = "https://acme-plumbing.bank.example"
        body["recipe"]["reads"] = [{"url": "https://acme-plumbing.bank.example/api/v2/me"},
                                   {"url": "https://acme-plumbing.bank.example/api/v2/users/user-48213377/activity"}]
        _, _, _, artifact = acquired(policy=policy, body=body)
        self.assertEqual(artifact["sourceOrigins"], ["https://{sub}.bank.example"])
        body["credential"]["origin"] = "https://api2.bank.example"
        for read in body["recipe"]["reads"]:
            read["url"] = read["url"].replace("acme-plumbing", "api2")
        self.assertEqual(acquired(policy=policy, body=body)[3]["sourceOrigins"], ["https://api2.bank.example"])
        from transcripts.open_source import INFRA_LABEL
        for label in ("mjones", "mysmith", "ibrahim", "webster", "paybob"):
            self.assertIsNone(INFRA_LABEL.fullmatch(label), label)
        for label in ("api", "secure05ea", "web3", "online"):
            self.assertIsNotNone(INFRA_LABEL.fullmatch(label), label)
    def test_post_body_values_and_notes_with_personal_text_are_not_kept(self):
        body = payload()
        document = json.dumps({"operationName": "GetActivityQuery", "query": "query Q { a }",
                               "variables": {"accountType": "SAV-0048213377", "pageState": "AAEBAgMEBQYH"}})
        body["recipe"]["reads"][1] = {"url": ORIGIN + "/api/graphql", "method": "POST",
                                      "contentType": "application/json", "body": document}
        _, _, _, artifact = acquired(bank=Bank(bodies={"/api/v2/me": ME, "/api/graphql": HISTORY}), body=body)
        for secret in ("SAV-0048213377", "AAEBAgMEBQYH"):
            self.assertNotIn(secret, canonical(artifact).decode())
        for notes in ("Paid Bob Example last week", "call 415-555-0101", "ssn 123-45-6789", "lives in Springfield",
                      "phone (415) 555 0101",
                      "card 4111 1111 1111 1111", "id is user 4821 3377"):
            with self.assertRaisesRegex(Rejected, "unsafe_notes"):
                acquired(body=payload(notes=notes))
    def test_format_classes_never_echo_values(self):
        samples = {"2026-10-01T08:00:00+05:30": "datetime:iso8601:offset", "2026-10-01": "date:iso8601", "": "empty",
                   "123e4567-e89b-42d3-a456-426614174000": "uuid", "0012345": "digits:7", "-45": "digits:neg:2",
                   "19.99": "decimal:pos:2", "EUR": "currency_code", "a@b.co": "email", "https://x.example/y": "url",
                   "1,000 USD": "money_text", "deadbeefdeadbeefdeadbeef": "hex:short", "Hello": "text:short:alpha",
                   "+14155550101": "phone", "+44 20 7946 0958": "phone", "user-48213377": "text:medium:mixed",
                   12: "int:pos:2", -3.5: "float:neg:1", 0: "int:zero:1"}
        for value, expected in samples.items():
            self.assertEqual(value_format(value), expected)
        self.assertEqual(value_format(1759300000, "createdAt"), "int:epoch_s")
        self.assertEqual(value_format(1759300000, "id"), "int:pos:10")
        self.assertIsNone(value_format(True))


class AssessmentTests(unittest.TestCase):
    def test_correct_mapping_scores_full_and_is_recomputed_at_acceptance(self):
        policy, context, reads, artifact = acquired()
        result = assess(policy, reads, context, artifact, {"mapping": MAPPING, "completedStatus": ["completed", "nope"]})
        self.assertEqual((result["score"], result["useful"], result["unverified"]), (100, True, []))
        self.assertEqual(result["completedStatus"], ["completed"])
        self.assertEqual(sum(ROLE_WEIGHTS.values()), 100)
        check_assessment(policy, reads, context, artifact, result)
        validate_model_result(policy, artifact, result)
    def test_wrong_fields_are_not_credited(self):
        policy, context, reads, artifact = acquired()
        wrong = dict(MAPPING, amount="$.activity.items[].memo", timestamp="$.activity.items[].id",
                     paymentId="$.activity.items[].currency", currency="$.activity.items[].status")
        result = assess(policy, reads, context, artifact, {"mapping": wrong, "completedStatus": []})
        self.assertEqual(set(result["mapping"]), {"counterparty", "status"})
        self.assertFalse(result["useful"])
        with self.assertRaisesRegex(Rejected, "mapping_missing_paymentId"):
            check_assessment(policy, reads, context, artifact, result)
    def test_paths_outside_history_or_reused_paths_do_not_count(self):
        policy, context, reads, artifact = acquired()
        outside = dict(MAPPING, counterparty="$.activity.byAccount.{key}.balance", status="$.activity.items[].id")
        result = assess(policy, reads, context, artifact, {"mapping": outside, "completedStatus": []})
        self.assertEqual(sorted(result["unverified"]), ["counterparty", "status"])
        self.assertEqual(result["score"], 75)
    def test_stored_score_cannot_exceed_what_the_records_support(self):
        policy, context, reads, artifact = acquired()
        honest = assess(policy, reads, context, artifact, {"mapping": {"paymentId": MAPPING["paymentId"]},
                                                           "completedStatus": []})
        forged = dict(honest, score=100, useful=True)
        with self.assertRaisesRegex(Rejected, "model_result_invalid"):
            check_assessment(policy, reads, context, artifact, forged)
        forged = dict(honest, mapping=dict(MAPPING, amount="$.activity.items[].memo"), score=100, useful=True)
        with self.assertRaisesRegex(Rejected, "model_result_invalid"):
            check_assessment(policy, reads, context, artifact, forged)
    def test_model_reply_parsing_finds_the_answer_in_wrapped_replies(self):
        answer = json.dumps({"mapping": MAPPING, "completedStatus": ["completed"], "score": 100})
        expected = {"mapping": MAPPING, "completedStatus": ["completed"]}
        for text in ("```json\n" + answer + "\n```",
                     "<think>maybe {\"mapping\": {\"paymentId\": \"$.wrong\"}} or {broken</think>\n" + answer,
                     "Here is the result: " + answer + " Let me know.",
                     json.dumps({"note": "first"}) + "\n" + answer):
            self.assertEqual(parse_proposal(text), expected)
        self.assertEqual(parse_proposal(json.dumps({"mapping": {"paymentId": None, "extra": "x"}})),
                         {"mapping": {}, "completedStatus": []})
        for text in ("no json here", "{broken", None, json.dumps({"mapping": "x"}), json.dumps({"score": 100})):
            with self.assertRaisesRegex(Rejected, "model_output_not_json"):
                parse_proposal(text)
    def test_role_checks_accept_common_bank_encodings(self):
        from transcripts.open_source import _numeric, _timestamp
        for value in (12.5, -3, "-12.50", "12,50", "1.234,56", "1,000 USD", "Rp 150.000", "\u20ab 1.000.000",
                      "$12.50", "(45.00)", "0.10"):
            self.assertTrue(_numeric(value), value)
        for value in ("2026-10-01", "txn-00017", "hello", "", None, True, "0012345", "1 2 3 4 5"):
            self.assertFalse(_numeric(value), value)
        for value in ("2026-10-01T08:00:00Z", "2026-10-01", "10/01/2026", "01.10.2026", "10/01/2026 08:00:00",
                      "20261001", "20261001083000", 1759300000, 1759300000000, 1759300000.25, "1759300000"):
            self.assertTrue(_timestamp(value), value)
        for value in ("12.50", "hello", 42, "4821337700123", None, True, "20269901", "9" * 5000):
            self.assertFalse(_timestamp(value), value)
    def test_selector_through_data_keyed_siblings_and_sort_fields_still_maps(self):
        rows = copy.deepcopy(HISTORY["activity"]["items"])
        nested = {"sortBy": "createdAt", "orderBy": "amount",
                  "buckets": {"usd": {"items": rows}, "eur": {"items": []}, "gbp": {"items": []}}}
        body = payload()
        body["recipe"]["history"]["path"] = ["buckets", "usd", "items"]
        policy, context, reads, artifact = acquired(
            bank=Bank(bodies={"/api/v2/me": ME, "/api/v2/users/user-48213377/activity": nested}), body=body)
        prefix = artifact["history"]["path"]
        self.assertTrue(prefix.endswith(".{key}.items"))  # the currency bucket is data, not a field name
        mapping = {role: path.replace("$.activity.items", prefix) for role, path in MAPPING.items()}
        result = assess(policy, reads, context, artifact, {"mapping": mapping, "completedStatus": []})
        self.assertEqual((result["score"], result["unverified"]), (100, []))
        # A response value naming a schema field under a sort key does not hide that field.
        self.assertIn(prefix + "[].createdAt", artifact["requests"][1]["fields"])
    def bank_rows(self, rows, mapping, path=("rows",)):
        body = payload()
        body["recipe"]["history"]["path"] = list(path)
        policy, context, reads, artifact = acquired(
            bank=Bank(bodies={"/api/v2/me": ME, "/api/v2/users/user-48213377/activity": {"rows": rows}}), body=body)
        prefix = artifact["history"]["path"] + "[]"
        proposal = {role: prefix + suffix for role, suffix in mapping.items()}
        return artifact, assess(policy, reads, context, artifact, {"mapping": proposal, "completedStatus": []})
    def test_common_bank_row_shapes_keep_their_field_names(self):
        # Flat rows whose values are all strings, in a non-English schema.
        flat = [{"TransactionID": "QX1A%d" % index, "CompletedTime": "2026-10-0%d 08:00:00" % index,
                 "Jumlah": "1,250.00", "Penerima": name, "TransactionStatus": "Completed", "Keterangan": "x%d" % index}
                for index, name in ((1, "ana"), (2, "budi"), (3, "citra"))]
        artifact, result = self.bank_rows(flat, {"paymentId": ".TransactionID", "amount": ".Jumlah",
                                                 "timestamp": ".CompletedTime", "counterparty": ".Penerima",
                                                 "status": ".TransactionStatus"})
        self.assertEqual((result["score"], result["unverified"]), (95, []))
        # Nested amount and counterparty objects with three same-typed members each.
        nested = [{"id": 9000 + index, "amount": {"value": "12.50", "currency": "EUR", "formatted": "12,50 EUR"},
                   "counterparty": {"name": name, "handle": name + "x", "account": "ACC" + name},
                   "bookedAt": 1759300000 + index, "endToEndId": "E2E-%d" % index, "memo": "Amount"}
                  for index, name in ((1, "ana"), (2, "budi"), (3, "citra"))]
        artifact, result = self.bank_rows(nested, {"paymentId": ".id", "amount": ".amount.value",
                                                   "timestamp": ".bookedAt", "counterparty": ".counterparty.handle",
                                                   "currency": ".amount.currency"})
        self.assertEqual((result["score"], result["unverified"]), (90, []))
        self.assertIn("$.rows[].endToEndId", artifact["requests"][1]["fields"])
    def test_names_seen_once_are_kept_only_when_made_of_common_words(self):
        me = copy.deepcopy(ME)
        me["user"].update(sharedWith={"alicesmith": True, "bobjones": True}, vault={"mainchecking": {"balance": 1.0}},
                          limits={"daily": 5, "monthlyTotal": 9}, contacts={"gracehall": [1], "heidi": []})
        body = payload()
        policy, _, _, artifact = acquired(bank=Bank(bodies={"/api/v2/me": me,
                                                            "/api/v2/users/user-48213377/activity": HISTORY}), body=body)
        encoded = canonical(artifact).decode()
        for secret in ("alicesmith", "bobjones", "mainchecking", "gracehall", "heidi"):
            self.assertNotIn(secret, encoded)
        self.assertIn("$.user.limits.monthlyTotal", artifact["requests"][0]["fields"])
        self.assertEqual(artifact["identity"]["path"], "$.user.id")
    def test_status_codes_with_digits_are_withheld_without_failing_the_role(self):
        rows = copy.deepcopy(HISTORY["activity"]["items"])
        for row, code in zip(rows, ("MT103", "pacs.008", "SETTLED")):
            row["status"] = code
        artifact, result = self.bank_rows(rows, {"paymentId": ".id", "amount": ".amount", "timestamp": ".createdAt",
                                                 "counterparty": ".counterparty.handle", "status": ".status"})
        self.assertIn("status", result["mapping"])
        status = artifact["requests"][1]["fields"]["$.rows[].status"]
        self.assertEqual((status["values"], status["valuesIncomplete"]), (["SETTLED"], True))
    def test_row_witnesses_follow_the_history_not_the_declared_identity(self):
        from transcripts.open_source import row_witnesses
        _, context, reads, _ = acquired()
        first = row_witnesses(reads, context)
        other = payload()
        other["recipe"]["identity"]["path"] = ["user", "email"]
        _, context, reads, _ = acquired(body=other)
        self.assertNotEqual(reads[0].account_id, "open:" + ORIGIN + ":user-48213377")
        self.assertEqual(row_witnesses(reads, context), first)
        self.assertEqual(len(first), 3)


class ProviderTests(unittest.TestCase):
    def propose(self, bank, **changes):
        policy, context, reads, artifact = acquired()
        client = ProviderClient(policy, reservation(policy, **changes), INFERENCE, bank)
        return client, artifact, client.grade(artifact, NOW + 3)
    def test_prompt_is_peerlink_text_around_notes_and_value_free_transcript(self):
        bank = Bank()
        client, artifact, proposal = self.propose(bank)
        kind, url, headers, body = bank.calls[-1]
        self.assertEqual((kind, url), ("provider", BASE + "/chat/completions"))
        self.assertEqual(headers["Authorization"], "Bearer " + INFERENCE)
        sent = json.loads(body)
        self.assertEqual(sent["model"], "any/model-1")
        self.assertEqual([message["role"] for message in sent["messages"]], ["system", "user"])
        self.assertEqual(sent["messages"][0]["content"], OPEN_PREFIX)
        user = sent["messages"][1]["content"]
        self.assertTrue(user.startswith("<contributor_notes>\n" + artifact["notes"]))
        self.assertTrue(user.endswith(OPEN_SUFFIX))
        for secret in PRIVATE:
            self.assertNotIn(secret, body.decode())
        self.assertEqual(proposal["mapping"], MAPPING)
        self.assertEqual(client.metadata["baseUrl"], BASE)
        self.assertEqual(client.metadata["requestDigest"], digest(sent))
        self.assertEqual((client.metadata["inputTokens"], client.metadata["outputTokens"]), (900, 80))
    def test_named_providers_use_their_fixed_endpoints_with_any_model(self):
        bank = Bank()
        client, _, _ = self.propose(bank, provider="openai", model="gpt-anything")
        self.assertEqual(bank.calls[-1][1], "https://api.openai.com/v1/chat/completions")
        self.assertIn("max_completion_tokens", json.loads(bank.calls[-1][3]))
        self.assertNotIn("baseUrl", client.metadata)
        bank = Bank()
        self.propose(bank, provider="near", model="some/other-model")
        self.assertEqual(bank.calls[-1][1], "https://cloud-api.near.ai/v1/chat/completions")
        self.assertIn("max_tokens", json.loads(bank.calls[-1][3]))
    def test_one_shape_retry_on_400_and_no_other_retry(self):
        bank = Bank(provider_failures=["provider_http_bad_request"])
        self.propose(bank)
        sent = [json.loads(call[3]) for call in bank.calls if call[0] == "provider"]
        self.assertEqual(len(sent), 2)
        self.assertIn("max_tokens", sent[0])
        self.assertIn("max_completion_tokens", sent[1])
        bank = Bank(provider_failures=["provider_http_bad_request", "provider_http_bad_request"])
        with self.assertRaisesRegex(Rejected, "provider_http_bad_request"):
            self.propose(bank)
        bank = Bank(provider_failures=["provider_http_unauthorized"])
        with self.assertRaisesRegex(Rejected, "provider_http_unauthorized"):
            self.propose(bank)
        self.assertEqual(sum(call[0] == "provider" for call in bank.calls), 1)
    def test_unusable_model_output_fails_with_a_specific_code(self):
        with self.assertRaisesRegex(Rejected, "model_output_not_json"):
            self.propose(Bank(model="I cannot help with that."))
        policy, context, reads, artifact = acquired()
        client = ProviderClient(policy, reservation(policy), INFERENCE, Bank())
        client.close()
        with self.assertRaisesRegex(Rejected, "inference_key_required"):
            client.grade(artifact, NOW + 3)
    def test_reviewed_campaigns_keep_pinned_routes(self):
        from transcripts.tests.test_core import campaign as reviewed, request
        policy = reviewed()
        with self.assertRaisesRegex(Rejected, "provider_not_allowed"):
            ProviderClient(policy, {**request(policy), "provider": "openai_compatible", "inferenceBaseUrl": BASE},
                           INFERENCE, Bank())
        self.assertNotEqual(open_prompt_digest(), hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest())


class OpenEpoch(FakeEpoch):
    def accept(self, job_id, reads, grade, now, context=None):
        self.require_active()
        return self.ledger.accept(job_id, reads, grade, dedup_key=KEY, now=now, context=context)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch("transcripts.runtime.time.time", return_value=NOW + 3)
        self.clock.start()
        self.events, self.epoch = [], OpenEpoch()
        self.archive = FakeArchive(self.events)
        self.policy = {"promptDigest": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                       "openPromptDigest": open_prompt_digest(), "payoutRpc": "https://rpc.example",
                       "campaigns": [campaign()], "operatorPublicKey": PUBLIC_OPERATOR, "pilotBudgetMinor": 50_000_000,
                       "payoutAuthority": {"kind": "aws_kms", "keyId": KEY_ID, "wallet": self.epoch.wallet}}
        self.bank = Bank()
        with patch("transcripts.runtime.Channel", return_value=SigningChannel()):
            self.runtime = Runtime(self.policy, self.epoch, self.bank, self.archive,
                                   attester=lambda *args: b"synthetic-quote")
        self.runtime.coordinator = FakeCoordinator(self.epoch.ledger, self.events)
    def tearDown(self):
        self.epoch.ledger.close()
        self.clock.stop()
    def run_job(self, wallet=1, body=None):
        status = self.runtime.dispatch("reserve", reservation(self.policy["campaigns"][0], wallet))
        self.epoch.ledger.submit(status["jobId"], status["bindingDigest"], NOW + 3)
        body = body or payload()
        self.runtime.jobs.acquire()
        self.runtime.process(status["jobId"], body)
        self.assertEqual(body, {})
        return status["jobId"], self.epoch.ledger.status(status["jobId"])
    def test_open_contribution_is_archived_and_paid_without_private_data(self):
        job_id, status = self.run_job()
        self.assertEqual(status["state"], "paid")
        self.assertEqual(self.events, ["archive", "reconcile", "paid", "archive"])
        for archived in self.archive.records:
            record = archived["payload"]
            validate_archive_record(self.policy["campaigns"][0], record, policy=self.policy)
            self.assertEqual(record["modelResult"]["score"], 100)
            self.assertEqual(record["inference"]["baseUrl"], BASE)
            encoded = canonical(archived).decode()
            for secret in PRIVATE:
                self.assertNotIn(secret, encoded)
        self.assertEqual(self.bank.calls[-1][0], "provider")
        self.assertEqual(self.runtime.dispatch("campaigns", {})["availability"],
                         {"budgetRemainingMinor": 45_000_000,
                          "campaigns": [{"campaignId": "synthetic-open-v1", "slotsRemaining": 1}]})
    def test_model_cannot_grant_itself_a_score(self):
        self.bank.model = {"mapping": {"paymentId": MAPPING["paymentId"]}, "score": 100, "useful": True,
                           "rubricVersion": "transcript-mapping-v1"}
        _, status = self.run_job()
        self.assertEqual((status["state"], status["reason"]), ("rejected", "mapping_missing_amount"))
        self.assertEqual(self.archive.records, [])
    def test_failures_surface_specific_fixed_codes(self):
        self.bank.anonymous = (200, "same")
        _, status = self.run_job()
        self.assertEqual((status["state"], status["reason"]), ("rejected", "anonymous_access_allowed"))
        self.bank.anonymous = (401, None)
        _, status = self.run_job(wallet=2, body=payload(notes="call me on 4155550101999"))
        self.assertEqual(status["reason"], "unsafe_notes")
        self.bank.provider_failures = ["provider_http_unauthorized"]
        _, status = self.run_job(wallet=3)
        self.assertEqual(status["reason"], "provider_http_unauthorized")
    def test_same_account_is_paid_once_per_campaign(self):
        self.assertEqual(self.run_job(wallet=1)[1]["state"], "paid")
        _, status = self.run_job(wallet=2)
        self.assertEqual((status["state"], status["reason"]), ("rejected", "duplicate_account"))
    def test_same_history_under_another_identity_selector_is_a_duplicate(self):
        self.assertEqual(self.run_job(wallet=1)[1]["state"], "paid")
        other = payload()
        other["recipe"]["identity"]["path"] = ["user", "email"]
        _, status = self.run_job(wallet=2, body=other)
        self.assertEqual((status["state"], status["reason"]), ("rejected", "duplicate_account"))
    def test_rows_as_long_as_a_real_bank_row_are_paid_and_still_deduplicated(self):
        # Found on the validation enclave: a row witness built from the row text
        # overran the account-id bound, so every realistic history was rejected.
        rows = [{"id": "txn-%05d" % (100 + index), "amount": "-%d.50" % (index + 1), "currency": "USD",
                 "createdAt": "2026-09-%02dT10:11:12Z" % (index + 1), "status": "completed",
                 "counterparty": {"handle": "payee_%02d" % index, "name": "Person Example"},
                 "details": {"reference": "invoice " + "lorem ipsum " * 60, "sourceCurrency": "USD",
                             "targetCurrency": "USD", "rate": 1.0, "hasActiveIssues": False,
                             "businessCategory": None, "quoteUuid": "0f8fad5b-d9cb-469f-a165-70867728950e"}}
                for index in range(20)]
        self.assertTrue(all(len(canonical(row)) > 800 for row in rows))
        self.bank.bodies = {"/api/v2/me": ME, "/api/v2/users/user-48213377/activity": {"activity": {"items": rows}}}
        self.assertEqual(self.run_job(wallet=1)[1]["state"], "paid")
        other = payload()
        other["recipe"]["identity"]["path"] = ["user", "email"]
        _, status = self.run_job(wallet=2, body=other)
        self.assertEqual((status["state"], status["reason"]), ("rejected", "duplicate_account"))
    def test_campaign_list_survives_an_unavailable_ledger(self):
        with patch.object(self.epoch.ledger, "availability", side_effect=Rejected("state_unavailable")):
            self.assertEqual(set(self.runtime.dispatch("campaigns", {})), {"policyDigest", "campaigns"})
    def test_runtime_requires_the_measured_open_prompt(self):
        policy = dict(self.policy, openPromptDigest="0" * 64)
        with patch("transcripts.runtime.Channel", return_value=SigningChannel()):
            with self.assertRaisesRegex(Rejected, "prompt_mismatch"):
                Runtime(policy, OpenEpoch(), self.bank, self.archive, attester=lambda *args: b"q")


class DurableCapacityTests(unittest.TestCase):
    def test_snapshot_holds_every_shipped_campaign_and_restarts(self):
        from pathlib import Path
        from transcripts.aws_state import Authority, StateAnchor
        from transcripts.epoch import BootEpoch
        from transcripts.tests.test_core_epoch import synthetic_epoch
        from transcripts.tests.test_durable import CONFIG, SyntheticAWS
        policy = json.loads((Path(__file__).parents[1] / "policy.json").read_text())
        opens = [item for item in policy["campaigns"] if "openSource" in item]
        self.assertGreater(len(opens), 5)
        old = synthetic_epoch()
        signer = old._signer
        old.close()
        aws = SyntheticAWS()

        def boot():
            authority = Authority(CONFIG, aws)
            head = authority.load()
            anchor = StateAnchor(CONFIG, digest(policy), signer.address.lower(), b"0" * 32, b"synthetic-wrapped-master",
                                 authority, head)
            snapshot = anchor.open(head) if head else None
            with patch("transcripts.epoch._require_nsm"), patch("transcripts.epoch.time.time", return_value=NOW + 5):
                return BootEpoch.create(signer, budget_minor=50_000_000, state_anchor=anchor, initial_snapshot=snapshot)

        epoch = boot()
        # More distinct campaigns than the old five-campaign snapshot bound, within in-flight capacity.
        for index, item in enumerate(opens[:6], 1):
            request = {"version": 1, "campaignId": item["id"], "payoutAddress": "0x" + f"{index:040x}",
                       "provider": "openai", "model": "gpt-x", "privacyMode": "provider_visible", "consent": True,
                       "policyDigest": digest(item), "expiresAt": NOW + 600, "limits": campaign_limits(item)}
            self.assertEqual(epoch.ledger.reserve(item, request, NOW)["state"], "reserved")
        self.assertEqual(len(epoch.ledger.availability(policy["campaigns"], NOW)["campaigns"]), len(policy["campaigns"]))
        epoch.ledger.close()
        restarted = boot()
        self.assertEqual(restarted.ledger.retirement_status()["state"], "open")
        restarted.ledger.close()
    def test_paid_rows_do_not_reserve_a_full_job_allowance(self):
        from transcripts.aws_state import JOB_STORAGE_ALLOWANCE, MAX_CIPHERTEXT, PAID_STORAGE_ALLOWANCE, StateAnchor
        anchor = object.__new__(StateAnchor)
        row = {"id": "a" * 32, "campaign": canonical(campaign()).decode(), "request": None, "artifact": None,
               "evidence": None, "receipt_job": None, "payout_intent": None, "account_aliases": None}
        paid = [dict(row, id=f"{index:032x}", state="paid") for index in range(10)]
        anchor.capacity({"revision": 1, "budget": 50_000_000, "jobs": paid, "retirement": {}, "runtime": {}})
        self.assertLess(10 * PAID_STORAGE_ALLOWANCE, JOB_STORAGE_ALLOWANCE)
        live = [dict(row, id=f"{index:032x}", state="reserved") for index in range(MAX_CIPHERTEXT // JOB_STORAGE_ALLOWANCE + 1)]
        with self.assertRaisesRegex(Rejected, "state_capacity"):
            anchor.capacity({"revision": 1, "budget": 50_000_000, "jobs": live, "retirement": {}, "runtime": {}})


class HostAndCliTests(unittest.TestCase):
    def test_relay_public_egress_is_opt_in_and_dns_names_only(self):
        allowed = {"api.bank.example"}
        self.assertTrue(egress_permitted("api.bank.example", allowed, False))
        self.assertFalse(egress_permitted("inference.example", allowed, False))
        self.assertTrue(egress_permitted("inference.example", allowed, True))
        for host in ("127.0.0.1", "localhost", "169.254.169.254", "a..b", "UPPER.example", "x" * 300 + ".com", 5):
            self.assertFalse(egress_permitted(host, allowed, True))
    def test_preview_runs_locally_and_reports_the_assessment(self):
        from transcripts.cli import preview
        body = payload()
        with patch("transcripts.transport.HTTPTransport", return_value=Bank()):
            result = preview({"campaigns": [campaign()]}, "synthetic-open-v1", body, MAPPING)
        self.assertTrue(result["acquired"])
        self.assertEqual(result["assessment"]["score"], 100)
        self.assertIn("$.activity.items[].counterparty.handle", result["historyFieldPaths"])
        for secret in PRIVATE:
            self.assertNotIn(secret, json.dumps(result))
        # Local, value-free facts for the notes; the model picks the completed tokens.
        self.assertNotIn("completedStatus", result["assessment"])
        self.assertEqual({key: result["observations"][key] for key in
                          ("records", "timestampOrder", "amountForm", "amountSign", "statusUsage")},
                         {"records": 3, "timestampOrder": "oldest_first", "amountForm": "text", "amountSign": "mixed",
                          "statusUsage": {"completed": 2, "pending": 1}})
    def test_lookup_returns_one_value_from_one_read(self):
        from transcripts.cli import lookup
        policy = {"campaigns": [campaign()]}
        bank = Bank()
        with patch("transcripts.transport.HTTPTransport", return_value=bank):
            found = lookup(policy, "synthetic-open-v1", payload(), 0, ["user", "id"])
            self.assertEqual((found["read"], found["value"]), (0, "user-48213377"))
            # Only the chosen read is sent, with the session, and never a probe or model call.
            self.assertEqual([call[0] for call in bank.calls], ["bank"])
            self.assertTrue(bank.calls[0][1].endswith("/api/v2/me"))
            for path in (["user"], ["user", "missing"], ["user", "address", "city", 0]):
                with self.assertRaisesRegex(Rejected, "lookup_not_scalar"):
                    lookup(policy, "synthetic-open-v1", payload(), 0, path)
            with self.assertRaisesRegex(Rejected, "recipe_invalid"):
                lookup(policy, "synthetic-open-v1", payload(), 2, ["user", "id"])
            outside = payload()
            outside["recipe"]["reads"][0]["url"] = "https://elsewhere.example/api/v2/me"
            with self.assertRaisesRegex(Rejected, "source_not_allowed"):
                lookup(policy, "synthetic-open-v1", outside, 0, ["user", "id"])
            write = payload()
            write["recipe"]["reads"][0] = {"url": ORIGIN + "/api/payments/send", "method": "POST",
                                           "contentType": "application/json", "body": "{}"}
            with self.assertRaisesRegex(Rejected, "write_request_refused"):
                lookup(policy, "synthetic-open-v1", write, 0, ["id"])
    def test_secrets_from_env_fill_the_payload_after_admission(self):
        from transcripts.cli import secrets_from_env
        body = {key: value for key, value in payload().items() if key != "inferenceKey"}
        body["credential"] = {"origin": ORIGIN, "kind": "headers"}
        with patch.dict("os.environ", {"PEERLINK_BANK_CREDENTIAL": json.dumps({"Cookie": SESSION}),
                                       "PEERLINK_INFERENCE_KEY": INFERENCE}):
            secrets_from_env(body)
        self.assertEqual(body["credential"]["value"], {"Cookie": SESSION})
        self.assertEqual(body["inferenceKey"], INFERENCE)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(Rejected, "secrets_env_missing"):
                secrets_from_env({key: value for key, value in payload().items() if key != "inferenceKey"} |
                                 {"credential": {"origin": ORIGIN, "kind": "bearer"}})
    def test_campaigns_command_lists_open_campaign_terms(self):
        from transcripts.cli import campaign_summary, terms
        card = campaign_summary(campaign())
        self.assertEqual((card["kind"], card["domains"], card["maxBankReads"]), ("open_recipe", [ORIGIN], 4))
        release = {"status": "approved", "expiresAt": 2**40}
        shown = terms(release, {"campaigns": [campaign()]}, "synthetic-open-v1", "openai_compatible", "any/model-1")
        self.assertEqual((shown["kind"], shown["model"]), ("open_recipe", "any/model-1"))
        self.assertEqual(shown["inferenceInput"], "contributor_notes_and_value_free_transcript")
    def test_campaign_domain_admits_its_subdomains_only(self):
        from transcripts.open_source import origin_in_domain
        policy = campaign()
        sub = recipe()
        sub["reads"] = [{"url": "https://api.bank.example/v1/me"}, {"url": "https://api.bank.example/v1/activity"}]
        validate_open_recipe(policy, sub, 4)
        mixed = recipe()
        mixed["reads"][1]["url"] = "https://api.bank.example/v1/activity"
        with self.assertRaisesRegex(Rejected, "recipe_invalid"):
            validate_open_recipe(policy, mixed, 4)
        for origin in ("https://evilbank.example", "https://bank.example.evil.test", "https://example",
                       "http://bank.example", "https://BANK.example", "https://bank.example:443"):
            self.assertFalse(origin_in_domain(origin, ORIGIN))
        with self.assertRaisesRegex(Rejected, "invalid_credential"):
            OpenBankClient(policy, {"origin": "https://evilbank.example", "kind": "bearer", "value": "x"}, Bank())
        body = payload()
        body["recipe"] = sub
        with self.assertRaisesRegex(Rejected, "invalid_credential"):
            acquired(body=body)  # credential origin differs from the recipe host


if __name__ == "__main__":
    unittest.main()
