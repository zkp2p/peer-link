"""Contributor client: verify an independently pinned release before encryption."""
import hashlib
import copy
import secrets
import time
import urllib.error
import urllib.request
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from verification.attestation import verify_document
from verification.common import unb64
from .common import Rejected,canonical,digest,fields,require,strict_json
from .channel import encrypt
from .policy import validate_reservation
from .artifacts import validate_archive_record, validate_epoch_descriptor

SAFE_ERRORS = {'campaign_capacity','budget_exhausted','duplicate_recipient','duplicate_account',
               'campaign_unavailable','job_expired','job_replayed','job_not_found','receipt_unavailable',
               'payout_paused','capacity','service_unavailable','invalid_submission','provider_failed',
               'bank_read_failed','insufficient_history','model_rejected','storage_unavailable',
               'insufficient_evidence','unauthenticated_source','source_not_allowed','model_result_invalid',
               'unsafe_artifact','cancelled','consent_required','account_evidence_missing','ambiguous_account',
               'policy_mismatch','stale_evidence','limits_exceeded','invalid_envelope','expired_or_replayed_challenge',
               'interrupted_execution','state_capacity'}
from .acquisition import SOURCE_FAILURES
SAFE_ERRORS.update(SOURCE_FAILURES)
# Every terminal reason the ledger can record is a fixed, data-free code.
from .ledger import REASONS
SAFE_ERRORS.update(REASONS)
JOB_FIELDS = {'jobId','campaignId','state','bindingDigest','expiresAt','rewardMinor','payoutAddress',
              'reason','artifactDigest','transactionId'}
STATE_FIELDS = {'version','jobId','campaignId','request','bindingDigest','epoch','publicKey','releaseDigest','policyDigest'}
DEFAULT_LIMITS = {'maxCalls':1,'maxInputTokens':50000,'maxOutputTokens':2048,'maxBankReads':10,'deadlineSeconds':120}

def release_identity(release):
    # Routine renewal changes the expiry, never the measured/service/policy pins.
    return digest({key:value for key,value in release.items() if key!='expiresAt'})

def safe_failure(body):
    try:
        value=strict_json(body,4096)
        code=value.get('error') if isinstance(value,dict) else None
        return code if isinstance(code,str) and code in SAFE_ERRORS else 'service_unavailable'
    except Exception:return 'service_unavailable'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def campaign_limits(campaign,overrides=None):
    limits=DEFAULT_LIMITS.copy()
    if 'sourceDescriptor' in campaign:limits['maxBankReads']=campaign['sourceDescriptor']['maxReads']
    if 'openSource' in campaign:limits['maxBankReads']=campaign['openSource']['maxReads']
    for name,value in (overrides or {}).items():
        require(name in {'maxOutputTokens','maxInputTokens','deadlineSeconds'} and type(value) is int,'invalid_limits')
        limits[name]=value
    return limits


