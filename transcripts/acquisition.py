"""Reviewed JSON acquisition descriptors; contributor input contains hints only.

Selectors are bounded sequences of public field names, never expressions. Raw
identity/history remain inside the enclave; organization dedup is not humanity.
"""
import copy
import datetime as dt
import re
import time
import uuid
from urllib.parse import urlencode
from .common import Rejected, fields, integer, opaque_id, require

DESCRIPTOR_FIELDS = {'version','kind','origin','organizationPath','identityPath','identityScope',
    'accountsPath','accountsListPath','accountIdField','accountTypeField','accountTypeValue',
    'accountStatusField','accountStatusValue','historyPath','historyListPath',
    'historyAccountField','historyTimestampField','maxItems','maxWindowDays','maxReads'}

SOURCE_FAILURES = {"org_id_missing","org_id_invalid","account_list_invalid","account_not_in_page",
    "account_not_eligible","transaction_account_missing","transaction_account_invalid",
    "transaction_account_mismatch","bank_response_non_json","bank_http_unauthorized",
    "bank_http_redirect","bank_http_client_error","bank_http_server_error","bank_http_unexpected_status"}


def negative_source_checks(campaign,transport,timeout=15):
    """Operator preflight uses no contributor token, reservation or model call."""
    from .common import digest
    from .transport import HTTPResponse
    d=validate_descriptor(campaign);url=d['origin']+d['organizationPath']
    deadline=time.monotonic()+timeout
    for invalid in (False,True):
        remaining=deadline-time.monotonic();require(remaining>0,'request_timeout')
        response=transport.probe_authentication(url,timeout=remaining,invalid_credential=invalid)
        require(type(response) is HTTPResponse and response.tls_verified is True and response.status==401
                and response.body==b'' and response.headers==(),'unauthenticated_source')
    return {'descriptorDigest':digest(d),'anonymousStatus':401,'invalidCredentialStatus':401}


def uuid_id(value,code="account_evidence_missing"):
    require(isinstance(value,str) and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value),
            code)
    require(uuid.UUID(value).int != 0,code)
    return value


def select(body,path):
    for part in path:
        body=body.get(part) if isinstance(body,dict) else None
    return body


def validate_descriptor(campaign):
    from .policy import safe_name, origin
    d=campaign['sourceDescriptor']
    fields(d,DESCRIPTOR_FIELDS)
    require(type(d['version']) is int and d['version']==1 and d['kind']=='json-account-history-v1', 'invalid_policy')
    origin(d['origin'])
    require(d['identityScope']=='organization','invalid_policy')
    for key in ('identityPath','accountsListPath','historyListPath'):
        require(isinstance(d[key],list) and 1<=len(d[key])<=4,'invalid_policy')
        for name in d[key]: safe_name(name)
    for key in ('accountIdField','accountTypeField','accountStatusField','historyAccountField','historyTimestampField'):
        safe_name(d[key])
    for key in ('accountTypeValue','accountStatusValue'):
        safe_name(d[key])
    integer(d['maxItems'],1,100,'invalid_policy')
    integer(d['maxWindowDays'],1,30,'invalid_policy')
    require(type(d['maxReads']) is int and d['maxReads']==4,'invalid_policy')
    paths=[d['organizationPath'],d['accountsPath'],d['historyPath']]
    require(len(set(paths))==3 and all(isinstance(p,str) and re.fullmatch(r'/[A-Za-z0-9_/{}/.-]+',p)
            and '..' not in p and '//' not in p for p in paths),'invalid_source')
    require(all('{' not in p and '}' not in p for p in paths[:2])
            and d['historyPath'].count('{id}')==1 and
            all('{' not in segment and '}' not in segment or segment=='{id}'
                for segment in d['historyPath'].split('/')),'invalid_source')
    require(len(campaign['sources'])==1,'invalid_source')
    source=campaign['sources'][0]
    require(source['origin']==d['origin'] and set(source['paths'])==set(paths)
            and source['methods']==['GET'] and set(source['parameterNames'])=={'limit','order','start','end'}, 'invalid_source')
    names=set(d['identityPath']+d['accountsListPath']+d['historyListPath']) | {
        d['accountIdField'],d['accountTypeField'],d['accountStatusField'],d['historyAccountField'],d['historyTimestampField']}
    require(names<=set(campaign['safeSchemaFields']) and
            campaign['evidenceRequirements']['historyPath']==d['historyListPath'] and
            {d['historyAccountField'],d['historyTimestampField']} <= set(campaign['evidenceRequirements']['requiredFields']), 'invalid_policy')
    return d


