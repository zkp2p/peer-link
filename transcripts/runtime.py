"""Measured PeerLink runtime: no host secrets, no arbitrary code or bank writes."""
import argparse
import hashlib
import json
import secrets
import socket
import threading
import time
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from verification.common import b64,unb64
from verification.nsm import attest
from .common import Rejected,canonical,digest,fields,require,strict_json
from .channel import Channel
from .epoch import BootEpoch
from .eth_payout import BaseUSDCPayoutTransport
from .payout import PayoutCoordinator, RetirementCoordinator
from .artifacts import extract_artifact,validate_archive_record
from .ledger import REASONS
from .storage import ArchiveClient
from .wire import receive,send

ROOT=Path(__file__).parent

class RPC:
    def __init__(self,endpoint,transport):self.endpoint,self.transport=endpoint,transport
    def call(self,method,params):
        identity=secrets.token_hex(8)
        body=canonical({'jsonrpc':'2.0','id':identity,'method':method,'params':params})
        response=self.transport.request('POST',self.endpoint,headers={'Content-Type':'application/json'},body=body,timeout=15,max_bytes=1_000_000)
        require(response.status==200 and response.tls_verified,'payout_rpc_unavailable')
        data=strict_json(response.body,1_000_000)
        require(data.get('jsonrpc')=='2.0' and data.get('id')==identity and 'error' not in data and 'result' in data,'payout_rpc_unavailable')
        return data['result']


