"""Operator-only KMS USDC recovery. Plan by default; never recovers RAM-only keys.

Before execution, quiesce every other signer using this KMS wallet. The local file
lock serializes this recovery tool, not a live enclave or another machine. Only
USDC is refunded; residual ETH remains available to the KMS recovery authority.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess

import rlp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from eth_keys import keys
from eth_utils import to_checksum_address

from .common import Rejected, address, canonical, digest, fields, integer, require, strict_json
from .epoch import CHAIN_ID, USDC_ADDRESS, DEPLOYER_REFUND_ADDRESS
from .eth_payout import BaseUSDCPayoutTransport, MAX_FEE_WEI, MAX_PRIORITY_FEE_WEI, MAX_GAS, _quantity, refund_data
from .kms_signer import KmsSigner, KEY_ARN, _base64
from .policy import MAX_BUDGET, validate_payout_authority

STATE_FIELDS = {"version", "keyId", "wallet", "policyDigest", "chainId", "token", "recipient",
                "amountMinor", "nonce", "signedTransaction", "transactionId"}


class AWSKMSExchange:
    """Fixed CLI identity; only public key/digest/signature material crosses stdout."""
    def __init__(self, key_id, expected_wallet, *, run=subprocess.run):
        require(isinstance(key_id,str) and KEY_ARN.fullmatch(key_id) and ":kms:us-east-1:" in key_id,"kms_key_invalid")
        self.key_id,self.wallet,self._run=key_id,address(expected_wallet),run
        metadata=self._call('get-public-key',{'KeyId':key_id})
        require(isinstance(metadata,dict) and metadata.get('KeyId')==key_id
                and metadata.get('KeySpec')=='ECC_SECG_P256K1' and metadata.get('KeyUsage')=='SIGN_VERIFY'
                and metadata.get('SigningAlgorithms')==['ECDSA_SHA_256'],'kms_public_key_invalid')
        der=_base64(metadata.get('PublicKey'),200)
        try:
            public=serialization.load_der_public_key(der)
            require(isinstance(public,ec.EllipticCurvePublicKey) and isinstance(public.curve,ec.SECP256K1)
                    and public.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)==der,
                    'kms_public_key_invalid')
            raw=public.public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)[1:]
            require(keys.PublicKey(raw).to_address()==self.wallet,'kms_wallet_mismatch')
        except Rejected:raise
        except Exception:raise Rejected('kms_public_key_invalid') from None
        self.public_key=metadata['PublicKey']

    def _call(self, operation, payload):
        try:
            result=self._run(['aws','--profile','peer','--region','us-east-1','kms',operation,
                              '--cli-input-json','file:///dev/stdin','--cli-binary-format','base64','--output','json'],
                             input=canonical(payload).decode(),text=True,capture_output=True,timeout=30,check=False)
            require(result.returncode==0,'kms_broker_unavailable')
            return strict_json(result.stdout.encode(),8192)
        except Rejected:raise
        except Exception:raise Rejected('kms_broker_unavailable') from None

    def __call__(self, request):
        fields(request,{'version','keyId','digest'})
        require(type(request['version']) is int and request['version']==1 and request['keyId']==self.key_id
                and isinstance(request['digest'],str) and re.fullmatch('[0-9a-f]{64}',request['digest']),'kms_request_invalid')
        result=self._call('sign',{'KeyId':self.key_id,'Message':base64.b64encode(bytes.fromhex(request['digest'])).decode(),
                                  'MessageType':'DIGEST','SigningAlgorithm':'ECDSA_SHA_256'})
        fields(result,{'KeyId','Signature','SigningAlgorithm'})
        require(result['KeyId']==self.key_id and result['SigningAlgorithm']=='ECDSA_SHA_256','kms_response_invalid')
        return {'version':1,'keyId':self.key_id,'publicKey':self.public_key,'signature':result['Signature']}


class _RecoveryWallet:
    def __init__(self,signer):self.wallet,self.signer=address(signer.address),signer
    @contextmanager
    def retirement_guard(self):yield
    def sign_retirement_transaction(self,transaction):return self.signer.sign_transaction(transaction)


class OperatorRecovery:
    def __init__(self,policy,rpc,signer,state_path):
        authority=validate_payout_authority(policy['payoutAuthority'])
        require(authority['keyId']==signer.key_id and address(authority['wallet'])==address(signer.address),
                'recovery_authority_mismatch')
        self.policy,self.signer,self.state_path=policy,signer,Path(state_path)
        self.wallet=address(authority['wallet'])
        self.transport=BaseUSDCPayoutTransport(_RecoveryWallet(signer),rpc,pinned_rpc_url=policy['payoutRpc'])
        self.rpc=rpc

    def _load(self):
        if not self.state_path.exists():return None
        require(not self.state_path.is_symlink() and self.state_path.stat().st_size<=8192,'recovery_state_invalid')
        record=strict_json(self.state_path.read_bytes(),8192)
        fields(record,STATE_FIELDS)
        require(type(record['version']) is int and record['version']==1 and record['keyId']==self.signer.key_id
                and record['wallet']==self.wallet and record['policyDigest']==digest(self.policy)
                and type(record['chainId']) is int and record['chainId']==CHAIN_ID and record['token']==USDC_ADDRESS
                and record['recipient']==DEPLOYER_REFUND_ADDRESS,'recovery_state_invalid')
        integer(record['amountMinor'],1,MAX_BUDGET,'recovery_state_invalid')
        integer(record['nonce'],0,2**64-1,'recovery_state_invalid')
        raw=record['signedTransaction']
        require(isinstance(raw,str) and len(raw)%2==0 and re.fullmatch('0x[0-9a-f]{2,2048}',raw),'recovery_state_invalid')
        signed=bytes.fromhex(raw[2:])
        require(self.transport.validate_refund(signed,record['transactionId'],record['amountMinor']), 'recovery_state_invalid')
        require(int.from_bytes(rlp.decode(signed[1:],strict=True)[1],'big')==record['nonce'],'recovery_state_invalid')
        return record,signed

    def _save(self,record):
        # Exclusive creation avoids replacing a competing or already-broadcast identity.
        fd=os.open(self.state_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(canonical(record));stream.flush();os.fsync(stream.fileno())
            directory=os.open(self.state_path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        except Exception:
            # Never broadcast if durability fails; retain partial state for diagnosis.
            raise Rejected('recovery_state_write_failed') from None

    def _nonce(self):
        latest=_quantity(self.rpc.call('eth_getTransactionCount',[self.wallet,'latest']))
        pending=_quantity(self.rpc.call('eth_getTransactionCount',[self.wallet,'pending']))
        require(latest==pending,'recovery_unknown_pending_nonce')
        return integer(latest,0,2**64-1,'recovery_nonce_invalid')

    def _sync_saved(self):
        # A previous attempt may have saved bytes but failed its directory fsync.
        # Re-establish durability before any retry is allowed to broadcast them.
        try:
            fd=os.open(self.state_path,os.O_RDONLY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
            directory=os.open(self.state_path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        except Exception:raise Rejected('recovery_state_write_failed') from None

    def _plan(self):
        amount,gas_balance=self.transport.funding_balances()
        integer(amount,0,MAX_BUDGET,'recovery_balance_limit')
        nonce=self._nonce()
        plan={'wallet':self.wallet,'recipient':DEPLOYER_REFUND_ADDRESS,'amountMinor':amount,'nonce':nonce,
              'chainId':CHAIN_ID,'token':USDC_ADDRESS,'gasBalanceWei':gas_balance}
        if not amount:return plan,None
        block=self.rpc.call('eth_getBlockByNumber',['latest',False])
        require(isinstance(block,dict),'rpc_response_invalid')
        base=_quantity(block.get('baseFeePerGas'))
        priority=min(_quantity(self.rpc.call('eth_maxPriorityFeePerGas',[])),MAX_PRIORITY_FEE_WEI)
        fee=integer(base*2+priority,1,MAX_FEE_WEI,'payout_fee_limit')
        data=refund_data(amount)
        estimate=_quantity(self.rpc.call('eth_estimateGas',[{'from':self.wallet,'to':USDC_ADDRESS,'value':'0x0',
                            'data':'0x'+data.hex(),'maxFeePerGas':hex(fee),'maxPriorityFeePerGas':hex(priority)}]))
        integer(estimate,21000,MAX_GAS,'payout_gas_limit')
        gas=min(MAX_GAS,(estimate*12+9)//10)
        require(gas_balance>=gas*fee,'recovery_gas_insufficient')
        tx={'type':2,'chainId':CHAIN_ID,'nonce':nonce,'to':to_checksum_address(USDC_ADDRESS),'value':0,
            'data':data,'gas':gas,'maxFeePerGas':fee,'maxPriorityFeePerGas':priority,'accessList':[]}
        return {**plan,'gasLimit':gas,'maxFeePerGas':fee,'maxPriorityFeePerGas':priority},tx

    def _confirmed_status(self,txid):
        # An old confirmed refund does not establish that a reused KMS wallet is
        # empty now. Preserve its immutable identity; never silently sign another.
        remaining,_gas=self.transport.funding_balances()
        integer(remaining,0,2**256-1,'rpc_response_invalid')
        return {'state':'confirmed_but_balance_nonzero' if remaining else 'confirmed',
                'transactionId':txid,'remainingAmountMinor':remaining}

    def _reconcile(self,record,signed,execute):
        txid,amount=record['transactionId'],record['amountMinor']
        if self.transport.confirmed_refund(txid,amount):return self._confirmed_status(txid)
        latest=_quantity(self.rpc.call('eth_getTransactionCount',[self.wallet,'latest']))
        pending=_quantity(self.rpc.call('eth_getTransactionCount',[self.wallet,'pending']))
        require(pending>=latest,'recovery_nonce_conflict')
        known=self.rpc.call('eth_getTransactionByHash',[txid])
        require(latest in (record['nonce'],record['nonce']+1),'recovery_nonce_conflict')
        known_identity=isinstance(known,dict) and known.get('hash','').lower()==txid
        require(pending==record['nonce'] or (pending==record['nonce']+1 and isinstance(known,dict)
                and known.get('hash','').lower()==txid),'recovery_unknown_pending_nonce')
        require(latest==record['nonce'] or (known_identity and known.get('blockNumber') is not None),
                'recovery_nonce_conflict')
        if execute and not known_identity:
            self.transport._refund=(signed,txid,amount)
            self.transport.broadcast_refund(signed,txid)
        confirmed=self.transport.confirmed_refund(txid,amount)
        return self._confirmed_status(txid) if confirmed else {'state':'pending','transactionId':txid}

    def run(self,*,execute=False):
        self.state_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        lock_path=Path(str(self.state_path)+'.lock')
        fd=os.open(lock_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            existing=self._load()
            if existing:
                if execute:self._sync_saved()
                return self._reconcile(*existing,execute)
            plan,tx=self._plan()
            if not execute or tx is None:return {'state':'plan' if tx else 'empty',**plan}
            require(self._nonce()==plan['nonce'],'recovery_nonce_conflict')
            result=self.signer.sign_transaction(tx)
            record={'version':1,'keyId':self.signer.key_id,'wallet':self.wallet,'policyDigest':digest(self.policy),
                    'chainId':CHAIN_ID,'token':USDC_ADDRESS,'recipient':DEPLOYER_REFUND_ADDRESS,
                    'amountMinor':plan['amountMinor'],'nonce':plan['nonce'],'signedTransaction':'0x'+result.raw_transaction.hex(),
                    'transactionId':'0x'+result.hash.hex()}
            require(self.transport.validate_refund(result.raw_transaction,record['transactionId'],plan['amountMinor']),
                    'recovery_state_invalid')
            self._save(record)
            return self._reconcile(record,result.raw_transaction,True)
        finally:os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Plan fixed USDC refund from the measured KMS wallet. '
        'Quiesce all other KMS signers before --execute. Does not recover an old RAM-only wallet or sweep ETH.')
    parser.add_argument('--policy',type=Path,default=Path(__file__).with_name('policy.json'))
    parser.add_argument('--state',type=Path,default=Path('.local/revamp/operator-recovery.json'))
    parser.add_argument('--execute',action='store_true',help='sign/save/reconcile the fixed refund; default only plans')
    args=parser.parse_args(argv)
    try:
        from .runtime import RPC
        from .transport import HTTPTransport
        policy=strict_json(args.policy.read_bytes(),1_000_000)
        authority=validate_payout_authority(policy['payoutAuthority'])
        exchange=AWSKMSExchange(authority['keyId'],authority['wallet'])
        signer=KmsSigner(authority['keyId'],authority['wallet'],exchange)
        result=OperatorRecovery(policy,RPC(policy['payoutRpc'],HTTPTransport('direct')),signer,args.state).run(execute=args.execute)
        print(canonical(result).decode())
        return 0
    except Rejected as failure:
        print(canonical({'error':str(failure)}).decode());return 1
    except Exception:
        print('{"error":"recovery_unavailable"}');return 1


if __name__=='__main__':raise SystemExit(main())
