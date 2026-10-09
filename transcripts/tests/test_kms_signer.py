"""Local fixed synthetic KMS signatures; no AWS, network, live keys or funding."""
import base64
import copy
import hashlib
import unittest

import rlp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from eth_account import Account
from eth_keys import keys
from eth_utils import keccak, to_checksum_address

from transcripts.common import Rejected
from transcripts.epoch import CHAIN_ID, USDC_ADDRESS
from transcripts.eth_payout import transfer_data, refund_data
from transcripts.kms_signer import KmsSigner, SECP256K1_ORDER

KEY_ID = 'arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab'
FIXTURE_KEY = (1).to_bytes(32, 'big')
PUBLIC = ec.derive_private_key(1, ec.SECP256K1()).public_key()
PUBLIC_DER = PUBLIC.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
WALLET = Account.from_key(FIXTURE_KEY).address


def b64(value):
    return base64.b64encode(value).decode()


def transaction(nonce=0):
    return {'type':2,'chainId':CHAIN_ID,'nonce':nonce,'to':to_checksum_address(USDC_ADDRESS),
            'value':0,'data':transfer_data('0x'+'2'*40,5_000_000),'gas':72000,
            'maxFeePerGas':100_000_000,'maxPriorityFeePerGas':10000,'accessList':[]}


class SyntheticBroker:
    def __init__(self, high_s=False):
        self.high_s=high_s;self.requests=[];self.mutate=lambda response:response
    def __call__(self, request):
        self.requests.append(copy.deepcopy(request))
        signature=keys.PrivateKey(FIXTURE_KEY).sign_msg_hash(bytes.fromhex(request['digest']))
        s=SECP256K1_ORDER-signature.s if self.high_s else signature.s
        response={'version':1,'keyId':KEY_ID,'publicKey':b64(PUBLIC_DER),
                  'signature':b64(utils.encode_dss_signature(signature.r,s))}
        return self.mutate(response)


