"""Fresh, single-use encryption bound to attested campaign and billing terms."""
import hashlib
import secrets
import threading
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from verification.common import b64, unb64
from .common import Rejected, canonical, fields, require, strict_json

MAX_PAYLOAD = 2_000_000
CONTEXT_FIELDS = {'protocol','jobId','bindingDigest','policyDigest','epochId','wallet','nonce','clientNonce','expiresAt'}


def encrypt(public_key_der, context, payload, *, consent):
    require(consent is True, 'consent_required')
    fields(context, CONTEXT_FIELDS)
    plain = canonical(payload)
    require(len(plain) <= MAX_PAYLOAD, 'submission_size')
    key = serialization.load_der_public_key(public_key_der)
    require(isinstance(key, rsa.RSAPublicKey) and key.key_size == 3072, 'invalid_public_key')
    secret, nonce = AESGCM.generate_key(bit_length=256), secrets.token_bytes(12)
    aad = canonical(context)
    wrapped = key.encrypt(secret, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=hashlib.sha256(aad).digest()))
    return {'context':context,'wrappedKey':b64(wrapped),'nonce':b64(nonce),'ciphertext':b64(AESGCM(secret).encrypt(nonce,plain,aad))}


class Channel:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537,key_size=3072)
        self.public_key_der = self.key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.pending = {}
        self.lock = threading.Lock()

    def challenge(self, status, *, policy_digest, epoch_id, wallet, client_nonce):
        require(isinstance(client_nonce,str) and len(client_nonce)==64 and all(c in '0123456789abcdef' for c in client_nonce),'invalid_nonce')
        require(status['state']=='reserved','job_replayed')
        with self.lock:
            now = int(time.time())
            require(status['expiresAt']>now,'job_expired')
            self.pending = {k:v for k,v in self.pending.items() if v['expiresAt']>now}
            require(len(self.pending)<50,'capacity')
            context = {'protocol':'peerlink-transcript-v1','jobId':status['jobId'],'bindingDigest':status['bindingDigest'],
                       'policyDigest':policy_digest,'epochId':epoch_id,'wallet':wallet,'clientNonce':client_nonce,
                       'nonce':secrets.token_hex(32),'expiresAt':min(now+120,status['expiresAt'])}
            self.pending[context['nonce']] = context
            return dict(context)

    def decrypt_once(self,envelope):
        fields(envelope,{'context','wrappedKey','nonce','ciphertext'})
        context=envelope['context'];fields(context,CONTEXT_FIELDS)
        require(isinstance(context['nonce'],str),'invalid_nonce')
        with self.lock:
            expected=self.pending.get(context['nonce'])
            require(expected is not None and expected==context and context['expiresAt']>time.time(),'expired_or_replayed_challenge')
            try:
                aad=canonical(context)
                secret=self.key.decrypt(unb64(envelope['wrappedKey'],512),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=hashlib.sha256(aad).digest()))
                nonce=unb64(envelope['nonce'],12);require(len(nonce)==12,'invalid_nonce')
                plain=AESGCM(secret).decrypt(nonce,unb64(envelope['ciphertext'],MAX_PAYLOAD+16),aad)
                result=strict_json(plain,MAX_PAYLOAD)
                self.pending.pop(context['nonce'])
                return result
            except Exception:
                raise Rejected('invalid_envelope') from None

    def sign(self,payload):
        signature=self.key.sign(canonical(payload),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())
        return {'payload':payload,'signature':b64(signature)}