class Runtime:
    def __init__(self,policy,epoch,transport,archive,attester=attest):
        from .providers import SYSTEM_PROMPT
        require(policy['promptDigest']==hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),'prompt_mismatch')
        self.policy,self.policy_digest=policy,digest(policy)
        self.epoch,self.ledger,self.transport,self.archive=epoch,epoch.ledger,transport,archive
        self.channel,self.attester=Channel(),attester
        self.receipts={};self.pending_records={};self.settlement_lock=threading.Lock();self.operator_nonces=set();self.operator_lock=threading.Lock()
        self.jobs=threading.BoundedSemaphore(2)
        self.rpc=RPC(policy['payoutRpc'],transport)
        self.payment=BaseUSDCPayoutTransport(epoch,self.rpc,pinned_rpc_url=policy['payoutRpc'])
        self.coordinator=PayoutCoordinator(self.ledger,self.payment)
        self.retirement=RetirementCoordinator(epoch,self.payment)

    def quote(self,context):
        document=self.attester(hashlib.sha256(canonical(context)).digest(),self.channel.public_key_der,bytes.fromhex(self.policy_digest))
        return {'context':context,'publicKey':b64(self.channel.public_key_der),'attestation':b64(document)}

    def dispatch(self,command,body):
        if command=='health':
            active=True
            try:self.epoch.require_admission()
            except Rejected:active=False
            return {'service':'peerlink-transcripts','version':1,'mode':'nitro-pilot','accepting':active,
                    'policyDigest':self.policy_digest,'epoch':self.epoch.public_descriptor(),
                    'retirement':self.epoch.retirement_status()}
        if command=='release':
            # Approval/PCR pins are published after building this image. They cannot
            # be embedded in the image whose measurements they approve.
            return {'version':1,'status':'discovery_only','policyDigest':self.policy_digest,
                    'releaseSource':'https://github.com/zkp2p/peer-link/blob/main/transcripts/release.json'}
        if command=='campaigns':return {'policyDigest':self.policy_digest,'campaigns':self.policy['campaigns']}
        if command=='attest':
            fields(body,{'nonce'});require(isinstance(body['nonce'],str) and len(body['nonce'])==64 and all(c in '0123456789abcdef' for c in body['nonce']),'invalid_nonce')
            return self.quote({'protocol':'peerlink-epoch-v1','nonce':body['nonce'],'policyDigest':self.policy_digest,'epoch':self.epoch.public_descriptor()})
        if command=='operator':return self.operator(body)
        if command=='reserve':
            self.epoch.require_admission()
            campaign=next((item for item in self.policy['campaigns'] if item['id']==body.get('campaignId')),None)
            require(campaign is not None,'campaign_unavailable')
            return self.ledger.reserve(campaign,body,int(time.time()))
        if command=='challenge':
            fields(body,{'jobId','nonce'})
            status=self.ledger.status(body['jobId']);self.epoch.require_admission()
            context=self.channel.challenge(status,policy_digest=self.policy_digest,epoch_id=self.epoch.epoch_id,wallet=self.epoch.wallet,client_nonce=body['nonce'])
            return self.quote(context)
        if command=='submit':
            self.epoch.require_admission();require(self.jobs.acquire(blocking=False),'capacity')
            try:
                # Decryption precedes state mutation; only a valid, single-use ciphertext can submit.
                payload=self.channel.decrypt_once(body);context=body['context']
                fields(payload,{'credential','profileId','recipe','inferenceKey','notes','transcript'})
                require(isinstance(payload['notes'],str) and len(payload['notes'])<=32768,'invalid_submission')
                require(isinstance(payload['inferenceKey'],str) and 8<=len(payload['inferenceKey'])<=4096,'invalid_submission')
                status=self.ledger.submit(context['jobId'],context['bindingDigest'],int(time.time()))
                threading.Thread(target=self.process,args=(context['jobId'],payload),daemon=True).start()
                return status
            except BaseException:self.jobs.release();raise
        fields(body,{'jobId'})
        if command=='status':return self.ledger.status(body['jobId'])
        if command=='artifact':return self.ledger.artifact(body['jobId'])
        if command=='receipt':
            require(body['jobId'] in self.receipts,'receipt_unavailable');return self.receipts[body['jobId']]
        raise Rejected('route_not_found')

    def operator(self,body):
        fields(body,{'payload','signature'});value=body['payload']
        fields(value,{'action','epochId','wallet','nonce','expiresAt'})
        require(value['action'] in {'activate','pause','resume','reconcile','retire'},'invalid_operator_action')
        require(value['epochId']==self.epoch.epoch_id and value['wallet']==self.epoch.wallet,'epoch_binding_mismatch')
        require(type(value['expiresAt']) is int and time.time()<value['expiresAt']<=time.time()+120,'operator_expired')
        require(isinstance(value['nonce'],str) and len(value['nonce'])==64,'invalid_nonce')
        try:Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.policy['operatorPublicKey'])).verify(unb64(body['signature'],64),canonical(value))
        except Exception:raise Rejected('operator_signature_invalid') from None
        with self.operator_lock:
            require(value['nonce'] not in self.operator_nonces and len(self.operator_nonces)<1000,'operator_replayed')
            self.operator_nonces.add(value['nonce'])
            if value['action']=='pause':self.epoch.pause()
            elif value['action']=='resume':self.epoch.resume_after_operator_verification(self.epoch.epoch_id)
            elif value['action']=='reconcile':
                threading.Thread(target=self.reconcile_pending,daemon=True).start()
            elif value['action']=='retire':
                self.epoch.begin_retirement_after_operator_verification(self.epoch.epoch_id,now=int(time.time()))
                threading.Thread(target=self.reconcile_retirement,daemon=True).start()
            else:
                usdc,gas=self.payment.funding_balances()
                self.epoch.activate_after_operator_verification(self.epoch.epoch_id,self.epoch.wallet,usdc_balance_minor=usdc,gas_balance_wei=gas)
        return self.dispatch('health',{})

    def settle(self,job_id):
        with self.settlement_lock:
            self.epoch.require_active()
            record=self.pending_records[job_id]
            campaign=self.ledger.terms(job_id)['campaign']
            validate_archive_record(campaign,record)
            signed=self.channel.sign(record)
            self.archive.persist(signed)
            self.receipts[job_id]=signed
            for _ in range(30):
                result=self.coordinator.reconcile(job_id,now=int(time.time()))
                if result['state']=='paid':break
                time.sleep(2)
            record['job']=self.ledger.status(job_id)
            validate_archive_record(campaign,record)
            signed=self.channel.sign(record)
            self.archive.persist(signed)
            self.receipts[job_id]=signed
            if record['job']['state']=='paid':self.pending_records.pop(job_id,None)

    def reconcile_pending(self):
        for job_id in tuple(self.pending_records):
            try:self.settle(job_id)
            except Exception:pass

    def reconcile_retirement(self):
        self.reconcile_pending()
        with self.settlement_lock:
            # A paid receipt still awaiting durable archive blocks wallet retirement.
            if self.pending_records:return
            for _ in range(30):
                try:
                    result=self.retirement.reconcile()
                    if result['state']=='refunded':return
                except Exception:return
                time.sleep(2)

    def process(self,job_id,payload):
        from .transport import BankClient
        from .providers import ProviderClient
        try:
            terms=self.ledger.terms(job_id);campaign,request=terms['campaign'],terms['request']
            start=int(time.time());self.ledger.begin_verification(job_id,start)
            bank=BankClient(campaign,payload['credential'],transport=self.transport,profile_id=payload['profileId'],max_reads=request['limits']['maxBankReads'])
            reads=bank.acquire(job_id,payload['recipe'],start)
            artifact=extract_artifact(campaign,reads)
            provider=ProviderClient(campaign,request,payload['inferenceKey'],transport=self.transport)
            grade=provider.grade(artifact,int(time.time()))
            require(time.time()-start<=request['limits']['deadlineSeconds'],'limits_exceeded')
            self.epoch.accept(job_id,reads,grade,now=int(time.time()))
            record={'version':1,'epoch':self.epoch.public_descriptor(),'job':self.ledger.status(job_id),
                    'artifact':artifact,'modelResult':grade,'inference':provider.metadata,'policyDigest':self.policy_digest}
            self.pending_records[job_id]=record
            self.settle(job_id)
        except Rejected as error:
            status=self.ledger.status(job_id)
            if status['state'] in {'reserved','submitted','verifying'}:
                code=str(error) if str(error) in REASONS else 'invalid_submission'
                self.ledger.reject(job_id,code)
            # Accepted/pending jobs retain their obligation. No exception message can leak data.
        except Exception:
            status=self.ledger.status(job_id)
            if status['state'] in {'reserved','submitted','verifying'}:self.ledger.reject(job_id,'invalid_submission')
        finally:
            if 'bank' in locals():bank.close()
            if 'provider' in locals():provider.close()
            payload.clear();self.jobs.release()


def main():
    from .transport import HTTPTransport
    parser=argparse.ArgumentParser();parser.add_argument('--vsock-port',type=int,default=5100);parser.add_argument('--egress-port',type=int,default=5101)
    args=parser.parse_args()
    policy=json.loads((ROOT/'policy.json').read_text())
    runtime=Runtime(policy,BootEpoch.create(),HTTPTransport(mode='vsock'),ArchiveClient())
    with socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM) as listener:
        listener.bind((socket.VMADDR_CID_ANY,args.vsock_port));listener.listen(20)
        while True:
            connection,peer=listener.accept()
            with connection:
                try:
                    require(peer[0]==3,'ingress_denied');connection.settimeout(20)
                    message=receive(connection);fields(message,{'command','body'})
                    result=runtime.dispatch(message['command'],message['body'])
                except Rejected as error:result={'error':str(error)}
                except Exception:result={'error':'service_unavailable'}
                try:send(connection,result)
                except Exception:pass

if __name__=='__main__':main()