class KmsSignerTests(unittest.TestCase):
    def test_exact_eth_account_encoding_for_both_s_values_and_recovery_parities(self):
        seen=set()
        for nonce in range(12):
            tx=transaction(nonce)
            expected=Account.from_key(FIXTURE_KEY).sign_transaction(tx)
            for high_s in (False,True):
                with self.subTest(nonce=nonce,high_s=high_s):
                    broker=SyntheticBroker(high_s);signer=KmsSigner(KEY_ID,WALLET.lower(),broker)
                    result=signer.sign_transaction(tx)
                    self.assertEqual(result.raw_transaction,bytes(expected.raw_transaction))
                    self.assertEqual(result.hash,bytes(expected.hash))
                    self.assertEqual(signer.address,WALLET)
                    self.assertEqual(Account.recover_transaction(result.raw_transaction),WALLET)
                    decoded=rlp.decode(result.raw_transaction[1:])
                    seen.add(int.from_bytes(decoded[9],'big'))
                    self.assertLessEqual(int.from_bytes(decoded[11],'big'),SECP256K1_ORDER//2)
                    request=broker.requests[0]
                    self.assertEqual(set(request),{'version','keyId','digest'})
                    self.assertEqual(request['digest'],keccak(b'\x02'+rlp.encode(decoded[:9])).hex())
        self.assertEqual(seen,{0,1})

    def test_kms_style_prehashed_ecdsa_and_fixed_refund(self):
        tx=transaction();tx['data']=refund_data(49_123_456)
        def exchange(request):
            # Simulates ECDSA_SHA_256 with MessageType=DIGEST: no second hash.
            signature=ec.derive_private_key(1,ec.SECP256K1()).sign(bytes.fromhex(request['digest']),
                            ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            return {'version':1,'keyId':KEY_ID,'publicKey':b64(PUBLIC_DER),'signature':b64(signature)}
        result=KmsSigner(KEY_ID,WALLET,exchange).sign_transaction(tx)
        self.assertEqual(Account.recover_transaction(result.raw_transaction),WALLET)
        self.assertEqual(rlp.decode(result.raw_transaction[1:])[7],tx['data'])

    def test_wrong_wallet_curve_and_noncanonical_public_key_fail(self):
        other=ec.derive_private_key(2,ec.SECP256K1()).public_key()
        wrong_curve=ec.derive_private_key(1,ec.SECP256R1()).public_key()
        candidates=[other.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo),
                    wrong_curve.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo),
                    PUBLIC_DER+b'\0',b'not-a-public-key']
        for candidate in candidates:
            with self.subTest(candidate=candidate[:12]):
                broker=SyntheticBroker();broker.mutate=lambda response:{**response,'publicKey':b64(candidate)}
                with self.assertRaises(Rejected):KmsSigner(KEY_ID,WALLET,broker).sign_transaction(transaction())
        with self.assertRaisesRegex(Rejected,'kms_wallet_mismatch'):
            KmsSigner(KEY_ID,'0x'+'2'*40,SyntheticBroker()).sign_transaction(transaction())

    def test_der_signature_ranges_noncanonical_encodings_and_wrong_digest_reject(self):
        candidates=[utils.encode_dss_signature(r,s) for r,s in
                    ((0,1),(1,0),(SECP256K1_ORDER,1),(1,SECP256K1_ORDER),(1,1))]
        good=keys.PrivateKey(FIXTURE_KEY).sign_msg_hash(b'\0'*32)
        candidates.extend([utils.encode_dss_signature(good.r,good.s)+b'\0',b'\x30\x06\x02\x01\xff\x02\x01\x01',
                           utils.encode_dss_signature(good.r,good.s)])
        for candidate in candidates:
            with self.subTest(candidate=candidate.hex()[:20]):
                broker=SyntheticBroker();broker.mutate=lambda response:{**response,'signature':b64(candidate)}
                with self.assertRaises(Rejected):KmsSigner(KEY_ID,WALLET,broker).sign_transaction(transaction())
        def double_hash(response):
            digest=bytes.fromhex(broker.requests[-1]['digest'])
            sig=keys.PrivateKey(FIXTURE_KEY).sign_msg_hash(hashlib.sha256(digest).digest())
            return {**response,'signature':b64(utils.encode_dss_signature(sig.r,sig.s))}
        broker=SyntheticBroker();broker.mutate=double_hash
        with self.assertRaises(Rejected):KmsSigner(KEY_ID,WALLET,broker).sign_transaction(transaction())

    def test_replayed_signature_for_another_nonce_rejects(self):
        broker=SyntheticBroker()
        responses=[]
        broker.mutate=lambda response:responses.append(copy.deepcopy(response)) or response
        KmsSigner(KEY_ID,WALLET,broker).sign_transaction(transaction(0))
        with self.assertRaises(Rejected):
            KmsSigner(KEY_ID,WALLET,lambda request:responses[0]).sign_transaction(transaction(1))

    def test_bounded_exact_broker_schema_base64_and_error_sanitization(self):
        mutations=[lambda r:{**r,'version':True},lambda r:{**r,'keyId':KEY_ID+'x'},lambda r:{**r,'extra':'data'},
                   lambda r:{k:v for k,v in r.items() if k!='signature'},lambda r:None,
                   lambda r:{**r,'signature':'x'*1000},lambda r:{**r,'publicKey':'x'*1000},
                   lambda r:{**r,'signature':r['signature']+'\n'},lambda r:{**r,'signature':'not base64!'}]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                broker=SyntheticBroker();broker.mutate=mutate
                with self.assertRaises(Rejected):KmsSigner(KEY_ID,WALLET,broker).sign_transaction(transaction())
        def unavailable(request):raise RuntimeError('synthetic-secret-detail')
        with self.assertRaisesRegex(Rejected,'^kms_broker_unavailable$'):
            KmsSigner(KEY_ID,WALLET,unavailable).sign_transaction(transaction())

    def test_unapproved_transaction_never_reaches_broker(self):
        changes=[{'type':True},{'chainId':1},{'nonce':True},{'nonce':2**64},{'to':'0x'+'3'*40},
                 {'value':1},{'value':False},{'accessList':[[]]},{'gas':100001},{'maxFeePerGas':10**11},
                 {'maxPriorityFeePerGas':100_000_001},{'data':b'bad'},
                 {'data':bytes.fromhex('a9059cbb')+bytes.fromhex('2'*40).rjust(32,b'\0')+(123).to_bytes(32,'big')},
                 {'extra':'data'}]
        broker=SyntheticBroker();signer=KmsSigner(KEY_ID,WALLET,broker)
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(Rejected):signer.sign_transaction({**transaction(),**change})
        self.assertEqual(broker.requests,[])

    def test_only_exact_known_broker_availability_error_is_retryable(self):
        with self.assertRaisesRegex(Rejected,'^kms_broker_unavailable$'):
            KmsSigner(KEY_ID,WALLET,lambda request:{'version':1,'error':'kms_unavailable'}).sign_transaction(transaction())
        responses=[{'version':True,'error':'kms_unavailable'},
                   {'version':2,'error':'kms_unavailable'},
                   {'version':1,'error':'kms_unavailable','extra':'data'},
                   {'version':1,'error':'kms_signature_invalid'},
                   {'version':1,'error':'kms_key_invalid'},
                   {'version':1,'error':'kms_key_mismatch'},
                   {'version':1,'error':'kms_request_invalid'},
                   {'version':1,'error':'kms_peer_denied'},
                   {'version':1,'error':'unknown_failure'}]
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(Rejected) as rejected:
                    KmsSigner(KEY_ID,WALLET,lambda request:response).sign_transaction(transaction())
                self.assertNotEqual(str(rejected.exception),'kms_broker_unavailable')

    def test_alias_partial_key_id_and_private_key_configuration_are_not_accepted(self):
        for key_id in ('alias/payout',KEY_ID.split('/')[-1],KEY_ID.replace(':key/',':alias/'),'x'*257):
            with self.assertRaises(Rejected):KmsSigner(key_id,WALLET,SyntheticBroker())
        with self.assertRaises(TypeError):KmsSigner(KEY_ID,WALLET,SyntheticBroker(),private_key=FIXTURE_KEY)


if __name__=='__main__':unittest.main()
