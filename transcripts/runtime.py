"""Measured PeerLink runtime: no host secrets, no arbitrary code or bank writes."""
import argparse
import copy
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
from .artifacts import extract_artifact,validate_archive_record,validate_epoch_descriptor
from .ledger import REASONS
from .storage import ArchiveClient
from .wire import receive,send

ROOT=Path(__file__).parent
SETTLEMENT_RETRY_SECONDS=120
SETTLEMENT_MAX_ATTEMPTS=60
SETTLEMENT_RETRY_DELAY=2
TRANSIENT_SETTLEMENT_ERRORS=frozenset({'payout_rpc_unavailable','http_transport_failed',
    'storage_unavailable','kms_broker_unavailable','request_timeout','response_incomplete',
    'egress_unavailable','http_request_failed','relay_refused','connection_closed',
    'state_unavailable','state_authority_unavailable','credentials_unavailable','state_commit_uncertain'})

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


def bootstrap_wallet_gate(config,wallet,rpc):
    # Fixed measured genesis witness, never an inferred baseline. A lost head
    # beside a funded/used wallet requires explicit operator recovery.
    from .epoch import USDC_ADDRESS
    from .eth_payout import _quantity
    require(_quantity(rpc.call('eth_chainId',[]))==8453,'payout_chain_mismatch')
    require(all(_quantity(rpc.call('eth_getTransactionCount',[wallet,tag]))==config['initialWalletNonce']
                for tag in ('latest','pending')),'state_bootstrap_wallet_used')
    balance=rpc.call('eth_call',[{'to':USDC_ADDRESS,'data':'0x70a08231'+wallet[2:].rjust(64,'0')},'latest'])
    require(isinstance(balance,str) and len(balance)==66 and balance.startswith('0x')
            and all(char in '0123456789abcdefABCDEF' for char in balance[2:]) and int(balance,16)==0,
            'state_bootstrap_wallet_used')