class Client:
    def __init__(self,service,release,policy):
        require(release.get('status')=='approved' and release.get('expiresAt',0)>time.time(),'release_not_approved')
        require(isinstance(service,str) and service.startswith('https://') and release.get('serviceUrl')==service.rstrip('/'),'service_mismatch')
        require(release.get('policyDigest')==digest(policy),'policy_mismatch')
        self.service,self.release,self.policy=service.rstrip('/'),release,policy
        self.durable='stateAuthority' in policy
        self.receipt_key=None
        self.key=None;self.epoch=None;self.job=None;self.preflight_verified=False
    def call(self,path,body=None):
        request=urllib.request.Request(self.service+path,data=canonical(body) if body is not None else None,
                    headers={'Accept':'application/json','Content-Type':'application/json'},method='POST' if body is not None else 'GET')
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
                require(response.status in (200,202),'service_unavailable')
                result=strict_json(response.read(3_000_001),3_000_000)
                require(isinstance(result,dict),'service_unavailable')
                if 'error' in result:raise Rejected(safe_failure(canonical(result)))
                return result
        except urllib.error.HTTPError as error:
            try:code=safe_failure(error.read(4097))
            except Exception:code='service_unavailable'
            finally:error.close()
            raise Rejected(code) from None
        except Rejected:raise
        except Exception:raise Rejected('service_unavailable') from None
    def verify(self,quote,context,*,fresh_ingress=False):
        fields(quote,{'context','publicKey','attestation'})
        require(quote['context']==context,'context_mismatch')
        key=unb64(quote['publicKey'],1024)
        verify_document(unb64(quote['attestation'],32768),nonce=hashlib.sha256(canonical(context)).digest(),
                        public_key_der=key,release=self.release)
        if self.key is not None and not fresh_ingress:require(self.key==key,'enclave_restarted')
        public=serialization.load_der_public_key(key)
        require(isinstance(public,rsa.RSAPublicKey) and public.key_size==3072,'invalid_public_key')
        self.key=key
        return context
    def preflight(self):
        self.preflight_verified=False
        nonce=secrets.token_hex(32)
        quote=self.call('/v1/attest',{'nonce':nonce})
        context=quote.get('context',{})
        fields(context,{'protocol','nonce','policyDigest','epoch'} | ({'receiptPublicKey'} if self.durable else set()))
        require(context['protocol']==('peerlink-epoch-v2' if self.durable else 'peerlink-epoch-v1') and context['nonce']==nonce and context['policyDigest']==digest(self.policy),'context_mismatch')
        self.verify(quote,context,fresh_ingress=self.durable)
        if self.durable:
            receipt_key=unb64(context['receiptPublicKey'],1024)
            public=serialization.load_der_public_key(receipt_key)
            require(isinstance(public,rsa.RSAPublicKey) and public.key_size==3072,'invalid_public_key')
            if self.receipt_key is not None:require(receipt_key==self.receipt_key,'receipt_signer_changed')
            self.receipt_key=receipt_key
        validate_epoch_descriptor(context['epoch'],self.policy)
        if self.epoch is not None:require(context['epoch']==self.epoch,'enclave_restarted')
        self.epoch=context['epoch']
        self.preflight_verified=True
        return {'verified':True,'releaseDigest':digest(self.release),'measurements':copy.deepcopy(self.release.get('measurements',{})),
                'policyDigest':digest(self.policy),'epoch':self.epoch}
    def availability(self):
        """Unsigned capacity hint from the service; only a reservation admits a job."""
        result=self.call('/v1/campaigns')
        require(result.get('policyDigest')==digest(self.policy),'policy_mismatch')
        value=result.get('availability')
        require(isinstance(value,dict) and type(value.get('budgetRemainingMinor')) is int
                and isinstance(value.get('campaigns'),list),'service_unavailable')
        known={item['id'] for item in self.policy['campaigns']}
        slots={}
        for item in value['campaigns']:
            require(isinstance(item,dict) and item.get('campaignId') in known
                    and type(item.get('slotsRemaining')) is int,'service_unavailable')
            slots[item['campaignId']]=item['slotsRemaining']
        return {'budgetRemainingMinor':value['budgetRemainingMinor'],'slotsRemaining':slots,'verified':False}
    def reserve(self,campaign_id,payout,provider,model,privacy,*,consent,on_reserved=None,base_url=None,limits=None):
        require(consent is True,'consent_required');require(self.job is None,'job_context_exists');self.preflight()
        campaign=next((item for item in self.policy['campaigns'] if item['id']==campaign_id),None)
        require(campaign is not None,'campaign_unavailable')
        now=int(time.time())
        request={'version':1,'campaignId':campaign_id,'payoutAddress':payout,'provider':provider,'model':model,
                 'privacyMode':privacy,'consent':True,'policyDigest':digest(campaign),'expiresAt':now+600,
                 'limits':campaign_limits(campaign,limits)}
        if base_url is not None:request['inferenceBaseUrl']=base_url
        validate_reservation(campaign,request,now)
        status=self.call('/v1/reservations',request)
        fields(status,JOB_FIELDS)
        require(isinstance(status['jobId'],str) and len(status['jobId'])==32 and all(c in '0123456789abcdef' for c in status['jobId']),'binding_mismatch')
        expected=digest({'jobId':status['jobId'],'campaign':campaign,'request':request})
        require(status['bindingDigest']==expected and status['payoutAddress']==payout.lower() and status['rewardMinor']==campaign['rewardMinor'],'binding_mismatch')
        from verification.common import b64
        self.job={'version':2 if self.durable else 1,'jobId':status['jobId'],'campaignId':campaign_id,
                  'request':copy.deepcopy(request),'bindingDigest':expected,'epoch':copy.deepcopy(self.epoch),
                  'releaseDigest':release_identity(self.release) if self.durable else digest(self.release),'policyDigest':digest(self.policy)}
        if self.durable:self.job['receiptPublicKey']=b64(self.receipt_key)
        else:self.job['publicKey']=b64(self.key)
        if on_reserved is not None:on_reserved(copy.deepcopy(self.job))
        return self.provisional(status)

    def submit_reserved(self,payload,*,consent):
        require(consent is True,'consent_required');require(self.job is not None,'job_context_required')
        self.preflight()
        status=self.call('/v1/jobs/'+self.job['jobId']);self.provisional(status)
        require(status['state']=='reserved','job_replayed')
        nonce=secrets.token_hex(32)
        quote=self.call('/v1/challenges',{'jobId':self.job['jobId'],'nonce':nonce})
        context=quote.get('context',{})
        from .channel import context_fields
        context_fields(context)
        require(context['protocol']==('peerlink-transcript-v2' if self.durable else 'peerlink-transcript-v1')
                and context['jobId']==self.job['jobId'] and context['bindingDigest']==self.job['bindingDigest']
                and context['clientNonce']==nonce and context['policyDigest']==digest(self.policy)
                and context['epochId']==self.epoch['epochId'] and context['wallet']==self.epoch['payoutWallet']
                and time.time()<context['expiresAt']<=self.job['request']['expiresAt'],'context_mismatch')
        if self.durable:require(context['receiptKeyDigest']==hashlib.sha256(self.receipt_key).hexdigest(),'context_mismatch')
        self.verify(quote,context)
        envelope=encrypt(self.key,context,payload,consent=True)
        return self.provisional(self.call('/v1/submissions',envelope))

    def contribute(self,campaign_id,payout,provider,model,privacy,payload,*,consent,on_reserved=None,base_url=None,limits=None):
        self.reserve(campaign_id,payout,provider,model,privacy,consent=consent,on_reserved=on_reserved,
                     base_url=base_url,limits=limits)
        return self.submit_reserved(payload,consent=consent)

    def restore(self,state):
        # This is a local public recovery handle, never proof of a fresh quote.
        fields(state,(STATE_FIELDS-{'publicKey'} | {'receiptPublicKey'}) if self.durable else STATE_FIELDS)
        require(state['version']==(2 if self.durable else 1) and state['releaseDigest']==(release_identity(self.release) if self.durable else digest(self.release))
                and state['policyDigest']==digest(self.policy),'state_mismatch')
        require(isinstance(state['jobId'],str) and len(state['jobId'])==32
                and all(c in '0123456789abcdef' for c in state['jobId']),'state_mismatch')
        campaign=next((item for item in self.policy['campaigns'] if item['id']==state['campaignId']),None)
        require(campaign is not None,'state_mismatch')
        request=state['request']
        require(isinstance(request,dict) and type(request.get('expiresAt')) is int,'state_mismatch')
        # Validate original terms at their inferred reservation time; this does not
        # verify an old quote or revive an expired job. A fresh preflight follows.
        validate_reservation(campaign,request,request['expiresAt']-600)
        require(state['bindingDigest']==digest({'jobId':state['jobId'],'campaign':campaign,'request':request}),'state_mismatch')
        validate_epoch_descriptor(state['epoch'],self.policy,code='state_mismatch')
        if self.durable:
            self.key=None;self.receipt_key=unb64(state['receiptPublicKey'],1024)
        else:self.key=unb64(state['publicKey'],1024)
        self.epoch=copy.deepcopy(state['epoch']);self.job=copy.deepcopy(state)
        self.preflight_verified=False
    def provisional(self,status):
        require(self.job is not None,'job_context_required');fields(status,JOB_FIELDS)
        for field in ('jobId','campaignId','bindingDigest'):
            require(status[field]==self.job[field],'binding_mismatch')
        require(status['payoutAddress']==self.job['request']['payoutAddress'].lower()
                and status['rewardMinor']==next(c['rewardMinor'] for c in self.policy['campaigns'] if c['id']==self.job['campaignId'])
                and status['expiresAt']==self.job['request']['expiresAt'],'binding_mismatch')
        require(status['state'] in {'reserved','submitted','verifying','rejected','expired','cancelled','accepted','payout_pending','paid'},'binding_mismatch')
        require(status['reason'] is None or isinstance(status['reason'],str) and status['reason'] in SAFE_ERRORS,'service_unavailable')
        # Return no unsigned server free text or a misleading terminal paid state.
        return {'jobId':self.job['jobId'],'state':'unverified','reportedState':status['state'],
                'verified':False,'reason':status['reason'],'nextAction':'verify_receipt' if status['state']=='paid' else
                    'terminal_outcome_reported' if status['state'] in {'rejected','expired','cancelled'} else 'poll_same_job'}
    def status(self,job_id):
        require(self.job is not None and job_id==self.job['jobId'],'job_context_required')
        self.preflight()
        try:result=self.provisional(self.call('/v1/jobs/'+job_id))
        except Rejected as error:
            if str(error)=='job_not_found' and time.time()>=self.job['request']['expiresAt']:
                return {'jobId':job_id,'state':'unverified','reportedState':'unavailable_after_expiry','verified':False,
                        'reason':'job_not_found','nextAction':'terminal_record_unavailable'}
            raise
        if result['reportedState']=='paid':
            signed=self.receipt(job_id)
            return {'jobId':job_id,'state':signed['payload']['job']['state'],'verified':True,'receipt':signed}
        return result
    def receipt(self,job_id):
        require(self.key is not None and self.epoch is not None and self.preflight_verified,'preflight_required')
        require(self.release.get('status')=='approved' and self.release.get('expiresAt',0)>time.time(),'release_not_approved')
        require(self.job is not None and self.job['jobId']==job_id,'job_context_required')
        signed=self.call('/v1/jobs/'+job_id+'/receipt');fields(signed,{'payload','signature'})
        record=signed['payload']
        require(record['job']['jobId']==job_id and record['epoch']==self.epoch and record['policyDigest']==digest(self.policy),'receipt_mismatch')
        key=serialization.load_der_public_key(self.receipt_key if self.durable else self.key)
        require(isinstance(key,rsa.RSAPublicKey),'invalid_public_key')
        try:key.verify(unb64(signed['signature'],512),canonical(record),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())
        except Exception:raise Rejected('receipt_signature_invalid') from None
        campaign=next(item for item in self.policy['campaigns'] if item['id']==self.job['campaignId'])
        validate_archive_record(campaign,record,policy=self.policy)
        request=self.job['request']
        require(record['job']['bindingDigest']==self.job['bindingDigest']
                and record['job']['payoutAddress']==request['payoutAddress'].lower()
                and record['job']['expiresAt']==request['expiresAt'],'receipt_mismatch')
        require(record['inference'].get('baseUrl')==request.get('inferenceBaseUrl'),'receipt_mismatch')
        require(all(record['inference'][name]==request[name] for name in ('provider','model','privacyMode'))
                and record['inference']['inputTokens']<=request['limits']['maxInputTokens']
                and record['inference']['outputTokens']<=request['limits']['maxOutputTokens'],'receipt_mismatch')
        return signed
