"""Contributor commands. Secrets use owner TTY prompts or trusted local stdin, never arguments."""
import argparse
import getpass
import io
import json
import os
import sys
import time
import warnings
from pathlib import Path
from .client import Client,DEFAULT_LIMITS,campaign_limits
from .common import Rejected,canonical,digest,fields,require,strict_json
from .hints import hint
from .policy import CUSTOM_PROVIDER,route_allows,validate_campaign,validate_reservation


def terms(release,policy,campaign_id=None,provider=None,model=None,privacy='provider_visible'):
    """Offline consent preview, never a claim that a slot or reward is reserved."""
    from .epoch import CHAIN_ID,USDC_ADDRESS
    from .providers import OPENROUTER_UPSTREAMS,NEAR_VISIBLE_UPSTREAMS
    campaign=next((item for item in policy['campaigns'] if campaign_id is None or item['id']==campaign_id),None)
    require(campaign is not None,'campaign_unavailable');validate_campaign(campaign)
    route=next((item for item in campaign['inferenceRoutes'] if provider is None or item['provider']==provider),None)
    require(route is not None,'provider_not_allowed')
    # A "*" route takes any model the contributor names for that provider.
    model=model or ('ANY_MODEL_YOU_CHOOSE' if route['models']==['*'] else route['models'][0])
    require(model=='ANY_MODEL_YOU_CHOOSE' or route_allows(campaign,route['provider'],model,privacy),'provider_not_allowed')
    approved=release.get('status')=='approved' and release.get('expiresAt',0)>time.time()
    return {'campaignId':campaign['id'],'bankId':campaign['bankId'],'campaignStatus':campaign['status'],
            'kind':campaign_kind(campaign),
            ('domains' if 'openSource' in campaign else 'origins'):[source['origin'] for source in campaign['sources']],
            'inferenceRoutes':campaign['inferenceRoutes'],
            'accepting':False,'releaseApproved':approved,
            'reason':'preflight_and_service_admission_required' if approved else 'release_not_approved',
            'rewardMinor':campaign['rewardMinor'],'rewardUSDC':campaign['rewardMinor']//1000000,
            'payout':{'network':'Base','chainId':CHAIN_ID,'token':'USDC','contract':USDC_ADDRESS,'decimals':6},
            'provider':route['provider'],'model':model,'privacyMode':privacy,
            'upstream':(route['provider'] if 'openSource' in campaign else
                        OPENROUTER_UPSTREAMS.get(model) if route['provider']=='openrouter' else
                        sorted(NEAR_VISIBLE_UPSTREAMS) if route['provider']=='near' else route['provider']),
            'inferenceInput':('contributor_notes_and_value_free_transcript' if 'openSource' in campaign
                              else 'redacted_structural_artifact'),
            'inferenceBilling':'contributor_key_only_including_failed_or_rejected_jobs',
            'defaultLimits':campaign_limits(campaign),'inputLimitUnit':'conservative_encoded_request_bytes_then_reported_tokens',
            'guaranteedDollarCap':False,'rewardGuaranteed':False,
            'releaseDigest':digest(release),'policyDigest':digest(policy)}


def campaign_kind(campaign):
    return 'open_recipe' if 'openSource' in campaign else 'reviewed_descriptor' if 'sourceDescriptor' in campaign else 'reviewed_adapter'


def campaign_summary(campaign):
    """Compact public campaign card for a contributor's agent."""
    return {'campaignId':campaign['id'],'bankId':campaign['bankId'],'bankName':campaign['bankName'],
            'status':campaign['status'],'kind':campaign_kind(campaign),'rewardUSDC':campaign['rewardMinor']//1000000,
            'maxContributors':campaign['maxContributors'],
            # Open campaigns pin a registrable domain: any https host under it is accepted.
            ('domains' if 'openSource' in campaign else 'origins'):[source['origin'] for source in campaign['sources']],
            'methods':sorted({method for source in campaign['sources'] for method in source['methods']}),
            'inferenceRoutes':[{'provider':route['provider'],'models':route['models']} for route in campaign['inferenceRoutes']],
            'maxBankReads':campaign_limits(campaign)['maxBankReads'],'issueUrl':campaign['issueUrl'],
            **({'requiredRoles':campaign['evidenceRequirements']['requiredFields'],
                'minScore':campaign['evidenceRequirements']['minScore']} if 'openSource' in campaign else {})}


