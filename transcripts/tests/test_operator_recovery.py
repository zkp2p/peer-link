"""Synthetic outside-enclave recovery and durable retry tests; no AWS or network."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from eth_account import Account
from eth_utils import keccak

from transcripts.common import Rejected,canonical
from transcripts.epoch import DEPLOYER_REFUND_ADDRESS,USDC_ADDRESS
from transcripts.eth_payout import TRANSFER_TOPIC
from transcripts.kms_signer import KmsSigner
from transcripts.operator_recovery import AWSKMSExchange,OperatorRecovery
from transcripts.tests.test_core_eth_payout import SyntheticRPC,BLOCKHASH
from transcripts.tests.test_kms_signer import KEY_ID,WALLET,PUBLIC_DER,SyntheticBroker,b64,transaction,FIXTURE_KEY


class RecoveryRPC(SyntheticRPC):
    base_fee=1000
    def __init__(self):
        super().__init__();self.pending=self.nonce;self.known=None;self.amount=49_123_456
        self.fail_send=False;self.before_send=lambda raw:None
    def call(self,method,params):
        if method=='eth_getTransactionCount':return hex(self.nonce if params[1]=='latest' else self.pending)
        if method=='eth_getTransactionByHash':return copy.deepcopy(self.known)
        if method=='eth_call':return '0x'+f'{self.amount:064x}'
        if method=='eth_sendRawTransaction':
            self.before_send(params[0]);self.sent.append(params[0])
            if self.fail_send:raise Rejected('payout_rpc_unavailable')
            txid='0x'+keccak(bytes.fromhex(params[0][2:])).hex()
            self.known={'hash':txid,'blockNumber':None};self.pending=self.nonce+1
            return txid
        return super().call(method,params)
    def mine(self,record,confirmations=2,amount=None):
        txid=record['transactionId'];amount=record['amountMinor'] if amount is None else amount
        self.nonce=record['nonce']+1;self.pending=self.nonce
        self.known={'hash':txid,'blockNumber':'0x64'}
        self.latest=99+confirmations
        self.amount=0
        self.receipt={'transactionHash':txid,'status':'0x1','from':WALLET.lower(),'to':USDC_ADDRESS,
            'blockNumber':'0x64','blockHash':BLOCKHASH,'logs':[{'address':USDC_ADDRESS,
            'topics':[TRANSFER_TOPIC,'0x'+WALLET[2:].lower().rjust(64,'0'),'0x'+DEPLOYER_REFUND_ADDRESS[2:].rjust(64,'0')],
            'data':'0x'+f'{amount:064x}','removed':False,'transactionHash':txid,'blockHash':BLOCKHASH}]}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.state=Path(self.directory.name)/'recovery.json'
        self.broker=SyntheticBroker();self.signer=KmsSigner(KEY_ID,WALLET,self.broker);self.rpc=RecoveryRPC()
        self.policy={'payoutRpc':self.rpc.endpoint,'payoutAuthority':{'kind':'aws_kms','keyId':KEY_ID,'wallet':WALLET.lower()}}
    def recovery(self):return OperatorRecovery(self.policy,self.rpc,self.signer,self.state)
    def record(self):return json.loads(self.state.read_text())

    def test_default_plan_does_not_sign_persist_or_broadcast(self):
        result=self.recovery().run()
        self.assertEqual(result['state'],'plan');self.assertEqual(result['recipient'],DEPLOYER_REFUND_ADDRESS)
        self.assertEqual(result['amountMinor'],49_123_456)
        self.assertEqual(self.broker.requests,[]);self.assertEqual(self.rpc.sent,[]);self.assertFalse(self.state.exists())

    def test_durable_identity_before_broadcast_and_no_second_sign_on_retry(self):
        self.rpc.before_send=lambda raw:self.assertEqual(self.record()['signedTransaction'],raw)
        self.rpc.fail_send=True
        with self.assertRaises(Rejected):self.recovery().run(execute=True)
        stored=self.state.read_bytes()
        self.assertEqual(self.state.stat().st_mode&0o777,0o600)
        self.rpc.fail_send=False
        result=self.recovery().run(execute=True)
        self.assertEqual(result['state'],'pending');self.assertEqual(self.state.read_bytes(),stored)
        self.assertEqual(len(self.broker.requests),1);self.assertEqual(self.rpc.sent[0],self.rpc.sent[1])
        # Known pending transactions are observed rather than needlessly rebroadcast.
        self.recovery().run(execute=True);self.assertEqual(len(self.rpc.sent),2)
        self.rpc.mine(self.record(),confirmations=1)
        self.assertEqual(self.recovery().run(execute=True)['state'],'pending')
        self.rpc.mine(self.record(),confirmations=2)
        self.assertEqual(self.recovery().run(execute=True)['state'],'confirmed')
        self.assertEqual(len(self.broker.requests),1)

    def test_saved_bytes_are_actual_fixed_refund_and_exact_receipt_required(self):
        self.recovery().run(execute=True)
        record=self.record();raw=bytes.fromhex(record['signedTransaction'][2:])
        self.assertEqual(Account.recover_transaction(raw).lower(),WALLET.lower())
        self.assertTrue(self.recovery().transport.validate_refund(raw,record['transactionId'],49_123_456))
        self.rpc.mine(record,amount=49_123_455)
        with self.assertRaisesRegex(Rejected,'payout_receipt_mismatch'):self.recovery().run(execute=True)

    def test_confirmed_saved_refund_reports_later_funding_without_new_payment(self):
        self.recovery().run(execute=True)
        record=self.record();self.rpc.mine(record)
        stored=self.state.read_bytes()
        for execute in (False,True):
            for balance in (0,7_000_000,50_000_001):
                with self.subTest(execute=execute,balance=balance):
                    self.rpc.amount=balance
                    result=self.recovery().run(execute=execute)
                    self.assertEqual(result,{'state':'confirmed_but_balance_nonzero' if balance else 'confirmed',
                        'transactionId':record['transactionId'],'remainingAmountMinor':balance})
                    self.assertEqual(self.state.read_bytes(),stored)
        self.assertEqual(len(self.broker.requests),1);self.assertEqual(len(self.rpc.sent),1)

    def test_post_broadcast_confirmation_checks_balance_and_query_failure_fails_closed(self):
        # Exercise the second confirmation branch on the same execution call.
        def mine_and_refund(raw):
            self.rpc.mine(self.record());self.rpc.amount=1_000_000
        self.rpc.before_send=mine_and_refund
        result=self.recovery().run(execute=True)
        self.assertEqual(result['state'],'confirmed_but_balance_nonzero')
        self.assertEqual(result['remainingAmountMinor'],1_000_000)
        for execute in (False,True):
            recovery=self.recovery()
            with patch.object(recovery.transport,'funding_balances',side_effect=Rejected('payout_rpc_unavailable')):
                with self.assertRaisesRegex(Rejected,'payout_rpc_unavailable'):recovery.run(execute=execute)

    def test_unknown_pending_nonce_and_balance_limit_fail_before_sign(self):
        self.rpc.pending=self.rpc.nonce+1
        with self.assertRaisesRegex(Rejected,'recovery_unknown_pending_nonce'):self.recovery().run(execute=True)
        self.rpc.pending=self.rpc.nonce;self.rpc.amount=50_000_001
        with self.assertRaisesRegex(Rejected,'recovery_balance_limit'):self.recovery().run(execute=True)
        self.assertEqual(self.broker.requests,[]);self.assertEqual(self.rpc.sent,[])

    def test_empty_balance_and_insufficient_gas_never_sign(self):
        self.rpc.amount=0
        self.assertEqual(self.recovery().run(execute=True)['state'],'empty')
        self.rpc.amount=1;self.rpc.base_fee=100_000_000
        with self.assertRaisesRegex(Rejected,'recovery_gas_insufficient'):self.recovery().run(execute=True)
        self.assertEqual(self.broker.requests,[])

    def test_durability_failure_prevents_any_broadcast(self):
        recovery=self.recovery()
        with patch.object(recovery,'_save',side_effect=Rejected('recovery_state_write_failed')):
            with self.assertRaises(Rejected):recovery.run(execute=True)
        self.assertEqual(self.rpc.sent,[])

    def test_retry_reestablishes_state_durability_before_broadcast(self):
        self.rpc.fail_send=True
        with self.assertRaises(Rejected):self.recovery().run(execute=True)
        self.rpc.fail_send=False;recovery=self.recovery()
        with patch.object(recovery,'_sync_saved',side_effect=Rejected('recovery_state_write_failed')):
            with self.assertRaises(Rejected):recovery.run(execute=True)
        self.assertEqual(len(self.rpc.sent),1)
        self.assertEqual(len(self.broker.requests),1)

    def test_state_cannot_change_authority_amount_or_signed_recipient(self):
        self.recovery().run(execute=True);original=self.record()
        altered_tx=transaction(original['nonce']);signed=Account.from_key(FIXTURE_KEY).sign_transaction(altered_tx)
        changes=[{'wallet':'0x'+'2'*40},{'policyDigest':'0'*64},{'amountMinor':1},
                 {'recipient':'0x'+'3'*40},{'extra':'data'},
                 {'signedTransaction':'0x'+bytes(signed.raw_transaction).hex(),'transactionId':'0x'+bytes(signed.hash).hex()}]
        for change in changes:
            with self.subTest(change=change):
                self.state.write_bytes(canonical({**original,**change}))
                with self.assertRaises(Rejected):self.recovery().run(execute=True)
        self.assertEqual(len(self.broker.requests),1);self.assertEqual(len(self.rpc.sent),1)

    def test_unknown_replacement_nonce_is_not_reconciled_as_refund(self):
        self.recovery().run(execute=True)
        self.rpc.nonce+=1;self.rpc.pending=self.rpc.nonce;self.rpc.known=None
        with self.assertRaisesRegex(Rejected,'recovery_unknown_pending_nonce'):self.recovery().run(execute=True)
        self.assertEqual(len(self.broker.requests),1)


class AWSExchangeTests(unittest.TestCase):
    def test_fixed_profile_region_get_public_key_and_digest_mode(self):
        calls=[];broker=SyntheticBroker()
        def run(args,**kwargs):
            calls.append((args,kwargs));payload=json.loads(kwargs['input'])
            if 'get-public-key' in args:
                result={'KeyId':KEY_ID,'PublicKey':b64(PUBLIC_DER),'KeySpec':'ECC_SECG_P256K1',
                        'KeyUsage':'SIGN_VERIFY','SigningAlgorithms':['ECDSA_SHA_256']}
            else:
                import base64
                self.assertEqual(payload['MessageType'],'DIGEST');self.assertEqual(payload['SigningAlgorithm'],'ECDSA_SHA_256')
                response=broker({'version':1,'keyId':KEY_ID,'digest':base64.b64decode(payload['Message']).hex()})
                result={'KeyId':KEY_ID,'SigningAlgorithm':'ECDSA_SHA_256','Signature':response['signature']}
            return SimpleNamespace(returncode=0,stdout=json.dumps(result))
        exchange=AWSKMSExchange(KEY_ID,WALLET,run=run)
        result=KmsSigner(KEY_ID,WALLET,exchange).sign_transaction(transaction())
        self.assertEqual(Account.recover_transaction(result.raw_transaction),WALLET)
        for args,kwargs in calls:
            self.assertEqual(args[:5],['aws','--profile','peer','--region','us-east-1'])
            self.assertIn('file:///dev/stdin',args)
            self.assertEqual(kwargs['timeout'],30)

    def test_wrong_metadata_and_aws_errors_fail_without_secret_details(self):
        def wrong(args,**kwargs):
            return SimpleNamespace(returncode=0,stdout=json.dumps({'KeyId':KEY_ID,'PublicKey':b64(PUBLIC_DER),
                'KeySpec':'ECC_NIST_P256','KeyUsage':'SIGN_VERIFY','SigningAlgorithms':['ECDSA_SHA_256']}))
        with self.assertRaisesRegex(Rejected,'kms_public_key_invalid'):AWSKMSExchange(KEY_ID,WALLET,run=wrong)
        def failed(args,**kwargs):return SimpleNamespace(returncode=1,stdout='synthetic-private-aws-error')
        with self.assertRaisesRegex(Rejected,'^kms_broker_unavailable$'):AWSKMSExchange(KEY_ID,WALLET,run=failed)


if __name__=='__main__':unittest.main()
