"""Opaque monotonic state authority, published as an immutable Lambda version.

Only this Lambda role may update its DynamoDB item. It cannot decrypt state.
Callers authenticate AWS TLS inside the enclave; the parent has Invoke only.
No request bodies, ciphertext, credentials or exceptions are logged here.
"""
import base64
import hashlib
import os
import re

MAX_CIPHERTEXT = 327_680
MAX_WRAPPED_MASTER = 6_144
MAX_REVISION = 2**63 - 1
COMMON = {"version", "action", "nonce", "namespace"}
HEAD = {"revision", "ciphertextDigest", "ciphertext", "wrappedMaster", "lastOpId", "writerGeneration", "writeCommitment"}
CREATE = COMMON | {"revision", "ciphertextDigest", "ciphertext", "wrappedMaster", "opId", "writerGeneration", "writeCommitment"}
COMMIT = COMMON | {"expectedRevision", "expectedCiphertextDigest", "expectedWriterGeneration",
                   "revision", "ciphertextDigest", "ciphertext", "opId", "writerGeneration", "writeCapability", "writeCommitment"}
_client = None


class StateRejected(Exception):
    pass


def require(ok, code="state_invalid"):
    if not ok:
        raise StateRejected(code)


def number(value, minimum=0):
    require(type(value) is int and minimum <= value <= MAX_REVISION)
    return value


def hex64(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None)
    return value


