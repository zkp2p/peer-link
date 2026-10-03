"""Manually admitted enclave entrypoint; sessions fail closed until released.

No network on import. No shell execution, dynamic imports, or contributor adapter loading.
The checked-in policy disables acquisition. Receipts grant no payment authority.
"""
import socket
import struct
import time
import hashlib
import resource
from pathlib import Path

from .attestation import freshness_nonce, policy_digest
from .channel import SessionChannel
from .common import Rejected, b64, canonical, digest, fields, require, strict_json, unb64
from .nsm import attest
from .pipeline import acquire_and_compare
from .permits import verify as verify_permit
from .receipts import sign as sign_receipt
from .sandbox import MAX_MODULE
from .mercury_oracle import CAPABILITY

HERE = Path(__file__).parent


def receive(stream, maximum=32768):
    deadline = time.monotonic() + 5
    def exact(length):
        parts = bytearray()
        while len(parts) < length:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "frame_timeout")
            stream.settimeout(remaining)
            piece = stream.recv(length - len(parts))
            require(bool(piece), "truncated_frame")
            parts.extend(piece)
        return bytes(parts)
    size = struct.unpack("!I", exact(4))[0]
    require(0 < size <= maximum, "frame_size")
    return strict_json(exact(size), maximum)


def send(stream, value):
    body = canonical(value)
    require(len(body) <= 65536, "response_size")
    stream.sendall(struct.pack("!I", len(body)) + body)


class Runtime:
    def __init__(self):
        self.channel = SessionChannel()
        policy = strict_json((HERE / "policies/service.json").read_bytes())
        source = strict_json((HERE / "policies/mercury.json").read_bytes())
        model = strict_json((HERE / "policies/model-trust.json").read_bytes())
        operator = strict_json((HERE / "policies/operator-trust.json").read_bytes())
        self.operator = operator
        self.service = policy
        self.source = source
        self.model = model
        prompt = (HERE / "prompts/payment-review-v1.txt").read_text()
        self.policy_digest = policy_digest(policy, prompt, source, model, operator)
        self.window = time.monotonic()
        self.calls = 0

    def execute(self, request):
        """Only an operator-admitted artifact can consume an owner-encrypted session.

        All authority comes from measured policy and signed one-use permissions.
        The sole public output is a fixed-schema receipt. Private evidence, guest
        strings and field hashes never cross the enclave boundary.
        """
        require(self.service.get("manualVerification") is True and
                self.service.get("mode") == "manual", "live_verification_unavailable")
        require(self.operator.get("enabled") is True, "operator_not_approved")
        require(self.model.get("enabled") is False, "external_model_forbidden")
        fields(request, ("operation", "module", "envelope", "permit", "binding"))
        binding = request["binding"]
        fields(binding, ("revision", "release", "policy", "prompt"))
        from .common import hex_digest
        for value in binding.values():
            hex_digest(value)
        module = unb64(request["module"], MAX_MODULE)
        require(hashlib.sha256(module).hexdigest() == binding["revision"] and
                binding["policy"] == self.policy_digest, "execution_binding")
        envelope = request["envelope"]
        fields(envelope, ("context", "wrappedKey", "nonce", "ciphertext"))
        context = envelope["context"]
        require(isinstance(context, dict) and context.get("bindingDigest") == digest(binding),
                "execution_binding")
        key = unb64(self.operator.get("permitPublicKey"), 32)
        result = acquire_and_compare(self.channel, module, envelope, request["permit"],
            operator_public_key=key, policy_digest=self.policy_digest, source_policy=self.source)
        # Revalidate after bounded acquisition/guest execution; no late success.
        claims = verify_permit(request["permit"], key,
            enclave_key_digest=hashlib.sha256(self.channel.public_key_der).hexdigest(),
            policy_digest=self.policy_digest, artifact_digest=binding["revision"],
            challenge=context["nonce"])
        outcome = result["outcome"]
        require(outcome in ("consistent", "contradicted", "needs_review"), "pipeline_result")
        if outcome == "consistent":
            require(result.get("sourceAuthenticated") is True, "source_not_authenticated")
        now = int(time.time())
        receipt = sign_receipt({"audience": "peer-link-contribution-verification-v1",
            "attempt": claims["attempt"], "ticket": claims["ticket"],
            "bindingDigest": digest(binding), "capability": CAPABILITY,
            "result": "verified" if outcome == "consistent" else outcome,
            "issuedAt": now, "expiresAt": now + 300}, self.channel.key)
        # Do not add result, facts, exception messages, model output or guest output here.
        return {"receipt": receipt, "quote": self.quote(bytes.fromhex(digest(receipt)))}

    def quote(self, nonce):
        if time.monotonic() - self.window > 60:
            self.window, self.calls = time.monotonic(), 0
        require(self.calls < 10, "rate_limited")
        self.calls += 1
        require(isinstance(nonce, bytes) and len(nonce) == 32, "nonce_size")
        document = attest(nonce, self.channel.public_key_der, bytes.fromhex(self.policy_digest))
        return {"attestation": b64(document), "publicKey": b64(self.channel.public_key_der),
                "policyDigest": self.policy_digest}

    def handle(self, request):
        require(isinstance(request, dict), "invalid_request")
        if request.get("operation") == "status":
            fields(request, ("operation",))
            enabled = (self.service.get("mode") == "manual" and
                       self.service.get("manualVerification") is True and
                       self.operator.get("enabled") is True and
                       self.source.get("enabled") is True and
                       self.source.get("status") == "approved" and
                       self.model.get("enabled") is False)
            return {"schemaVersion": "1", "mode": "manual" if enabled else "pilot", "liveVerification": enabled,
                    "policyDigest": self.policy_digest, "scheduledJudgment": False}
        if request.get("operation") == "attest":
            fields(request, ("operation", "nonce"))
            return self.quote(freshness_nonce(unb64(request["nonce"], 32)))
        if request.get("operation") == "attest_challenge":
            fields(request, ("operation", "context"))
            require(self.operator.get("enabled") is True, "operator_not_approved")
            context = self.channel.active_context(request["context"])
            return self.quote(bytes.fromhex(digest(context)))
        if request.get("operation") == "execute":
            return self.execute(request)
        if request.get("operation") == "challenge":
            fields(request, ("operation", "grant"))
            require(self.operator.get("enabled") is True, "operator_not_approved")
            # The sole trust key comes from the measured image, never this request.
            key = unb64(self.operator.get("permitPublicKey"), 32)
            require(len(key) == 32, "invalid_operator_key")
            context = self.channel.challenge_authorized(request["grant"],
                operator_public_key=key, policy_digest=self.policy_digest)
            return {"context": context, "quote": self.quote(bytes.fromhex(digest(context)))}
        # No dormant 'debug', echo, arbitrary fetch, prompt or decrypt route.
        raise Rejected("live_verification_unavailable")


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    runtime = Runtime()
    listener = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    listener.bind((socket.VMADDR_CID_ANY, 5000))
    listener.listen(8)
    while True:
        stream, _ = listener.accept()
        with stream:
            stream.settimeout(5)
            try:
                result = runtime.handle(receive(stream, 3 * 1024 * 1024))
            except Rejected as error:
                result = {"error": str(error)}
            except Exception:
                result = {"error": "request_failed"}
            try:
                send(stream, result)
            except OSError:
                pass


if __name__ == "__main__":
    main()