def validate_hints(campaign, hints, max_reads=20, now=None):
    d=validate_descriptor(campaign)
    fields(hints,{'version','accountId','intervalStart','intervalEnd'})
    require(type(hints['version']) is int and hints['version']==2,'recipe_version')
    require(max_reads>=d['maxReads'],'recipe_limits')
    uuid_id(hints['accountId'])
    dates=[]
    for field in ('intervalStart','intervalEnd'):
        value=hints[field]
        require(isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value),'recipe_limits')
        try: dates.append(dt.date.fromisoformat(value))
        except ValueError: require(False,'recipe_limits')
    require(0<(dates[1]-dates[0]).days<=d['maxWindowDays'],'recipe_limits')
    if now is not None:
        today=dt.datetime.fromtimestamp(now,dt.timezone.utc).date()
        require(dates[1]<=today, 'stale_evidence')
    return hints


def urls(d,hints):
    return [d['origin']+d['organizationPath'],
            d['origin']+d['accountsPath']+'?'+urlencode({'limit':d['maxItems'],'order':'asc'}),
            d['origin']+d['historyPath'].replace('{id}',hints['accountId'])+'?'+urlencode({
                'limit':d['maxItems'],'order':'desc','start':hints['intervalStart'],'end':hints['intervalEnd']})]


def organization_identity(body,descriptor):
    value=select(body,descriptor['identityPath'])
    require(value is not None,'org_id_missing')
    return uuid_id(value,'org_id_invalid')


def validate_bodies(campaign,bodies,account,now=None):
    d=validate_descriptor(campaign)
    require(isinstance(bodies,list) and len(bodies)==3,'account_evidence_missing')
    identity=organization_identity(bodies[0],d)
    accounts=select(bodies[1],d['accountsListPath'])
    require(isinstance(accounts,list) and 1<=len(accounts)<=d['maxItems'],'account_list_invalid')
    ids=[];selected=None
    for row in accounts:
        require(isinstance(row,dict),'account_evidence_missing')
        id_=uuid_id(row.get(d['accountIdField']),'account_list_invalid'); ids.append(id_)
        if id_==account: selected=row
    require(len(set(ids))==len(ids),'ambiguous_account')
    require(selected is not None,'account_not_in_page')
    require(selected.get(d['accountTypeField'])==d['accountTypeValue']
            and selected.get(d['accountStatusField'])==d['accountStatusValue'], 'account_not_eligible')
    history=select(bodies[2],d['historyListPath'])
    require(isinstance(history,list) and len(history)<=d['maxItems'],'insufficient_history')
    for row in history:
        require(isinstance(row,dict) and row.get(d['historyAccountField']) is not None,'transaction_account_missing')
        observed=uuid_id(row[d['historyAccountField']],'transaction_account_invalid')
        require(observed==account,'transaction_account_mismatch')
        value=row.get(d['historyTimestampField'])
        require(isinstance(value,str) and 1<=len(value)<=64,'insufficient_history')
        try:
            timestamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        except (ValueError,OverflowError): require(False,'insufficient_history')
        require(timestamp.tzinfo is not None and (now is None or timestamp.timestamp()<=now),'stale_evidence')
    return 'organization:'+d['origin']+':'+identity


