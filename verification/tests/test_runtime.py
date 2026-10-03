import hashlib
import time
import socket
import struct
import unittest
from unittest.mock import Mock, patch

from verification.acquisition import ReadDeadline
from verification.attestation import freshness_nonce, policy_digest
from verification.channel import encrypt_session
from verification.common import Rejected, b64, digest, strict_json
from verification.admission import issue
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from verification.readiness import inspect
from verification.runtime import Runtime, receive


class RuntimeTests(unittest.TestCase):
    def test_runtime_never_accepts_live_secrets_or_arbitrary_operations(self):
        runtime = Runtime()
        self.assertFalse(runtime.handle({"operation": "status"})["liveVerification"])
        for operation in ("verify", "decrypt", "fetch", "debug", "prompt", "payout"):
            with self.subTest(operation=operation), self.assertRaises(Rejected):
                runtime.handle({"operation": operation})

    def test_challenge_requires_measured_operator_and_valid_grant_before_quote(self):
        runtime = Runtime()
        with patch("verification.runtime.attest") as attest:
            with self.assertRaisesRegex(Rejected, "operator_not_approved"):
                runtime.handle({"operation": "challenge", "grant": {}})
            signer = Ed25519PrivateKey.generate()
            runtime.operator = {"enabled": True, "permitPublicKey": b64(signer.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw))}
            grant = issue({"audience": "peer-link-challenge-v1", "attempt": "attempt-1",
                "bindingDigest": "a" * 64, "policyDigest": runtime.policy_digest,
                "enclaveKeyDigest": hashlib.sha256(runtime.channel.public_key_der).hexdigest(),
                "expiresAt": int(time.time()) + 60}, Ed25519PrivateKey.generate())
            with self.assertRaisesRegex(Rejected, "invalid_admission_signature"):
                runtime.handle({"operation": "challenge", "grant": grant})
            with self.assertRaises(Rejected):
                runtime.handle({"operation": "challenge", "grant": grant, "operatorPublicKey": "attacker"})
            attest.assert_not_called()
        self.assertEqual(runtime.channel.challenges, {})
        self.assertEqual(runtime.channel.admissions, {})

    def test_policy_digest_includes_all_trust_and_prompt_inputs(self):
        args = [{"service": 1}, "public task", {"bank": 1}, {"model": 1}, {"operator": 1}]
        original = policy_digest(*args)
        for index in range(5):
            changed = args.copy()
            changed[index] = "different"
            self.assertNotEqual(original, policy_digest(*changed))

    def test_generic_probe_cannot_quote_an_issued_context_hash(self):
        runtime = Runtime()
        signer = Ed25519PrivateKey.generate()
        runtime.operator = {"enabled": True, "permitPublicKey": b64(signer.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw))}
        grant = issue({"audience": "peer-link-challenge-v1", "attempt": "attempt-1",
            "bindingDigest": "a" * 64, "policyDigest": runtime.policy_digest,
            "enclaveKeyDigest": hashlib.sha256(runtime.channel.public_key_der).hexdigest(),
            "expiresAt": int(time.time()) + 60}, signer)
        with patch('verification.runtime.attest', return_value=b'synthetic-document') as nsm:
            setup = runtime.handle({'operation': 'challenge', 'grant': grant})
            context = setup['context']
            context_nonce = bytes.fromhex(digest(context))
            self.assertEqual(nsm.call_args.args[0], context_nonce)
            runtime.handle({'operation': 'attest', 'nonce': b64(context_nonce)})
            self.assertEqual(nsm.call_args.args[0], freshness_nonce(context_nonce))
            self.assertNotEqual(nsm.call_args.args[0], context_nonce)
            runtime.handle({'operation': 'attest_challenge', 'context': context})
            self.assertEqual(nsm.call_args.args[0], context_nonce)
            self.assertEqual(runtime.channel.active_context(context)['expiresAt'], context['expiresAt'])
            for changed in ({**context, 'nonce': 'f' * 64},
                            {**context, 'bindingDigest': 'b' * 64},
                            {**context, 'expiresAt': context['expiresAt'] + 1}):
                with self.subTest(changed=changed), self.assertRaises(Rejected):
                    runtime.handle({'operation': 'attest_challenge', 'context': changed})
            self.assertEqual(nsm.call_count, 3)
            with patch('time.time', return_value=context['expiresAt']):
                with self.assertRaisesRegex(Rejected, 'expired_or_replayed_challenge'):
                    runtime.handle({'operation': 'attest_challenge', 'context': context})
            envelope = encrypt_session(runtime.channel.public_key_der, context,
                                       {'synthetic': True}, consent=True)
            runtime.channel.decrypt_once(envelope)
            with self.assertRaisesRegex(Rejected, 'expired_or_replayed_challenge'):
                runtime.handle({'operation': 'attest_challenge', 'context': context})
            self.assertEqual(nsm.call_count, 3)

    def test_frame_absolute_deadline_is_not_reset_by_drip_data(self):
        stream = Mock()
        stream.recv.side_effect = [struct.pack("!I", 2), b"{", b"}"]
        with patch("verification.runtime.time.monotonic", side_effect=[0, 1, 4, 6]):
            with self.assertRaisesRegex(Rejected, "frame_timeout"):
                receive(stream)
        self.assertEqual(stream.recv.call_count, 2)

    def test_frame_size_and_truncation(self):
        for replies in ([struct.pack("!I", 100000)], [struct.pack("!I", 5), b""]):
            stream = Mock()
            stream.recv.side_effect = replies
            with self.assertRaises(Rejected):
                receive(stream)

    def test_read_deadline_terminates_active_socket(self):
        deadline = ReadDeadline(60)
        stream = Mock()
        deadline.stream = stream
        deadline.expire()
        stream.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        stream.close.assert_called_once()
        with self.assertRaisesRegex(Rejected, "bank_read_timeout"):
            deadline.check()
        deadline.close()

    def test_read_deadline_blocks_late_dns_without_sending_secrets(self):
        deadline = ReadDeadline(60)
        deadline.expire()
        stream = Mock()
        with self.assertRaisesRegex(Rejected, "bank_read_timeout"):
            deadline.tls(stream, "synthetic.example")
        stream.close.assert_called_once()
        stream.send.assert_not_called()
        deadline.close()

    def test_readiness_refuses_current_unreleased_system(self):
        status = inspect()
        self.assertFalse(status["readyForSecrets"])
        self.assertIn("ownerClientValidated", status["blockers"])
        self.assertIn("hardwareEndToEndVerified", status["blockers"])
        self.assertFalse(status["automaticPayout"])

    def test_json_numeric_overflow_and_utf8_byte_limit(self):
        for value in ('{"n":1e999}', '{"n":-1e999}'):
            with self.assertRaises(Rejected):
                strict_json(value)
        with self.assertRaises(Rejected):
            strict_json('"ééé"', 6)


if __name__ == "__main__":
    unittest.main()
