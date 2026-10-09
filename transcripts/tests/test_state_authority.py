"""Credential-free authority safety tests with an atomic synthetic DynamoDB."""
import base64
import copy
import hashlib
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from transcripts.infra.state_authority import Authority, MAX_CIPHERTEXT
from transcripts.infra.state_template import template

NAMESPACE = "synthetic-public-state"


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class AtomicTable:
    def __init__(self):
        self.item = None
        self.lock = threading.Lock()
        self.reads, self.writes = [], []

    def get_item(self, **args):
        with self.lock:
            self.reads.append(args)
            return {} if self.item is None else {"Item": copy.deepcopy(self.item)}

    def update_item(self, **args):
        with self.lock:
            self.writes.append(args)
            values = args["ExpressionAttributeValues"]
            if "attribute_not_exists" in args["ConditionExpression"]:
                ok = self.item is None
            else:
                ok = self.item is not None and all(self.item[field] == values[value] for field, value in
                    [("revision", ":oldRevision"), ("writerGeneration", ":oldGeneration"), ("ciphertextDigest", ":oldDigest"), ("writeCommitment", ":oldCommitment")])
            if not ok:
                raise ConditionalFailure()
            item = copy.deepcopy(self.item or args["Key"])
            for field, value in [("revision", ":revision"), ("writerGeneration", ":generation"),
                                 ("ciphertextDigest", ":digest"), ("ciphertext", ":cipher"), ("lastOpId", ":op"), ("writeCommitment", ":commitment")]:
                item[field] = copy.deepcopy(values[value])
            if ":wrapped" in values:
                item["wrappedMaster"] = copy.deepcopy(values[":wrapped"])
            self.item = item
            return {"Attributes": copy.deepcopy(item)}


