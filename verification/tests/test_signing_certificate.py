import datetime
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from verification.infra.signing_certificate import certificate


class SigningCertificateTests(unittest.TestCase):
    def test_exact_external_key_signs_certificate(self):
        key = ec.generate_private_key(ec.SECP384R1())
        sign = lambda digest: key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA384())))
        cert = certificate(key.public_key(), sign, datetime.datetime.now(datetime.timezone.utc))
        cert.verify_directly_issued_by(cert)
        self.assertEqual(cert.public_key().public_numbers(), key.public_key().public_numbers())

    def test_wrong_external_signature_is_rejected_before_publication(self):
        first = ec.generate_private_key(ec.SECP384R1())
        second = ec.generate_private_key(ec.SECP384R1())
        sign = lambda digest: second.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA384())))
        with self.assertRaises(InvalidSignature):
            certificate(first.public_key(), sign, datetime.datetime.now(datetime.timezone.utc))

    def test_wrong_key_curve_is_rejected(self):
        with self.assertRaises(ValueError):
            certificate(ec.generate_private_key(ec.SECP256R1()).public_key(), None,
                        datetime.datetime.now(datetime.timezone.utc))
