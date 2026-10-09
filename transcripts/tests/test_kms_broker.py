"""Synthetic broker boundary tests: no AWS, credentials or network transfers."""
import base64
import copy
import json
from pathlib import Path
import socket
import stat
import struct
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from eth_utils import keccak

from transcripts.common import Rejected, canonical
from transcripts.kms_broker import KmsBroker, MAX_MESSAGE, connection
from transcripts.wire import receive

KEY_ID = 'arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab'
PRIVATE = ec.derive_private_key(1, ec.SECP256K1())
PUBLIC = PRIVATE.public_key()
DER = PUBLIC.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
RAW = PUBLIC.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
WALLET = '0x' + keccak(RAW[1:])[-20:].hex()


def b64(value):
    return base64.b64encode(value).decode()


def request(digest='a' * 64):
    return {'version': 1, 'keyId': KEY_ID, 'digest': digest}


class FakeAws:
    def __init__(self):
        self.calls = []
        self.public = {'KeyId': KEY_ID, 'KeySpec': 'ECC_SECG_P256K1', 'KeyUsage': 'SIGN_VERIFY',
                       'SigningAlgorithms': ['ECDSA_SHA_256'], 'PublicKey': b64(DER)}
        self.mutate_sign = lambda response: response
        self.returncode = 0
        self.message_files = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[2] == 'get-public-key':
            result = copy.deepcopy(self.public)
        else:
            path = Path(args[args.index('--message') + 1].removeprefix('fileb://'))
            self.message_files.append(str(path))
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            digest = path.read_bytes()
            assert len(digest) == 32
            signature = PRIVATE.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            result = self.mutate_sign({'KeyId': KEY_ID, 'SigningAlgorithm': 'ECDSA_SHA_256',
                                       'Signature': b64(signature)})
        return SimpleNamespace(returncode=self.returncode, stdout=canonical(result),
                               stderr=b'synthetic-secret-error-detail')


