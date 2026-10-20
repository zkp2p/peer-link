"""RSA-OAEP/AES-GCM envelopes with authenticated, canonical job context."""
import hashlib
import secrets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .common import b64, unb64, canonical, fields, require, strict_json

MAX_PAYLOAD = 2_000_000


def encrypt(public_key_der, context, payload):
    plain = canonical(payload)
    require(len(plain) <= MAX_PAYLOAD, 'submission_size')
    key = serialization.load_der_public_key(public_key_der)
    require(isinstance(key, rsa.RSAPublicKey) and key.key_size == 3072, 'invalid_public_key')
    secret, nonce = AESGCM.generate_key(bit_length=256), secrets.token_bytes(12)
    aad = canonical(context)
    wrapped = key.encrypt(secret, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                             algorithm=hashes.SHA256(), label=hashlib.sha256(aad).digest()))
    return {'context': context, 'wrappedKey': b64(wrapped), 'nonce': b64(nonce),
            'ciphertext': b64(AESGCM(secret).encrypt(nonce, plain, aad))}


def decrypt(key, envelope):
    fields(envelope, {'context', 'wrappedKey', 'nonce', 'ciphertext'})
    aad = canonical(envelope['context'])
    secret = key.decrypt(unb64(envelope['wrappedKey'], 512), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=hashlib.sha256(aad).digest()))
    nonce = unb64(envelope['nonce'], 12)
    require(len(nonce) == 12, 'invalid_nonce')
    plain = AESGCM(secret).decrypt(nonce, unb64(envelope['ciphertext'], MAX_PAYLOAD + 16), aad)
    return strict_json(plain, MAX_PAYLOAD)