def op32(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{32}", value) is not None)
    return value


def blob(value, limit, minimum=1):
    require(isinstance(value, str) and len(value) <= 4 * ((limit + 2) // 3))
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        raise StateRejected("state_invalid") from None
    require(minimum <= len(raw) <= limit and base64.b64encode(raw).decode() == value)
    return raw


def decode_head(item, namespace):
    require(isinstance(item, dict) and set(item) == HEAD | {"namespace"}, "state_unavailable")
    require(item["namespace"] == {"S": namespace}, "state_unavailable")
    try:
        result = {name: item[name]["S"] for name in ["ciphertextDigest", "lastOpId", "writeCommitment"]}
        for name in ["revision", "writerGeneration"]:
            require(set(item[name]) == {"N"}, "state_unavailable")
            result[name] = int(item[name]["N"])
        for name in ["ciphertext", "wrappedMaster"]:
            require(set(item[name]) == {"B"}, "state_unavailable")
            raw = bytes(item[name]["B"])
            result[name] = base64.b64encode(raw).decode()
        for name in ["ciphertextDigest", "lastOpId", "writeCommitment"]:
            require(set(item[name]) == {"S"}, "state_unavailable")
        number(result["revision"]); number(result["writerGeneration"], 1)
        op32(result["lastOpId"]); hex64(result["ciphertextDigest"])
        hex64(result["writeCommitment"])
        ciphertext = blob(result["ciphertext"], MAX_CIPHERTEXT, 29)
        blob(result["wrappedMaster"], MAX_WRAPPED_MASTER)
        require(hashlib.sha256(ciphertext).hexdigest() == result["ciphertextDigest"], "state_unavailable")
        return result
    except Exception:
        raise StateRejected("state_unavailable") from None


class Authority:
    def __init__(self, client, table, namespace):
        require(isinstance(namespace, str) and re.fullmatch("[a-z0-9][a-z0-9-]{0,63}", namespace) is not None)
        self.client, self.table, self.namespace = client, table, namespace

    def load(self):
        result = self.client.get_item(TableName=self.table, Key={"namespace": {"S": self.namespace}},
                                      ConsistentRead=True)
        item = result.get("Item")
        return None if item is None else decode_head(item, self.namespace)

    def invoke(self, request):
        nonce = request.get("nonce") if isinstance(request, dict) else None
        response = {"version": 1, "nonce": nonce, "namespace": self.namespace}
        try:
            require(isinstance(request, dict) and type(request.get("version")) is int and request["version"] == 1)
            hex64(nonce)
            require(request.get("namespace") == self.namespace)
            action = request.get("action")
            if action == "load":
                require(set(request) == COMMON)
                return {**response, "head": self.load()}
            require(action in {"create", "commit"})
            require(set(request) == (CREATE if action == "create" else COMMIT))
            revision = number(request["revision"])
            generation = number(request["writerGeneration"], 1)
            operation = op32(request["opId"])
            commitment = hex64(request["writeCommitment"])
            ciphertext = blob(request["ciphertext"], MAX_CIPHERTEXT, 29)
            cipher_digest = hex64(request["ciphertextDigest"])
            require(hashlib.sha256(ciphertext).hexdigest() == cipher_digest)
            values = {":revision": {"N": str(revision)}, ":generation": {"N": str(generation)},
                      ":digest": {"S": cipher_digest}, ":cipher": {"B": ciphertext}, ":op": {"S": operation},
                      ":commitment": {"S": commitment}}
            names = {"#revision": "revision", "#generation": "writerGeneration", "#digest": "ciphertextDigest",
                     "#cipher": "ciphertext", "#op": "lastOpId", "#commitment": "writeCommitment"}
            update = "SET #revision=:revision, #generation=:generation, #digest=:digest, #cipher=:cipher, #op=:op, #commitment=:commitment"
            if action == "create":
                require(revision == 0 and generation == 1)
                wrapped = blob(request["wrappedMaster"], MAX_WRAPPED_MASTER)
                values[":wrapped"] = {"B": wrapped}
                names.update({"#wrapped": "wrappedMaster", "#namespace": "namespace"})
                update += ", #wrapped=:wrapped"
                condition = "attribute_not_exists(#namespace)"
            else:
                old_revision = number(request["expectedRevision"])
                old_generation = number(request["expectedWriterGeneration"], 1)
                old_digest = hex64(request["expectedCiphertextDigest"])
                # Only the enclave learns this preimage through its own TLS.
                # Store/hash it before DynamoDB: no capability in DDB data logs.
                capability = bytes.fromhex(hex64(request["writeCapability"]))
                old_commitment = hashlib.sha256(capability).hexdigest()
                require(revision == old_revision + 1 and generation in {old_generation, old_generation + 1})
                values.update({":oldRevision": {"N": str(old_revision)}, ":oldGeneration": {"N": str(old_generation)},
                               ":oldDigest": {"S": old_digest}, ":oldCommitment": {"S": old_commitment}})
                condition = "#revision=:oldRevision AND #generation=:oldGeneration AND #digest=:oldDigest AND #commitment=:oldCommitment"
            try:
                result = self.client.update_item(TableName=self.table, Key={"namespace": {"S": self.namespace}},
                    UpdateExpression=update, ConditionExpression=condition, ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values, ReturnValues="ALL_NEW")
                head = decode_head(result["Attributes"], self.namespace)
            except Exception as error:
                if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise
                # Resolve lost acknowledgments without allocating a fresh signature
                # or transaction. The ten-minute DynamoDB token is not our authority.
                head = self.load()
                require(head is not None and head["revision"] == revision and head["writerGeneration"] == generation
                        and head["lastOpId"] == operation and head["ciphertextDigest"] == cipher_digest
                        and head["ciphertext"] == request["ciphertext"] and head["writeCommitment"] == commitment, "state_conflict")
                if action == "create":
                    require(head["wrappedMaster"] == request["wrappedMaster"], "state_conflict")
            return {**response, "head": head}
        except StateRejected as error:
            return {"version": 1, "nonce": nonce, "error": str(error)}
        except Exception:
            return {"version": 1, "nonce": nonce, "error": "state_unavailable"}


def handler(event, _context):
    global _client
    try:
        if _client is None:
            import boto3
            _client = boto3.client("dynamodb", region_name=os.environ["AWS_REGION"])
        return Authority(_client, os.environ["TABLE_NAME"], os.environ["STATE_NAMESPACE"]).invoke(event)
    except Exception:
        # No AWS error body, private payload or credentials cross this boundary.
        return {"version": 1, "nonce": event.get("nonce") if isinstance(event, dict) else None,
                "error": "state_unavailable"}