class Runtime:
    def __init__(self,policy,epoch,transport,archive,attester=attest):
        from .providers import SYSTEM_PROMPT
        require(policy['promptDigest']==hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),'prompt_mismatch')
        validate_epoch_descriptor(epoch.public_descriptor(), policy)
        self.policy,self.policy_digest=policy,digest(policy)
        self.epoch,self.ledger,self.transport,self.archive=epoch,epoch.ledger,transport,archive
        self.channel,self.attester=Channel(),attester
        self.durable=getattr(epoch,"durable",False)
        self.receipt_signer=epoch.receipt_signer if self.durable else self.channel
        self.receipts={};self.pending_records={};self.settlement_lock=threading.Lock();self.operator_nonces=set();self.operator_lock=threading.Lock()
        self.jobs=threading.BoundedSemaphore(2)
        self.funding_preflight=None
        self.rpc=RPC(policy['payoutRpc'],transport)
        self.payment=BaseUSDCPayoutTransport(epoch,self.rpc,pinned_rpc_url=policy['payoutRpc'])
        self.coordinator=PayoutCoordinator(self.ledger,self.payment)
        self.retirement=RetirementCoordinator(epoch,self.payment)
        if self.durable:self.restore_records()

    def restore_records(self):
        for job in self.ledger.recovery_jobs():
            self.pending_records[job]=self.ledger.archive_record(job)
            signed=self.ledger.restored_receipt(job)
            if signed is not None:self.receipts[job]=signed

    def restore_funding_gate(self):
        self.payment.check_continuity()
        usdc,gas=self.payment.funding_balances()
        rows=self.ledger.payment_rows()
        spent=0
        for row in rows:
            if row['state']=='paid':spent+=row['reward']
            elif row['state']=='payout_pending' and self.payment.confirmed(row['tx_id'],row['recipient'],row['reward']):spent+=row['reward']
        required=self.epoch.budget_minor-spent
        require(usdc>=required and gas>0,'epoch_funding_mismatch')

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
            context={'protocol':'peerlink-epoch-v2' if self.durable else 'peerlink-epoch-v1',
                     'nonce':body['nonce'],'policyDigest':self.policy_digest,'epoch':self.epoch.public_descriptor()}
            if self.durable:context['receiptPublicKey']=b64(self.receipt_signer.public_key_der)
            return self.quote(context)
        if command=='operator':return self.operator(body)
        if command=='reserve':
            self.epoch.require_admission()
            campaign=next((item for item in self.policy['campaigns'] if item['id']==body.get('campaignId')),None)
            require(campaign is not None,'campaign_unavailable')
            return self.ledger.reserve(campaign,body,int(time.time()))
        if command=='challenge':
            fields(body,{'jobId','nonce'})
            status=self.ledger.status(body['jobId']);self.epoch.require_admission()
            context=self.channel.challenge(status,policy_digest=self.policy_digest,epoch_id=self.epoch.epoch_id,wallet=self.epoch.wallet,client_nonce=body['nonce'],
                receipt_key_digest=hashlib.sha256(self.receipt_signer.public_key_der).hexdigest() if self.durable else None)
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
        if command=='status':
            status=self.ledger.status(body['jobId'])
            if self.durable and status['state'] in {'accepted','payout_pending','paid'}:
                self.restore_records()
            return status
        if command=='artifact':return self.ledger.artifact(body['jobId'])
        if command=='receipt':
            if self.durable:
                restored=self.ledger.restored_receipt(body['jobId'])
                if restored is not None:self.receipts[body['jobId']]=restored
            require(body['jobId'] in self.receipts,'receipt_unavailable');return self.receipts[body['jobId']]
        raise Rejected('route_not_found')

    def operator(self,body):
        fields(body,{'payload','signature'});value=body['payload']
        fields(value,{'action','epochId','wallet','nonce','expiresAt'})
        require(value['action'] in {'activate','pause','resume','reconcile','retire','preflight'},'invalid_operator_action')
        require(value['epochId']==self.epoch.epoch_id and value['wallet']==self.epoch.wallet,'epoch_binding_mismatch')
        require(type(value['expiresAt']) is int and time.time()<value['expiresAt']<=time.time()+120,'operator_expired')
        require(isinstance(value['nonce'],str) and len(value['nonce'])==64,'invalid_nonce')
        try:Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.policy['operatorPublicKey'])).verify(unb64(body['signature'],64),canonical(value))
        except Exception:raise Rejected('operator_signature_invalid') from None
        with self.operator_lock:
            require(value['nonce'] not in self.operator_nonces and len(self.operator_nonces)<1000,'operator_replayed')
            if self.durable:self.ledger.consume_operator_nonce(value['nonce'],value['expiresAt'],int(time.time()))
            self.operator_nonces.add(value['nonce'])
            if value['action']=='preflight':
                usdc,gas=self.payment.funding_balances()
                require(usdc==0,'preflight_requires_unfunded')
                nonce=int(self.rpc.call('eth_getTransactionCount',[self.epoch.wallet,'pending']),16)
                probe=self.epoch.check_payout_signing(nonce)
                self.funding_preflight=digest(self.epoch.public_descriptor())
                return {'health':self.dispatch('health',{}),'preflight':{
                    **probe,'usdcBalanceMinor':usdc,'gasBalanceWei':gas,'pendingNonce':nonce}}
            if value['action']=='pause':self.epoch.pause()
            elif value['action']=='resume':
                if self.durable:self.restore_funding_gate()
                self.epoch.resume_after_operator_verification(self.epoch.epoch_id)
                if self.durable:threading.Thread(target=self.reconcile_pending,daemon=True).start()
            elif value['action']=='reconcile':
                threading.Thread(target=self.reconcile_pending,daemon=True).start()
            elif value['action']=='retire':
                self.epoch.begin_retirement_after_operator_verification(self.epoch.epoch_id,now=int(time.time()))
                threading.Thread(target=self.reconcile_retirement,daemon=True).start()
            else:
                require(self.funding_preflight==digest(self.epoch.public_descriptor()),'funding_preflight_required')
                if self.durable:self.payment.check_continuity()
                usdc,gas=self.payment.funding_balances()
                self.epoch.activate_after_operator_verification(self.epoch.epoch_id,self.epoch.wallet,usdc_balance_minor=usdc,gas_balance_wei=gas)
        return self.dispatch('health',{})

    def archive_settlement(self,job_id,campaign,record):
        validate_archive_record(campaign,record,policy=self.policy)
        # Channel.sign retains its input by reference. A failed later archive
        # must not mutate the payload of an already-published valid signature.
        signed=self.ledger.restored_receipt(job_id) if self.durable else None
        if signed is None or signed['payload']!=record:
            signed=(self.receipt_signer if self.durable else self.channel).sign(copy.deepcopy(record))
            if self.durable:self.ledger.save_receipt(job_id,signed)
        self.archive.persist(signed)
        self.receipts[job_id]=signed

    def settle_attempt(self,job_id):
        with self.settlement_lock:
            if job_id not in self.pending_records:return True
            status=self.ledger.status(job_id)
            # Publishing an already-paid durable receipt uses no payout key and
            # must remain recoverable while a restarted/retired epoch is paused.
            if not (self.durable and status['state']=='paid'):self.epoch.require_active()
            record=self.pending_records[job_id]
            campaign=self.ledger.terms(job_id)['campaign']
            record['job']=self.ledger.status(job_id)
            if self.receipts.get(job_id,{}).get('payload')!=record:
                self.archive_settlement(job_id,campaign,record)
            if record['job']['state']!='paid':
                self.coordinator.reconcile(job_id,now=int(time.time()))
                record['job']=self.ledger.status(job_id)
                if self.receipts[job_id]['payload']!=record:
                    self.archive_settlement(job_id,campaign,record)
            if record['job']['state']=='paid':
                self.pending_records.pop(job_id,None)
                return True
            return False

    def settle(self,job_id):
        # Only the accepted RAM record/ledger identity is retried. Bank reads,
        # grading and contribution admission are never part of this loop.
        # Stop starting attempts after either bound; each in-flight transport
        # call also retains its existing timeout. Operator reconcile can resume
        # an obligation retained after exhaustion, without a second submission.
        deadline=time.monotonic()+SETTLEMENT_RETRY_SECONDS
        for attempt in range(SETTLEMENT_MAX_ATTEMPTS):
            if time.monotonic()>=deadline:return
            try:
                if self.settle_attempt(job_id):return
            except Rejected as error:
                if str(error) not in TRANSIENT_SETTLEMENT_ERRORS:raise
            except OSError:
                # ArchiveClient's bounded VSOCK socket can raise OSError directly.
                pass
            remaining=deadline-time.monotonic()
            if remaining<=0 or attempt+1==SETTLEMENT_MAX_ATTEMPTS:return
            time.sleep(min(SETTLEMENT_RETRY_DELAY,remaining))

    def reconcile_pending(self):
        if self.durable:self.restore_records()
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
            if self.durable:
                from .aws_state import MAX_RECORD
                require(len(canonical(artifact))<=MAX_RECORD-8192,'unsafe_artifact')
                self.ledger.check_account(job_id,reads,dedup_key=self.epoch._dedup_key,now=int(time.time()))
                self.payment.preflight_recipient(request['payoutAddress'],campaign['rewardMinor'])
            provider=ProviderClient(campaign,request,payload['inferenceKey'],transport=self.transport)
            grade=provider.grade(artifact,int(time.time()))
            require(time.time()-start<=request['limits']['deadlineSeconds'],'limits_exceeded')
            evidence={'epoch':self.epoch.public_descriptor(),'modelResult':grade,
                      'inference':provider.metadata,'policyDigest':self.policy_digest}
            if self.durable:self.epoch.accept(job_id,reads,grade,now=int(time.time()),evidence=evidence,policy=self.policy)
            else:self.epoch.accept(job_id,reads,grade,now=int(time.time()))
            record={'version':1,'epoch':self.epoch.public_descriptor(),'job':self.ledger.status(job_id),
                    'artifact':artifact,'modelResult':grade,'inference':provider.metadata,'policyDigest':self.policy_digest}
            self.pending_records[job_id]=record
            # Settlement needs only the redacted record and ledger payment.
            # Release credentials/raw history before any potentially long retry.
            bank.close();provider.close();payload.clear();reads=None
            self.settle(job_id)
        except Rejected as error:
            if str(error) in TRANSIENT_SETTLEMENT_ERRORS and self.durable:
                # An uncertain accepted CAS is retained by Ledger. Do not turn a
                # paid grade into a rejection while its durable outcome is unknown.
                return
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
    from .kms_signer import KmsSigner
    from .policy import validate_payout_authority
    parser=argparse.ArgumentParser();parser.add_argument('--vsock-port',type=int,default=5100);parser.add_argument('--egress-port',type=int,default=5101)
    args=parser.parse_args()
    policy=json.loads((ROOT/'policy.json').read_text())
    authority=validate_payout_authority(policy['payoutAuthority'])
    def kms_exchange(request):
        with socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM) as connection:
            connection.settimeout(20);connection.connect((3,5103))
            send(connection,request)
            return receive(connection)
    signer=KmsSigner(authority['keyId'],authority['wallet'],kms_exchange)
    transport=HTTPTransport(mode='vsock')
    state_anchor,snapshot=None,None
    if 'stateAuthority' in policy:
        from .aws_state import AWS,Authority,Credentials,Master,StateAnchor,decode
        config=policy['stateAuthority']
        aws=AWS(config,transport,Credentials(config['credentialRoleArn']))
        state_authority=Authority(config,aws);head=state_authority.load()
        if head is None:bootstrap_wallet_gate(config,authority['wallet'],RPC(policy['payoutRpc'],transport))
        wrapped=decode(head['wrappedMaster'],6144) if head else None
        master,wrapped=Master(config,digest(policy),authority['wallet'],aws,attest).obtain(wrapped)
        state_anchor=StateAnchor(config,digest(policy),authority['wallet'],master,wrapped,state_authority,head)
        snapshot=state_anchor.open(head) if head else None
        master=None
    runtime=Runtime(policy,BootEpoch.create(signer,budget_minor=policy['pilotBudgetMinor'],
                    state_anchor=state_anchor,initial_snapshot=snapshot),transport,ArchiveClient())
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