def secret_free(payload):
    """The stdin payload for --secrets-from-env/--prompt-secrets must not already hold secrets."""
    require(isinstance(payload,dict) and isinstance(payload.get('credential'),dict)
            and 'inferenceKey' not in payload and 'value' not in payload['credential'],'secrets_already_in_payload')
    fields(payload,{'credential','profileId','recipe','notes','transcript'})
    fields(payload['credential'],{'origin','kind'})


def bank_secret(payload,value):
    # Header credentials are a JSON object of header name to value.
    if payload['credential']['kind']=='headers':
        try:value=strict_json(value,65536)
        except Rejected:raise Rejected('credential_headers_invalid') from None
        require(isinstance(value,dict),'credential_headers_invalid')
    payload['credential']['value']=value


def secrets_from_env(payload,*,inference=True):
    """Owner-exported secrets; the agent never needs to read or store their values."""
    secret_free(payload)
    bank,key=os.environ.get('PEERLINK_BANK_CREDENTIAL'),os.environ.get('PEERLINK_INFERENCE_KEY')
    require(bool(bank) and (bool(key) or not inference),'secrets_env_missing')
    bank_secret(payload,bank)
    if inference:payload['inferenceKey']=key


def preview(policy,campaign_id,payload,mapping=None):
    """Run the campaign's reads from this machine and show exactly what the enclave
    would retain. No reservation, inference, upload or payout happens here."""
    from .artifacts import extract_artifact
    from .transport import BankClient,HTTPTransport
    campaign=next((item for item in policy['campaigns'] if item['id']==campaign_id),None)
    require(campaign is not None,'campaign_unavailable');validate_campaign(campaign)
    fields(payload,{'credential','profileId','recipe','notes','transcript'} | ({'inferenceKey'} if 'inferenceKey' in payload else set()))
    context=None
    if 'openSource' in campaign:
        from .open_source import submission_context
        context=submission_context(campaign,payload)
    bank=BankClient(campaign,payload['credential'],transport=HTTPTransport('direct'),profile_id=payload['profileId'],
                    max_reads=campaign_limits(campaign)['maxBankReads'])
    try:
        reads=bank.acquire('0'*32,payload['recipe'],int(time.time()))
        artifact=extract_artifact(campaign,reads,context) if context is not None else extract_artifact(campaign,reads)
        result={'campaignId':campaign_id,'acquired':True,'transcriptBytes':len(canonical(artifact)),'transcript':artifact,
                'retained':'This transcript is everything the enclave keeps and sends to your model. Review it for anything personal.'}
        if context is not None:
            from .open_source import ROLES,assess
            history=artifact['history'];prefix=history['path']+'[]'
            result['historyFieldPaths']=sorted(path for path in artifact['requests'][history['step']-1]['fields']
                                               if path.startswith(prefix+'.') and '[]' not in path[len(prefix):] and '{key}' not in path)
            if mapping is not None:
                require(isinstance(mapping,dict) and set(mapping)<=set(ROLES),'model_result_invalid')
                assessment=assess(campaign,reads,context,artifact,{'mapping':mapping,'completedStatus':[]})
                # The model, not this preview, chooses which status tokens mean "completed".
                del assessment['completedStatus']
                result['assessment']={**assessment,'required':campaign['evidenceRequirements']['requiredFields'],
                                      'minScore':campaign['evidenceRequirements']['minScore']}
                result['observations']=observations(reads,context,artifact,assessment['mapping'])
        return result
    finally:
        bank.close();reads=None