class KmsBrokerTests(unittest.TestCase):
    def test_verified_wallet_signature_cache_cli_and_ephemeral_digest(self):
        aws = FakeAws(); broker = KmsBroker(KEY_ID, WALLET, aws)
        for digest in ('a' * 64, 'b' * 64):
            with patch.dict('os.environ', {'AWS_ENDPOINT_URL_KMS': 'https://synthetic.invalid',
                                          'AWS_CA_BUNDLE': '/synthetic.pem',
                                          'AWS_ACCESS_KEY_ID': 'synthetic-static-key'}):
                result = broker.sign(request(digest))
            self.assertEqual(set(result), {'version', 'keyId', 'publicKey', 'signature'})
            self.assertEqual(result['publicKey'], b64(DER))
            PUBLIC.verify(base64.b64decode(result['signature']), bytes.fromhex(digest),
                          ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        self.assertEqual([args[2] for args, _ in aws.calls], ['get-public-key', 'sign', 'sign'])
        for args, kwargs in aws.calls:
            self.assertEqual(args[args.index('--key-id') + 1], KEY_ID)
            self.assertEqual(args[args.index('--region') + 1], 'us-east-1')
            self.assertLessEqual(kwargs['timeout'], 30)
            self.assertEqual(kwargs['env']['AWS_SHARED_CREDENTIALS_FILE'], '/dev/null')
            self.assertNotIn('AWS_ACCESS_KEY_ID', kwargs['env'])
            self.assertNotIn('AWS_ENDPOINT_URL_KMS', kwargs['env'])
            self.assertNotIn('AWS_CA_BUNDLE', kwargs['env'])
            if args[2] == 'sign':
                self.assertEqual(args[args.index('--message-type') + 1], 'DIGEST')
                self.assertEqual(args[args.index('--signing-algorithm') + 1], 'ECDSA_SHA_256')
        self.assertTrue(all(not Path(path).exists() for path in aws.message_files))

    def test_bad_request_never_calls_aws(self):
        changes = [None, [], {**request(), 'extra': 1}, {**request(), 'version': True},
                   {**request(), 'version': 2}, {**request(), 'digest': 'A' * 64},
                   {**request(), 'digest': 'a' * 63}, {**request(), 'digest': 12},
                   {**request(), 'keyId': KEY_ID + 'x'}]
        aws = FakeAws(); broker = KmsBroker(KEY_ID, WALLET, aws)
        for candidate in changes:
            with self.subTest(candidate=candidate):
                with self.assertRaises(Rejected): broker.sign(candidate)
        self.assertEqual(aws.calls, [])

    def test_key_metadata_curve_wallet_and_canonical_der_binding(self):
        bad_curve = ec.derive_private_key(1, ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        changes = [{'KeyId': KEY_ID + 'x'}, {'KeySpec': 'ECC_NIST_P256'},
                   {'KeyUsage': 'ENCRYPT_DECRYPT'}, {'SigningAlgorithms': ['RSASSA_PSS_SHA_256']},
                   {'PublicKey': b64(bad_curve)}, {'PublicKey': b64(DER + b'\0')},
                   {'PublicKey': 'not-base64'}, {'PublicKey': b64(DER) + '\n'}]
        for change in changes:
            aws = FakeAws(); aws.public.update(change)
            with self.subTest(change=change):
                with self.assertRaisesRegex(Rejected, '^kms_key_invalid$'):
                    KmsBroker(KEY_ID, WALLET, aws).sign(request())
                self.assertEqual([args[2] for args, _ in aws.calls], ['get-public-key'])
        with self.assertRaisesRegex(Rejected, '^kms_key_invalid$'):
            KmsBroker(KEY_ID, '0x' + '2' * 40, FakeAws()).sign(request())
        for invalid in ('alias/payout', KEY_ID.split('/')[-1], KEY_ID + '*', None):
            with self.assertRaises(Rejected): KmsBroker(invalid, WALLET, FakeAws())

    def test_signature_metadata_wrong_digest_and_der_fail_closed(self):
        unrelated = PRIVATE.sign(b'\0' * 32, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        changes = [{'KeyId': KEY_ID + 'x'}, {'SigningAlgorithm': 'ECDSA_SHA_384'},
                   {'Signature': b64(unrelated)}, {'Signature': b64(unrelated + b'\0')},
                   {'Signature': b64(utils.encode_dss_signature(0, 1))}, {'Signature': 'bad!'}]
        for change in changes:
            aws = FakeAws(); aws.mutate_sign = lambda result: {**result, **change}
            with self.subTest(change=change):
                with self.assertRaisesRegex(Rejected, '^kms_signature_invalid$'):
                    KmsBroker(KEY_ID, WALLET, aws).sign(request())

    def test_subprocess_errors_never_expose_stderr_or_exception(self):
        aws = FakeAws(); aws.returncode = 1
        with self.assertRaisesRegex(Rejected, '^kms_unavailable$'):
            KmsBroker(KEY_ID, WALLET, aws).sign(request())
        def fail(*args, **kwargs): raise RuntimeError('synthetic-secret-detail')
        with self.assertRaisesRegex(Rejected, '^kms_unavailable$'):
            KmsBroker(KEY_ID, WALLET, fail).sign(request())

    def exchange_frame(self, frame, cid=16):
        client, host = socket.socketpair(); aws = FakeAws()
        worker = threading.Thread(target=connection, args=(host, cid, 16, KmsBroker(KEY_ID, WALLET, aws)))
        worker.start(); client.settimeout(2)
        try:
            if frame: client.sendall(frame)
            response = receive(client)
        finally:
            client.close(); worker.join(2)
        self.assertFalse(worker.is_alive())
        return response, aws

    def test_peer_and_framing_reject_before_aws_and_body_read(self):
        response, aws = self.exchange_frame(b'', cid=17)
        self.assertEqual(response, {'version': 1, 'error': 'kms_peer_denied'})
        self.assertEqual(aws.calls, [])
        for length in (0, MAX_MESSAGE + 1, 2**32 - 1):
            response, aws = self.exchange_frame(struct.pack('!I', length))
            self.assertEqual(response, {'version': 1, 'error': 'kms_request_invalid'})
            self.assertEqual(aws.calls, [])
        duplicate = b'{"version":1,"version":1,"keyId":"x","digest":"x"}'
        response, aws = self.exchange_frame(struct.pack('!I', len(duplicate)) + duplicate)
        self.assertEqual(response['error'], 'kms_request_invalid')
        self.assertEqual(aws.calls, [])

    def test_valid_framed_exchange(self):
        body = canonical(request())
        response, aws = self.exchange_frame(struct.pack('!I', len(body)) + body)
        self.assertEqual(response['keyId'], KEY_ID)
        self.assertEqual(len(aws.calls), 2)


if __name__ == '__main__': unittest.main()
