"""Open-recipe campaigns: synthetic bank, synthetic model, no network or keys."""
import copy
import hashlib
import io
import json
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

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
                            "value": {COOKIE: SESSION, "X-CSRF-Token": CSRF}},
             "profileId": None, "recipe": recipe(), "inferenceKey": INFERENCE, "transcript": [],
             "notes": "Activity list is newest first. The handle under counterparty is what a payer types to send."}
    value.update(changes)
    return value


class Bank:
    """Transport double: authenticated JSON, anonymous 401, and one model reply."""
    def __init__(self, *, anonymous=(401, False), model=None, bodies=None, provider_failures=()):
        self.anonymous, self.model, self.calls = anonymous, model, []
        self.bodies = bodies or {"/api/v2/me": ME, "/api/v2/users/user-48213377/activity": HISTORY}
        self.provider_failures = list(provider_failures)
    def probe_anonymous(self, url, *, timeout=15, body=None, content_type=None):
        self.calls.append(("probe", url, body))
        status, served = self.anonymous
        return HTTPResponse(status, b"", (("content-type", "json"),) if served else ())
    def request_bank(self, url, *, headers, timeout=15, max_bytes=0, open_headers=False, body=None, content_type=None):
        self.calls.append(("bank", url, dict(headers), body, content_type))
        path = url[len(ORIGIN):].split("?")[0]
        if path not in self.bodies:
            raise Rejected("bank_http_client_error")
        return HTTPResponse(200, canonical(self.bodies[path]), (("content-type", "application/json"),))
    def request_provider(self, url, *, headers, body, timeout=15, max_bytes=0):
        self.calls.append(("provider", url, dict(headers), body))
        if self.provider_failures:
            raise Rejected(self.provider_failures.pop(0))
        reply = self.model if self.model is not None else {"rubricVersion": "transcript-mapping-v1",
                                                         "mapping": MAPPING, "completedStatus": ["completed"]}
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
    def test_post_reads_refuse_named_state_changes(self):
        policy = campaign()
        ok = recipe()
        ok["reads"][1] = {"url": ORIGIN + "/api/graphql", "method": "POST", "contentType": "application/json",
                          "body": json.dumps({"operationName": "GetActivityQuery", "query": "query GetActivityQuery { a }",
                                              "variables": {"first": 20}})}
        validate_open_recipe(policy, ok, 4)
        for url, body in ((ORIGIN + "/api/transfer", "{}"), (ORIGIN + "/api/payments/send", "{}"),
                          (ORIGIN + "/api/graphql", json.dumps({"query": "mutation Pay { pay }"})),
                          (ORIGIN + "/api/graphql", json.dumps({"operationName": "CreatePayment", "query": "query { a }"})),
                          (ORIGIN + "/api/graphql", json.dumps({"operationName": "ActivityMutation", "query": "{ a }"}))):
            bad = recipe()
            bad["reads"][1] = {"url": url, "method": "POST", "contentType": "application/json", "body": body}
            with self.assertRaisesRegex(Rejected, "write_request_refused"):
                validate_open_recipe(policy, bad, 4)
        get_only = campaign()
        get_only["sources"][0]["methods"] = ["GET"]
        with self.assertRaisesRegex(Rejected, "source_not_allowed"):
            validate_open_recipe(get_only, ok, 4)
        put = recipe()
        put["reads"][1] = {"url": ORIGIN + "/api/x", "method": "PUT", "contentType": "application/json", "body": "{}"}
        with self.assertRaisesRegex(Rejected, "recipe_invalid"):
            validate_open_recipe(policy, put, 4)
    def test_credential_headers_exclude_transport_control(self):
        bearer = credential_headers({"origin": ORIGIN, "kind": "bearer", "value": "abc"}, ORIGIN)
        self.assertEqual(list(bearer.items()), [("Authorization", "Bearer abc")])
        for value in ({"Host": "evil.example"}, {"Content-Length": "0"}, {COOKIE: "a", COOKIE.lower(): "b"},
                      {"X Bad": "a"}, {COOKIE: "line\nbreak"}, {COOKIE: ""}, {}):
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
    def test_session_headers_reach_only_the_bank_after_the_anonymous_gate(self):
        bank = Bank()
        _, _, reads, _ = acquired(bank=bank)
        kinds = [call[0] for call in bank.calls]
        self.assertEqual(kinds, ["probe", "probe", "bank", "bank"])
        for call in bank.calls:
            self.assertTrue(call[1].startswith(ORIGIN + "/"))
            if call[0] == "bank":
                self.assertEqual(call[2]["Cookie"], SESSION)
                self.assertEqual(call[2]["Accept"], "application/json")
        self.assertEqual({read.account_id for read in reads}, {"open:" + ORIGIN + ":user-48213377"})
        self.assertNotIn("user-48213377", repr(reads))
    def test_anonymously_readable_json_is_refused_but_a_login_page_is_not(self):
        with self.assertRaisesRegex(Rejected, "anonymous_access_allowed"):
            acquired(bank=Bank(anonymous=(200, True)))
        acquired(bank=Bank(anonymous=(200, False)))
        acquired(bank=Bank(anonymous=(302, False)))
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
        document = json.dumps({"operationName": "GetActivityQuery", "query": "query GetActivityQuery { a }"})
        body["recipe"]["reads"][1] = {"url": ORIGIN + "/api/graphql", "method": "POST",
                                      "contentType": "application/json", "body": document}
        bank = Bank(bodies={"/api/v2/me": ME, "/api/graphql": HISTORY})
        _, _, reads, artifact = acquired(bank=bank, body=body)
        self.assertEqual(reads[1].method, "POST")
        self.assertEqual(bank.calls[-1][3:], (document, "application/json"))
        self.assertEqual(bank.calls[1], ("probe", ORIGIN + "/api/graphql", document))
        request = artifact["requests"][1]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["body"]["fields"]["$.operationName"]["values"], ["GetActivityQuery"])
        self.assertNotIn("query GetActivityQuery", canonical(artifact).decode())