def observations(reads,context,artifact,mapping):
    """Value-free facts about the verified fields, computed on this machine only, so
    notes can state ordering, sign and status usage without anyone reading the rows."""
    from collections import Counter
    from .open_source import _history_rows,select,value_format
    rows=_history_rows(reads,context);history=artifact['history'];prefix=history['path']+'[]'
    shapes=artifact['requests'][history['step']-1]['fields']

    def column(role):
        keys=mapping[role][len(prefix)+1:].split('.')
        return [value for value in (select(row,keys) for row in rows) if value is not None and value!='']

    def number(value):
        if type(value) in (int,float):return value
        try:return float(value.strip().replace(',',''))
        except (AttributeError,ValueError):return None

    result={'records':len(rows),'local':'Computed here from the live rows; never uploaded. Use it to write accurate notes.'}
    if 'timestamp' in mapping:
        values=column('timestamp');order='unknown'
        sortable=all(type(value) in (int,float) for value in values) or all(
            isinstance(value,str) and (value_format(value,'date') or '').split(':')[0]=='datetime' for value in values)
        # Text times compare correctly only when every row uses one layout and zone.
        zones={('Z' if value.endswith('Z') else value[-6:] if value[-6:-5] in ('+','-') else '')
               if isinstance(value,str) else '' for value in values}
        if sortable and len(zones)==1 and len(set(map(len,map(str,values))))==1 and len(values)>1:
            pairs=list(zip(values,values[1:]))
            order=('single_value' if len(set(values))==1 else 'newest_first' if all(a>=b for a,b in pairs)
                   else 'oldest_first' if all(a<=b for a,b in pairs) else 'unordered')
        result['timestampOrder']=order
    if 'amount' in mapping:
        values=column('amount');numbers=[number(value) for value in values]
        result['amountForm']=('integer' if all(type(value) is int for value in values) else
                              'decimal' if all(type(value) in (int,float) for value in values) else 'text')
        result['amountSign']=('unknown' if not numbers or None in numbers else 'all_positive' if all(n>0 for n in numbers)
                              else 'all_negative' if all(n<0 for n in numbers) else 'mixed')
    if 'status' in mapping:
        kept=set(shapes[mapping['status']].get('values',[]));counts=Counter(column('status'))
        # Only tokens the transcript already keeps are named; anything else is pooled.
        usage={token:count for token,count in sorted(counts.items()) if token in kept}
        other=sum(count for token,count in counts.items() if token not in kept)
        result['statusUsage']={**usage,**({'(withheld)':other} if other else {})}
    return result


def lookup(policy,campaign_id,payload,index,path):
    """Run one read of the recipe from this machine and return a single value from its
    JSON, for an id that a later URL needs. Nothing is reserved, uploaded or kept."""
    from .open_source import credential_headers,origin_in_domain,select,validate_open_recipe
    from .transport import HTTPResponse,HTTPTransport,json_response
    campaign=next((item for item in policy['campaigns'] if item['id']==campaign_id),None)
    require(campaign is not None and 'openSource' in campaign,'campaign_unavailable');validate_campaign(campaign)
    credential=payload.get('credential');recipe=payload.get('recipe')
    require(isinstance(credential,dict) and any(origin_in_domain(credential.get('origin'),source['origin'])
                                                for source in campaign['sources']),'invalid_credential')
    require(isinstance(recipe,dict) and isinstance(recipe.get('reads'),list) and type(index) is int
            and 0<=index<len(recipe['reads']),'recipe_invalid')
    read=recipe['reads'][index];selector={'read':0,'path':path}
    # The same URL, method and write rules the enclave applies to that read.
    validate_open_recipe(campaign,{'version':3,'reads':[read],'identity':selector,'history':selector})
    require(read['url'].startswith(credential['origin']+'/'),'source_not_allowed')
    headers=credential_headers(credential,credential['origin'])
    if not any(name.lower()=='accept' for name in headers):headers['Accept']='application/json'
    try:
        response=HTTPTransport('direct').request_bank(read['url'],headers=headers,timeout=45,max_bytes=2_000_000,
                                                      open_headers=True,body=read.get('body'),content_type=read.get('contentType'))
        require(type(response) is HTTPResponse and response.status==200,'bank_http_unexpected_status')
        try:value=select(json_response(response),path)
        except Rejected:raise Rejected('bank_response_non_json') from None
    finally:headers.clear()
    require(type(value) is int or isinstance(value,str) and 0<len(value)<=200,'lookup_not_scalar')
    return {'campaignId':campaign_id,'read':index,'value':value,
            'local':'A raw value from the account, shown only on this machine. Put it in the later read URL; do not paste it into notes.'}