def validate_evidence(campaign,reads):
    """Recheck private provenance before grading/acceptance/structural extraction."""
    from .recipe import LiveRead
    from urllib.parse import urlsplit,parse_qsl
    d=validate_descriptor(campaign)
    require(isinstance(reads,list) and len(reads)==3 and all(type(r) is LiveRead and r.authentication_gate is True
            and r.authenticated is True and r.tls_verified is True and r.status==200 and r.method=='GET' for r in reads), 'unauthenticated_source')
    org,accounts,history=(urlsplit(r.url) for r in reads)
    require(reads[0].url==d['origin']+d['organizationPath'] and
            accounts.scheme=='https' and accounts.netloc==urlsplit(d['origin']).netloc and accounts.path==d['accountsPath']
            and dict(parse_qsl(accounts.query))=={'limit':str(d['maxItems']),'order':'asc'}, 'source_not_allowed')
    prefix,suffix=d['historyPath'].split('{id}')
    require(history.scheme=='https' and history.netloc==accounts.netloc and history.path.startswith(prefix)
            and history.path.endswith(suffix),'source_not_allowed')
    account=history.path[len(prefix):len(history.path)-len(suffix) if suffix else None]
    uuid_id(account)
    parameters=dict(parse_qsl(history.query,strict_parsing=True))
    require(set(parameters)=={'limit','order','start','end'} and parameters['limit']==str(d['maxItems'])
            and parameters['order']=='desc','source_not_allowed')
    validate_hints(campaign,{'version':2,'accountId':account,'intervalStart':parameters['start'],
                            'intervalEnd':parameters['end']},now=reads[0].acquired_at)
    identity=validate_bodies(campaign,[r.body for r in reads],account,reads[0].acquired_at)
    require(all(r.account_id==identity and r.job_id==reads[0].job_id and r.acquired_at==reads[0].acquired_at
                for r in reads),'ambiguous_account')
    return identity


class DescriptorBankClient:
    def __init__(self,campaign,credential,transport=None,*,profile_id=None,max_reads=20,timeout=15):
        from .policy import validate_campaign
        from .transport import HTTPTransport
        validate_campaign(campaign); self.descriptor=validate_descriptor(campaign)
        fields(credential,{'origin','kind','value'})
        require(credential['origin']==self.descriptor['origin'] and credential['kind']=='bearer','invalid_credential')
        require(isinstance(credential['value'],str) and 1<=len(credential['value'])<=16384
                and all(33<=ord(c)<127 for c in credential['value']),'invalid_credential')
        require(profile_id is None,'invalid_profile')
        self.campaign=copy.deepcopy(campaign);self.credential=credential.copy()
        self.transport=transport or HTTPTransport();self.max_reads=integer(max_reads,1,20,'recipe_limits')
        require(type(timeout) in (int,float) and 0<timeout<=300,'request_timeout');self.timeout=timeout

    def acquire(self,job_id,hints,now):
        from .recipe import LiveRead,permitted_endpoint,assess_history
        from .transport import HTTPResponse,json_response
        opaque_id(job_id);integer(now,0,2**63-1)
        require(bool(self.credential),'invalid_credential')
        validate_hints(self.campaign,hints,self.max_reads,now)
        d=self.descriptor; targets=urls(d,hints)
        for url in targets: permitted_endpoint(self.campaign,url,'GET')
        deadline=time.monotonic()+self.timeout
        def remaining():
            value=deadline-time.monotonic();require(value>0,'request_timeout');return value
        probe=self.transport.probe_authentication(targets[0],timeout=remaining())
        require(type(probe) is HTTPResponse and probe.tls_verified is True and probe.status==401
                and probe.body==b'' and probe.headers==(), 'unauthenticated_source')
        bodies=[]
        for index,url in enumerate(targets):
            from .transport import bank_status_error
            try:
                response=self.transport.request_bank(url,headers={'Accept':'application/json',
                    'Authorization':'Bearer '+self.credential['value']},timeout=remaining(),max_bytes=2_000_000)
                require(type(response) is HTTPResponse and response.tls_verified is True,'unauthenticated_source')
                require(response.status==200,bank_status_error(response.status))
                body=json_response(response)
            except Rejected as error:
                if str(error) in {'response_not_json','response_invalid_json'}:raise Rejected('bank_response_non_json') from None
                raise
            bodies.append(body)
            # Fail authentication and membership gates before requesting more data.
            if index==0: organization_identity(body,d)
            if index==1: validate_bodies(self.campaign,bodies+[_empty(d['historyListPath'])],hints['accountId'])
        identity=validate_bodies(self.campaign,bodies,hints['accountId'],now)
        reads=[LiveRead(job_id,url,'GET',200,body,identity,now,True,True,(),True)
               for url,body in zip(targets,bodies)]
        validate_evidence(self.campaign,reads);assess_history(self.campaign,reads)
        return reads

    def close(self): self.credential.clear()


def _empty(path):
    result=[]
    for key in reversed(path): result={key:result}
    return result