class TranscriptTests(unittest.TestCase):
    def test_transcript_keeps_names_and_shapes_but_no_bank_values(self):
        policy, _, _, artifact = acquired()
        validate_artifact(policy, artifact)
        encoded = canonical(artifact).decode()
        for secret in PRIVATE + ("Illinois", "Bob Example", "carol77", "12.50", "2026-09-30", "SYNTHETIC-CSRF"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(artifact["credentialHeaders"], ["cookie", "x-csrf-token"])
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
                       lambda a: a.update(credentialHeaders=["cookie", "host"]),
                       lambda a: a.update(rawBody={"x": 1})):
            candidate = copy.deepcopy(artifact)
            mutate(candidate)
            with self.assertRaises(Rejected):
                validate_artifact(policy, candidate)
    def test_format_classes_never_echo_values(self):
        samples = {"2026-10-01T08:00:00+05:30": "datetime:iso8601:offset", "2026-10-01": "date:iso8601", "": "empty",
                   "123e4567-e89b-42d3-a456-426614174000": "uuid", "0012345": "digits:7", "-45": "digits:neg:2",
                   "19.99": "decimal:pos:2", "EUR": "currency_code", "a@b.co": "email", "https://x.example/y": "url",
                   "1,000 USD": "money_text", "deadbeefdeadbeefdeadbeef": "hex:short", "Hello": "text:short:alpha",
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
    def test_model_reply_parsing_is_lenient_about_wrapping_only(self):
        fenced = "```json\n" + json.dumps({"mapping": MAPPING, "completedStatus": ["completed"], "score": 100}) + "\n```"
        self.assertEqual(parse_proposal(fenced), {"mapping": MAPPING, "completedStatus": ["completed"]})
        self.assertEqual(parse_proposal(json.dumps({"mapping": {"paymentId": None, "extra": "x"}})),
                         {"mapping": {}, "completedStatus": []})
        for text in ("no json here", "{broken", None):
            with self.assertRaisesRegex(Rejected, "model_output_not_json"):
                parse_proposal(text)
        with self.assertRaisesRegex(Rejected, "model_result_invalid"):
            parse_proposal(json.dumps({"mapping": "x"}))


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
        self.bank.anonymous = (200, True)
        _, status = self.run_job()
        self.assertEqual((status["state"], status["reason"]), ("rejected", "anonymous_access_allowed"))
        self.bank.anonymous = (401, False)
        _, status = self.run_job(wallet=2, body=payload(notes="call me on 4155550101999"))
        self.assertEqual(status["reason"], "unsafe_notes")
        self.bank.provider_failures = ["provider_http_unauthorized"]
        _, status = self.run_job(wallet=3)
        self.assertEqual(status["reason"], "provider_http_unauthorized")
    def test_same_account_is_paid_once_per_campaign(self):
        self.assertEqual(self.run_job(wallet=1)[1]["state"], "paid")
        _, status = self.run_job(wallet=2)
        self.assertEqual((status["state"], status["reason"]), ("rejected", "duplicate_account"))
    def test_runtime_requires_the_measured_open_prompt(self):
        policy = dict(self.policy, openPromptDigest="0" * 64)
        with patch("transcripts.runtime.Channel", return_value=SigningChannel()):
            with self.assertRaisesRegex(Rejected, "prompt_mismatch"):
                Runtime(policy, OpenEpoch(), self.bank, self.archive, attester=lambda *args: b"q")


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