def prompt_secrets(payload):
    """Read directly from the controlling TTY; disable every stdin/echo fallback."""
    secret_free(payload)
    require(os.name=='posix','secret_prompt_unavailable')
    previous_stdin=sys.stdin
    bank_key=inference_key=None
    try:
        with open('/dev/tty','w',encoding='utf-8') as terminal:
            require(terminal.isatty(),'secret_prompt_unavailable')
            # getpass normally falls back to stdin if /dev/tty or echo control
            # fails. The recipe pipe is never allowed as a secret input source.
            sys.stdin=io.StringIO()
            with warnings.catch_warnings():
                warnings.simplefilter('error',getpass.GetPassWarning)
                bank_key=getpass.getpass('Bank API token (owner only): ',stream=terminal)
                inference_key=getpass.getpass('Inference API key (owner only): ',stream=terminal)
            require(isinstance(bank_key,str) and 1<=len(bank_key)<=16384
                    and all(33<=ord(char)<127 for char in bank_key),'invalid_credential')
            require(isinstance(inference_key,str) and 8<=len(inference_key)<=4096
                    and all(33<=ord(char)<127 for char in inference_key),'inference_key_required')
            bank_secret(payload,bank_key);payload['inferenceKey']=inference_key
    except Rejected:raise
    except (OSError,ValueError,EOFError,getpass.GetPassWarning,KeyboardInterrupt):
        raise Rejected('secret_prompt_unavailable') from None
    finally:
        sys.stdin=previous_stdin;bank_key=inference_key=None