def request(action="create", payload=b"synthetic encrypted snapshot bytes"):
    result = {"version": 1, "action": action, "nonce": "a" * 64, "namespace": NAMESPACE}
    if action == "load":
        return result
    result.update({"opId": "b" * 32, "revision": 0, "writerGeneration": 1,
                   "ciphertextDigest": hashlib.sha256(payload).hexdigest(),
                   "ciphertext": base64.b64encode(payload).decode(),
                   "writeCommitment": hashlib.sha256(bytes.fromhex(("11" if action == "create" else "22") * 32)).hexdigest()})
    if action == "create":
        result["wrappedMaster"] = base64.b64encode(b"synthetic KMS wrapped master").decode()
    else:
        result.update({"expectedRevision": 0, "expectedWriterGeneration": 1,
                       "expectedCiphertextDigest": request()["ciphertextDigest"], "revision": 1, "opId": "c" * 32, "writeCapability": "11" * 32})
    return result


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.table = AtomicTable()
        self.authority = Authority(self.table, "synthetic-table", NAMESPACE)

    def create(self):
        result = self.authority.invoke(request())
        self.assertNotIn("error", result)
        return result

    def test_create_load_and_commit_are_strongly_read_and_keep_master(self):
        self.assertIsNone(self.authority.invoke(request("load"))["head"])
        initial = self.create()
        result = self.authority.invoke(request("commit", b"next synthetic encrypted snapshot"))
        self.assertEqual(result["head"]["revision"], 1)
        self.assertEqual(result["head"]["wrappedMaster"], initial["head"]["wrappedMaster"])
        self.assertEqual(self.authority.invoke(request("load"))["head"], result["head"])
        self.assertTrue(all(read["ConsistentRead"] is True for read in self.table.reads))
        self.assertNotIn("#wrapped", self.table.writes[-1]["ExpressionAttributeNames"])

    def test_lost_ack_retry_echoes_fresh_nonce_and_exact_identity(self):
        self.create()
        commit = request("commit")
        first = self.authority.invoke(commit)
        retry = {**commit, "nonce": "d" * 64}
        result = self.authority.invoke(retry)
        self.assertEqual(result["head"], first["head"])
        self.assertEqual(result["nonce"], retry["nonce"])
        changed = {**retry, "opId": "e" * 32}
        self.assertEqual(self.authority.invoke(changed), {"version": 1, "nonce": retry["nonce"], "error": "state_conflict"})

    def test_create_is_idempotent_but_never_overwrites_another_master(self):
        self.create()
        self.assertNotIn("error", self.authority.invoke(request()))
        changed = {**request(), "wrappedMaster": base64.b64encode(b"different synthetic master").decode()}
        self.assertEqual(self.authority.invoke(changed)["error"], "state_conflict")

    def test_writer_takeover_fences_stale_commit(self):
        self.create()
        takeover = {**request("commit"), "writerGeneration": 2}
        head = self.authority.invoke(takeover)["head"]
        stale = {**request("commit"), "revision": 2, "expectedRevision": 1, "opId": "f" * 32,
                 "expectedCiphertextDigest": head["ciphertextDigest"]}
        self.assertEqual(self.authority.invoke(stale)["error"], "state_conflict")
        fresh = {**stale, "expectedWriterGeneration": 2, "writerGeneration": 2, "writeCapability": "22" * 32,
                 "writeCommitment": hashlib.sha256(bytes.fromhex("33" * 32)).hexdigest()}
        self.assertNotIn("error", self.authority.invoke(fresh))

    def test_host_cannot_overwrite_head_without_enclave_capability(self):
        self.create()
        before = copy.deepcopy(self.table.item)
        forged = {**request("commit"), "writeCapability": "ff" * 32}
        self.assertEqual(self.authority.invoke(forged)["error"], "state_conflict")
        self.assertEqual(self.table.item, before)
        self.assertNotIn("writeCapability", self.authority.invoke(request("load"))["head"])
        for call in self.table.writes:
            self.assertNotIn("writeCapability", repr(call))
            self.assertNotIn("ff" * 32, repr(call))

    def test_racing_writers_cannot_both_advance_revision(self):
        self.create()
        requests = [{**request("commit"), "opId": f"{n:032x}"} for n in range(12)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(self.authority.invoke, requests))
        self.assertEqual(sum("head" in r for r in results), 1)
        self.assertEqual(sum(r.get("error") == "state_conflict" for r in results), 11)

    def test_strict_bounds_and_unknown_fields_reject_before_writes(self):
        cases = [{**request(), "version": True}, {**request(), "namespace": "another-namespace"},
                 {**request(), "revision": True}, {**request(), "writerGeneration": 0},
                 {**request(), "opId": "b" * 64}, {**request(), "ciphertextDigest": "0" * 64},
                 {**request(), "ciphertext": "!!!!"}, {**request(), "extra": "rejected"},
                 request(payload=b"x" * (MAX_CIPHERTEXT + 1)),
                 {**request("commit"), "writerGeneration": 3},
                 {**request("commit"), "revision": 0},
                 {**request("commit"), "wrappedMaster": "not-allowed"}]
        for value in cases:
            with self.subTest(value=list(value)):
                self.assertEqual(self.authority.invoke(value)["error"], "state_invalid")
        self.assertEqual(self.table.writes, [])

    def test_corrupt_current_item_fails_closed_without_exception_details(self):
        self.create()
        self.table.item["ciphertextDigest"] = {"S": "0" * 64}
        result = self.authority.invoke(request("load"))
        self.assertEqual(result, {"version": 1, "nonce": "a" * 64, "error": "state_unavailable"})

    def test_dynamodb_error_never_leaks_response_or_credentials(self):
        class Broken:
            def get_item(self, **_args):
                raise RuntimeError("synthetic private payload that must not escape")
        response = Authority(Broken(), "table", NAMESPACE).invoke(request("load"))
        self.assertEqual(response, {"version": 1, "nonce": "a" * 64, "error": "state_unavailable"})

    def test_template_retains_resources_and_pins_separate_crypto(self):
        value = template(); resources = value["Resources"]
        self.assertNotIn("Host", resources)
        for resource in ["StateTable", "StateKey", "AuthorityVersion"]:
            self.assertEqual(resources[resource]["DeletionPolicy"], "Retain")
        self.assertTrue(resources["StateTable"]["Properties"]["DeletionProtectionEnabled"])
        self.assertTrue(resources["StateTable"]["Properties"]["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"])
        self.assertEqual(value["Parameters"]["ApprovedImageSha384"]["Default"], "")
        grant = resources["StateKey"]["Properties"]["KeyPolicy"]["Statement"][1]["Fn::If"][1]
        self.assertEqual(grant["Action"], ["kms:GenerateDataKey", "kms:Decrypt"])
        self.assertIn("kms:RecipientAttestation:ImageSha384", grant["Condition"]["StringEqualsIgnoreCase"])
        self.assertIn("kms:RecipientAttestation:PCR3", grant["Condition"]["StringEqualsIgnoreCase"])
        policy = resources["AuthorityRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        self.assertEqual(policy[0]["Action"], ["dynamodb:GetItem", "dynamodb:UpdateItem"])

    def test_authority_env_decrypt_exception_cannot_decrypt_state_master(self):
        value = template()
        policy = value["Resources"]["AuthorityRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        self.assertEqual(policy[1]["NotAction"]["Fn::If"][1],
                         ["dynamodb:GetItem", "dynamodb:UpdateItem", "kms:Decrypt"])
        grant, deny, wrong_context = [statement["Fn::If"][1] for statement in policy[3:]]
        self.assertEqual(grant["Action"], "kms:Decrypt")
        self.assertEqual(grant["Resource"], {"Ref": "LambdaEnvironmentKeyArn"})
        self.assertEqual(deny["Effect"], "Deny")
        self.assertEqual(deny["NotResource"], {"Ref": "LambdaEnvironmentKeyArn"})
        self.assertEqual(wrong_context["Effect"], "Deny")
        self.assertIn("kms:EncryptionContext:aws:lambda:FunctionArn", wrong_context["Condition"]["StringNotEquals"])
        self.assertEqual(value["Parameters"]["LambdaEnvironmentKeyArn"]["Default"], "")


if __name__ == "__main__":
    unittest.main()
