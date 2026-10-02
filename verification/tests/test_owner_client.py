"""Owner client freshness with real attestation, encryption and receipt cryptography.

Only the AWS root is synthetic (see test_crypto.AttestationTests). No bank data.
"""
import hashlib
import time
import unittest
from unittest.mock import patch

from verification.channel import SessionChannel
from verification.common import Rejected, b64, digest, unb64
from verification.owner_client import complete
from verification.receipts import sign as sign_receipt
from verification.tests import test_crypto


class OwnerClientFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.pki = test_crypto.AttestationTests()
        self.pki.setUp()
        self.addCleanup(self.pki.tearDown)
        self.now = time.time()
        clock = patch('time.time', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.channel = SessionChannel()
        self.quote_keys = [self.channel.public_key_der]
        self.release = {**self.pki.release, 'liveVerification': True}
        module = b'synthetic-adapter-bytes'
        self.binding = {'revision': hashlib.sha256(module).hexdigest(), 'release': digest(self.release),
                        'policy': self.release['policyDigest'], 'prompt': 'c' * 64}
        self.context = self.channel.challenge('attempt-1', digest(self.binding))
        self.bundle = {'module': b64(module), 'binding': self.binding, 'context': self.context,
                       'permit': {'synthetic': True}}
        self.session = {'credentials': {'cookie': 'SYNTHETIC-OWNER-SECRET'}, 'sourceContext': None,
                        'transactionId': 'synthetic-wire-001'}
        self.operations = []
        self.received = []

    def quote(self, nonce, key):
        document = {**self.pki.doc, 'timestamp': int(self.now * 1000), 'nonce': nonce,
                    'public_key': key}
        return {'attestation': b64(self.pki.encode(document)), 'publicKey': b64(key),
                'policyDigest': self.release['policyDigest']}

    def call(self, request):
        self.operations.append(request['operation'])
        if request['operation'] == 'attest':
            key = self.quote_keys[min(self.operations.count('attest'), len(self.quote_keys)) - 1]
            return self.quote(unb64(request['nonce'], 32), key)
        self.assertEqual(request['operation'], 'execute')
        self.received.append(self.channel.decrypt_once(request['envelope']))
        claims = {'audience': 'peer-link-contribution-verification-v1', 'attempt': 'attempt-1',
                  'ticket': 'ticket-1', 'bindingDigest': digest(self.binding),
                  'capability': 'synthetic-sent', 'result': 'verified',
                  'issuedAt': int(self.now), 'expiresAt': int(self.now) + 300}
        receipt = sign_receipt(claims, self.channel.key)
        return {'receipt': receipt,
                'quote': self.quote(bytes.fromhex(digest(receipt)), self.channel.public_key_der)}

    def run_owner(self, seconds):
        def collect():
            self.now += seconds  # The owner reads the scope, types CONSENT and hidden inputs.
            return dict(self.session)
        return complete(self.bundle, release=self.release, expected_adapter=self.binding['revision'],
                        call=self.call, collect_session=collect)

    def test_slow_owner_input_is_encrypted_after_a_fresh_quote(self):
        # Longer than the 60-second attestation window, within the 120-second challenge.
        report = self.run_owner(61)
        self.assertEqual(report['receipt']['claims']['result'], 'verified')
        self.assertEqual(self.received, [self.session])
        self.assertEqual(self.operations, ['attest', 'attest', 'execute'])

    def test_changed_enclave_key_after_consent_never_receives_secrets(self):
        self.quote_keys.append(SessionChannel().public_key_der)
        with self.assertRaisesRegex(Rejected, 'session_key_changed'):
            self.run_owner(5)
        self.assertNotIn('execute', self.operations)

    def test_expired_challenge_is_still_refused_before_encryption(self):
        with self.assertRaisesRegex(Rejected, 'expired_challenge'):
            self.run_owner(121)
        self.assertNotIn('execute', self.operations)


if __name__ == '__main__':
    unittest.main()