def save_state(path,state):
    """A local recovery handle contains only public, verified reservation metadata."""
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as output:
        output.write(canonical(state));output.flush();os.fsync(output.fileno())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','campaigns','terms','preflight','preview','lookup','contribute','submit-reserved','job','receipt'])
    parser.add_argument('--service');parser.add_argument('--release',type=Path,default=Path(__file__).with_name('release.json'))
    parser.add_argument('--policy',type=Path,default=Path(__file__).with_name('policy.json'))
    parser.add_argument('--campaign');parser.add_argument('--payout');parser.add_argument('--provider',choices=['openai','openrouter','near',CUSTOM_PROVIDER])
    parser.add_argument('--base-url',help='With --provider openai_compatible: https URL prefix before /chat/completions')
    parser.add_argument('--max-output-tokens',type=int,help='Raise for reasoning models (default 2048, max 20000)')
    parser.add_argument('--deadline',type=int,help='Seconds allowed for bank reads plus inference (default 120, max 300)')
    parser.add_argument('--secrets-from-env',action='store_true',
                        help='Read PEERLINK_BANK_CREDENTIAL and PEERLINK_INFERENCE_KEY after admission; stdin holds only the nonsecret payload')
    parser.add_argument('--mapping',type=Path,help='preview only: JSON object of role to history field path to verify locally')
    parser.add_argument('--read',type=int,default=0,help='lookup only: index of the recipe read to run (default 0)')
    parser.add_argument('--path',help='lookup only: JSON array of keys and indexes selecting one value, for example \'[0,"id"]\'')
    parser.add_argument('--live',action='store_true',help='campaigns only: add the unsigned live capacity hint')
    parser.add_argument('--model');parser.add_argument('--privacy',choices=['provider_visible','confidential'],default=None)
    parser.add_argument('--consent',action='store_true')
    parser.add_argument('--state',type=Path,help='Public local recovery handle; contribute creates it, submit-reserved continues its unexpired reserved job without overwriting it')
    parser.add_argument('--job-id',help='Must match the job in --state')
    parser.add_argument('--prompt-secrets',action='store_true',
                        help='Owner enters bank/inference secrets on a controlling TTY after verified admission; contribute first saves the recovery handle, submit-reserved first verifies the existing job; stdin contains only the nonsecret recipe payload')
    args=parser.parse_args()
    client=None
    try:
        release=json.loads(args.release.read_text());policy=json.loads(args.policy.read_text())
        if args.command=='status':
            approved=release.get('status')=='approved' and release.get('expiresAt',0)>time.time()
            print(json.dumps({'release':release,'campaigns':policy['campaigns'],
                              'accepting':False,'releaseApproved':approved,
                              'reason':'preflight_and_service_admission_required' if approved else 'release_not_approved'}));return
        if args.command=='terms':
            print(json.dumps(terms(release,policy,args.campaign,args.provider,args.model,args.privacy or 'provider_visible'),sort_keys=True));return
        if args.command=='campaigns':
            # The whole epoch shares this funded amount; --live shows what is left of it.
            result={'epochBudgetUSDC':policy['pilotBudgetMinor']//1000000,
                    'campaigns':[campaign_summary(item) for item in policy['campaigns']
                                 if args.campaign is None or item['id']==args.campaign]}
            if args.live:
                client=Client(args.service or release.get('serviceUrl'),release,policy)
                result['availability']=client.availability()
            print(json.dumps(result,sort_keys=True));return
        if args.command=='preview':
            require(args.campaign is not None,'missing_arguments')
            payload=strict_json(sys.stdin.buffer.read(2_000_001),2_000_000)
            require(isinstance(payload,dict),'invalid_submission')
            try:
                # A local preview makes no model call, so it needs only the bank secret.
                if args.secrets_from_env:secrets_from_env(payload,inference=False)
                try:mapping=strict_json(args.mapping.read_bytes(),65536) if args.mapping is not None else None
                except OSError:raise Rejected('mapping_file_unreadable') from None
                result=preview(policy,args.campaign,payload,mapping)
            finally:payload.clear()
            print(json.dumps(result,sort_keys=True));return
        if args.command=='lookup':
            require(args.campaign is not None and args.path is not None,'missing_arguments')
            try:path=strict_json(args.path.encode(),4096)
            except Rejected:raise Rejected('identity_path_invalid') from None
            payload=strict_json(sys.stdin.buffer.read(2_000_001),2_000_000)
            require(isinstance(payload,dict),'invalid_submission')
            try:
                if args.secrets_from_env:secrets_from_env(payload,inference=False)
                result=lookup(policy,args.campaign,payload,args.read,path)
            finally:payload.clear()
            print(json.dumps(result,sort_keys=True));return
        client=Client(args.service or release.get('serviceUrl'),release,policy)
        if args.command=='preflight':result=client.preflight()
        elif args.command in {'job','receipt'}:
            require(args.state is not None,'state_required')
            client.restore(strict_json(args.state.read_bytes(),200_000))
            job_id=args.job_id or client.job['jobId']
            require(job_id==client.job['jobId'],'job_context_required')
            if args.command=='job':result=client.status(job_id)
            else:
                client.preflight();signed=client.receipt(job_id)
                result={'jobId':job_id,'verified':True,'state':signed['payload']['job']['state'],'receipt':signed}
        elif args.command=='submit-reserved':
            require(args.consent,'consent_required');require(args.state is not None,'state_required')
            # The original saved terms are authoritative. This command cannot
            # replace the beneficiary, campaign, provider, or model.
            require(not any((args.campaign,args.payout,args.provider,args.model)),'unexpected_arguments')
            client.restore(strict_json(args.state.read_bytes(),200_000))
            job_id=args.job_id or client.job['jobId']
            require(job_id==client.job['jobId'],'job_context_required')
            require(time.time()<client.job['request']['expiresAt'],'job_expired')
            status=client.status(job_id) # Current approved quote and bound status.
            require(status.get('reportedState',status.get('state'))=='reserved','job_replayed')
            request=client.job['request']
            require(time.time()<request['expiresAt'],'job_expired')
            require(args.privacy is None or args.privacy==request['privacyMode'],'unexpected_arguments')
            campaign=next(item for item in policy['campaigns'] if item['id']==client.job['campaignId'])
            print(json.dumps({'event':'continuing_reserved','jobId':job_id,'campaignId':client.job['campaignId'],
                              'payoutAddress':request['payoutAddress'],'rewardMinor':campaign['rewardMinor'],
                              'provider':request['provider'],'model':request['model'],'privacyMode':request['privacyMode'],
                              **({'inferenceBaseUrl':request['inferenceBaseUrl']} if 'inferenceBaseUrl' in request else {}),
                              'limits':request['limits'],'stateFile':str(args.state.resolve())}),flush=True)
            payload=strict_json(sys.stdin.buffer.read(2_000_001),2_000_000)
            require(isinstance(payload,dict),'invalid_submission')
            try:
                if args.prompt_secrets:prompt_secrets(payload)
                elif args.secrets_from_env:secrets_from_env(payload)
                result=client.submit_reserved(payload,consent=args.consent)
            finally:payload.clear()
        else:
            args.privacy=args.privacy or 'provider_visible'
            require(args.consent,'consent_required')
            require(all((args.campaign,args.payout,args.provider,args.model)),'missing_arguments')
            # Validate local terms before requesting or reading secret input.
            campaign=next((c for c in policy['campaigns'] if c['id']==args.campaign),None)
            require(campaign is not None,'campaign_unavailable')
            now=int(time.time())
            overrides={name:value for name,value in (('maxOutputTokens',args.max_output_tokens),
                                                    ('deadlineSeconds',args.deadline)) if value is not None}
            require((args.provider==CUSTOM_PROVIDER)==(args.base_url is not None),'invalid_provider')
            extra={}
            if args.base_url is not None:extra['base_url']=args.base_url.rstrip('/')
            if overrides:extra['limits']=overrides
            preview_request={'version':1,'campaignId':args.campaign,'payoutAddress':args.payout,
                'provider':args.provider,'model':args.model,'privacyMode':args.privacy,'consent':True,
                'policyDigest':digest(campaign),'expiresAt':now+600,
                'limits':campaign_limits(campaign,overrides)}
            if args.base_url is not None:preview_request['inferenceBaseUrl']=extra['base_url']
            validate_reservation(campaign,preview_request,now)
            if args.state is not None:require(not args.state.exists(),'state_exists')
            # Reserving first and then waiting on an empty terminal would hold a slot.
            require(sys.stdin.isatty() is not True,'payload_required')
            def reserved(state):
                path=args.state or Path('.local')/('transcript-job-'+state['jobId']+'.json')
                save_state(path,state)
                print(json.dumps({'event':'reserved','jobId':state['jobId'],'stateFile':str(path.resolve()),
                                  'nextAction':'poll_same_job'}),flush=True)
            # Reserve and durably save the public recovery handle before reading
            # stdin or prompting the owner. A full campaign never needs secrets.
            client.reserve(args.campaign,args.payout,args.provider,args.model,args.privacy,
                           consent=args.consent,on_reserved=reserved,**extra)
            payload=strict_json(sys.stdin.buffer.read(2_000_001),2_000_000)
            require(isinstance(payload,dict),'invalid_submission')
            try:
                if args.prompt_secrets:prompt_secrets(payload)
                elif args.secrets_from_env:secrets_from_env(payload)
                result=client.submit_reserved(payload,consent=args.consent)
            finally:payload.clear()
        if isinstance(result,dict) and hint(result.get('reason')):result['hint']=hint(result['reason'])
        print(json.dumps(result,sort_keys=True))
    except Rejected as error:
        result={'error':str(error)}
        if hint(str(error)):result['hint']=hint(str(error))
        if client is not None and client.job is not None:
            terminal=str(error)=='job_not_found' and time.time()>=client.job['request']['expiresAt']
            result.update({'jobId':client.job['jobId'],'bindingDigest':client.job['bindingDigest'],
                           'nextAction':'terminal_record_unavailable' if terminal else
                                        'check_existing_job_outcome' if str(error)=='job_expired' else 'poll_same_job_do_not_resubmit'})
        print(json.dumps(result));raise SystemExit(1)
    except Exception:
        result={'error':'client_failed'}
        if client is not None and client.job is not None:
            result.update({'jobId':client.job['jobId'],'bindingDigest':client.job['bindingDigest'],
                           'nextAction':'poll_same_job_do_not_resubmit'})
        print(json.dumps(result));raise SystemExit(1)

if __name__=='__main__':main()
