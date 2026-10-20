import json
import unittest
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from verification.common import canonical, unb64
from verification.envelope import decrypt

class EnvelopeInteropTests(unittest.TestCase):
    def test_browser_and_python_share_canonical_encryption(self):
        vector=json.loads((Path(__file__).parent/'fixtures/envelope.json').read_text())
        key=serialization.load_der_private_key(unb64(vector['privateKey']),password=None)
        self.assertEqual(canonical(vector['payload']).decode(),vector['canonical'])
        for field in ['browserEnvelope','pythonEnvelope']:
            self.assertEqual(decrypt(key,vector[field]),vector['payload'])
