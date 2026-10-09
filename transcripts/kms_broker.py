"""Host-side KMS signing for the explicitly trusted operator-custody pilot.

KMS Sign has no Nitro Recipient/PCR enforcement. The narrowly scoped host IAM
role and authorized operators can sign; bank plaintext remains in the enclave.
Only the configured CID and measured key/wallet binding reach this listener.
"""
import base64
import os
import re
import socket
import struct
import subprocess
import tempfile
import threading

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from eth_utils import keccak

from .common import Rejected, address, canonical, require, strict_json
from .wire import exact

MAX_MESSAGE = 8192
KEY_ARN = re.compile(r'arn:(aws|aws-us-gov|aws-cn):kms:([a-z0-9-]+):[0-9]{12}:key/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|mrk-[0-9a-f]{32})')
ERRORS = {'kms_request_invalid', 'kms_key_mismatch', 'kms_unavailable',
          'kms_key_invalid', 'kms_signature_invalid', 'kms_peer_denied'}


def decode(value, maximum, code):
    require(isinstance(value, str) and 0 < len(value) <= maximum, code)
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise Rejected(code) from None
    require(base64.b64encode(data).decode('ascii') == value, code)
    return data


class KmsBroker:
    def __init__(self, key_id, wallet, runner=None):
        match = KEY_ARN.fullmatch(key_id) if isinstance(key_id, str) else None
        require(match is not None, 'kms_key_invalid')
        self.key_id, self.region, self.wallet = key_id, match.group(2), address(wallet)
        self.runner = runner or subprocess.run
        self._public = None
        self._public_b64 = None
        self._lock = threading.Lock()

    def _call(self, operation, extra=()):
        # Instance-role credentials only: no inherited/static operator credentials.
        env = dict(os.environ)
        for name in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
                     'AWS_SECURITY_TOKEN', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE',
                     'AWS_WEB_IDENTITY_TOKEN_FILE', 'AWS_ROLE_ARN',
                     'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI', 'AWS_CONTAINER_CREDENTIALS_FULL_URI',
                     'AWS_EC2_METADATA_SERVICE_ENDPOINT', 'AWS_EC2_METADATA_SERVICE_ENDPOINT_MODE',
                     'AWS_CA_BUNDLE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'SSL_CERT_FILE', 'SSL_CERT_DIR'):
            env.pop(name, None)
        for name in tuple(env):
            if name.startswith('AWS_ENDPOINT_URL'):
                env.pop(name, None)
        env.update(AWS_CONFIG_FILE='/dev/null', AWS_SHARED_CREDENTIALS_FILE='/dev/null',
                   AWS_PAGER='', AWS_EC2_METADATA_DISABLED='false', AWS_MAX_ATTEMPTS='1',
                   AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true')
        args = ['aws', 'kms', operation, '--key-id', self.key_id, '--region', self.region,
                '--output', 'json', '--no-cli-pager', '--cli-connect-timeout', '5',
                '--cli-read-timeout', '15', *extra]
        try:
            result = self.runner(args, capture_output=True, timeout=25, check=False, env=env)
            require(result.returncode == 0, 'kms_unavailable')
            return strict_json(result.stdout, MAX_MESSAGE)
        except Exception:
            raise Rejected('kms_unavailable') from None

    def public_key(self):
        with self._lock:
            if self._public is None:
                result = self._call('get-public-key')
                require(result.get('KeyId') == self.key_id
                        and result.get('KeySpec') == 'ECC_SECG_P256K1'
                        and result.get('KeyUsage') == 'SIGN_VERIFY'
                        and result.get('SigningAlgorithms') == ['ECDSA_SHA_256'], 'kms_key_invalid')
                encoded = result.get('PublicKey')
                data = decode(encoded, 512, 'kms_key_invalid')
                try:
                    public = serialization.load_der_public_key(data)
                    require(isinstance(public, ec.EllipticCurvePublicKey)
                            and isinstance(public.curve, ec.SECP256K1), 'kms_key_invalid')
                    require(public.public_bytes(serialization.Encoding.DER,
                            serialization.PublicFormat.SubjectPublicKeyInfo) == data, 'kms_key_invalid')
                    raw = public.public_bytes(serialization.Encoding.X962,
                                              serialization.PublicFormat.UncompressedPoint)
                    require('0x' + keccak(raw[1:])[-20:].hex() == self.wallet, 'kms_key_invalid')
                except Exception:
                    raise Rejected('kms_key_invalid') from None
                self._public, self._public_b64 = public, encoded
            return self._public, self._public_b64

    def sign(self, request):
        require(isinstance(request, dict) and set(request) == {'version', 'keyId', 'digest'}
                and type(request['version']) is int and request['version'] == 1
                and isinstance(request['digest'], str)
                and re.fullmatch('[0-9a-f]{64}', request['digest']), 'kms_request_invalid')
        require(request['keyId'] == self.key_id, 'kms_key_mismatch')
        public, public_b64 = self.public_key()
        digest = bytes.fromhex(request['digest'])
        # Raw digest file is 0600 and ephemeral; no signing key exists on this host.
        with tempfile.NamedTemporaryFile(prefix='transcript-kms-digest-') as message:
            message.write(digest); message.flush()
            result = self._call('sign', ['--message', 'fileb://' + message.name,
                               '--message-type', 'DIGEST', '--signing-algorithm', 'ECDSA_SHA_256'])
        require(result.get('KeyId') == self.key_id
                and result.get('SigningAlgorithm') == 'ECDSA_SHA_256', 'kms_signature_invalid')
        encoded = result.get('Signature')
        signature = decode(encoded, 256, 'kms_signature_invalid')
        try:
            r, s = utils.decode_dss_signature(signature)
            require(utils.encode_dss_signature(r, s) == signature, 'kms_signature_invalid')
            public.verify(signature, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        except Exception:
            raise Rejected('kms_signature_invalid') from None
        return {'version': 1, 'keyId': self.key_id, 'publicKey': public_b64, 'signature': encoded}


def connection(conn, peer_cid, allowed_cid, broker):
    try:
        conn.settimeout(5)
        require(peer_cid == allowed_cid, 'kms_peer_denied')
        length = struct.unpack('!I', exact(conn, 4))[0]
        require(0 < length <= MAX_MESSAGE, 'kms_request_invalid')
        request = strict_json(exact(conn, length), MAX_MESSAGE)
        response = broker.sign(request)
    except Exception as error:
        code = str(error) if isinstance(error, Rejected) and str(error) in ERRORS else 'kms_request_invalid'
        response = {'version': 1, 'error': code}
    try:
        data = canonical(response)
        require(len(data) <= MAX_MESSAGE, 'kms_request_invalid')
        conn.sendall(struct.pack('!I', len(data)) + data)
    except Exception:
        pass
    finally:
        conn.close()


def serve(port, cid, broker):
    with socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM) as listener:
        listener.bind((socket.VMADDR_CID_ANY, port)); listener.listen(4)
        slots = threading.BoundedSemaphore(4)
        while True:
            conn, peer = listener.accept()
            # Reject foreign CIDs before parsing any request or invoking AWS.
            if peer[0] != cid or not slots.acquire(blocking=False):
                conn.close(); continue
            def run(channel=conn, peer_cid=peer[0]):
                try:
                    connection(channel, peer_cid, cid, broker)
                finally:
                    slots.release()
            threading.Thread(target=run, daemon=True).start()
