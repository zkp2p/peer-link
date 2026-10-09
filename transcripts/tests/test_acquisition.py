"""Synthetic descriptor acquisition regressions; no bank, provider, DNS or cloud."""
import copy
import datetime as dt
import socket
import unittest
from unittest.mock import Mock, patch
from transcripts.acquisition import validate_descriptor, validate_hints
from transcripts.artifacts import extract_artifact, validate_artifact, account_fingerprints
from transcripts.common import Rejected, canonical
from transcripts.policy import validate_campaign
from transcripts.recipe import validate_live_reads
from transcripts.transport import BankClient, HTTPTransport, HTTPResponse
from transcripts.tests.test_core import campaign, KEY, NOW, request

ORIGIN='https://api.mercury.com'
ORG='10000000-0000-0000-0000-000000000001'
ACCOUNT='20000000-0000-0000-0000-000000000001'
OTHER='20000000-0000-0000-0000-000000000002'
TX='30000000-0000-0000-0000-000000000001'
TIME=1791504000 # 2026-10-09 UTC


def mercury_campaign(**changes):
    descriptor={'version':1,'kind':'json-account-history-v1','origin':ORIGIN,
        'organizationPath':'/api/v1/organization','identityPath':['organization','id'],'identityScope':'organization',
        'accountsPath':'/api/v1/accounts','accountsListPath':['accounts'],'accountIdField':'id',
        'accountTypeField':'type','accountTypeValue':'mercury','accountStatusField':'status','accountStatusValue':'active',
        'historyPath':'/api/v1/account/{id}/transactions','historyListPath':['transactions'],
        'historyAccountField':'accountId','historyTimestampField':'createdAt','maxItems':100,'maxWindowDays':30,'maxReads':4}
    value=campaign(id='mercury-api-source-v1',bankId='us/mercury',bankName='Mercury',maxContributors=1,
        issueUrl='https://github.com/zkp2p/peer-link/issues/1',sourceDescriptor=descriptor,
        sources=[{'origin':ORIGIN,'paths':[descriptor[k] for k in ('organizationPath','accountsPath','historyPath')],
                  'methods':['GET'],'parameterNames':['limit','order','start','end'],'headerNames':[]}],
        safeSchemaFields=['organization','id','kind','legalBusinessName','ein','accounts','accountNumber','status','type',
                          'transactions','accountId','amount','createdAt','total','page','nextPage','previousPage'],
        evidenceRequirements={'historyPath':['transactions'],'minRecords':1,
                              'requiredFields':['id','accountId','amount','createdAt','kind','status'],'minScore':70})
    value.update(changes);return value


def hints(now=TIME,account=ACCOUNT):
    end=dt.datetime.fromtimestamp(now,dt.timezone.utc).date()
    return {'version':2,'accountId':account,'intervalStart':str(end-dt.timedelta(days=30)),'intervalEnd':str(end)}


def bodies(account=ACCOUNT,rows=1):
    return [{'organization':{'id':ORG,'legalBusinessName':'PRIVATE-LEGAL-NAME','ein':'PRIVATE-EIN'}},
            {'accounts':[{'id':ACCOUNT,'type':'mercury','status':'active','accountNumber':'PRIVATE-NUMBER'},
                         {'id':OTHER,'type':'mercury','status':'active','accountNumber':'OTHER-PRIVATE'}],
             'page':{'nextPage':None,'previousPage':None}},
            {'total':rows,'transactions':[{'id':TX,'accountId':account,'amount':193.45,
                'createdAt':'2026-10-08T12:00:00Z','kind':'incomingDomesticWire','status':'sent',
                'PRIVATE-NAME-KEY':{'https://private.example/?token=PRIVATE':'PRIVATE-MEMO'}}]*rows}]


class SyntheticTransport:
    def __init__(self,values=None,probe=None):
        self.values=iter(bodies() if values is None else values);self.calls=[]
        self.probe=probe or HTTPResponse(401,b'')
    def probe_authentication(self,url,**kwargs):
        self.calls.append(('probe',url,kwargs));return self.probe
    def request_bank(self,url,**kwargs):
        return self.request("GET",url,**kwargs)
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs));value=next(self.values)
        return value if isinstance(value,HTTPResponse) else HTTPResponse(200,canonical(value))


class AcquisitionTests(unittest.TestCase):
    def client(self,values=None,**kwargs):
        transport=SyntheticTransport(values,kwargs.pop('probe',None))
        return BankClient(mercury_campaign(),{'origin':ORIGIN,'kind':'bearer','value':'PRIVATE-TOKEN'},transport,**kwargs),transport
    def test_authenticated_organization_membership_and_bound_history(self):
        client,transport=self.client();reads=client.acquire('job',hints(),TIME)
        self.assertEqual(validate_live_reads(mercury_campaign(),reads,'job',TIME,TIME),'organization:'+ORIGIN+':'+ORG)
        self.assertEqual(len(transport.calls),4)
        self.assertNotIn('headers',transport.calls[0][2]);self.assertNotIn('PRIVATE-TOKEN',canonical(transport.calls[0]).decode())
        self.assertTrue(all(c[0]=='GET' and c[2]['headers']['Authorization']=='Bearer PRIVATE-TOKEN' for c in transport.calls[1:]))
        self.assertIn('limit=100&order=desc&start=2026-09-09&end=2026-10-09',reads[-1].url)
        client.close();self.assertEqual(client.credential,{})
    def test_status_only_probe_gate_failures_never_send_credential(self):
        for probe in (HTTPResponse(200,b''),HTTPResponse(403,b''),HTTPResponse(302,b''),
                      HTTPResponse(401,b'',tls_verified=False),HTTPResponse(401,b'PRIVATE-ERROR'),
                      HTTPResponse(401,b'',(('private','header'),))):
            client,transport=self.client(probe=probe)
            with self.assertRaisesRegex(Rejected,'unauthenticated_source'):client.acquire('job',hints(),TIME)
            self.assertEqual(len(transport.calls),1)
    def test_protected_identity_and_account_membership_stop_before_history(self):
        for mutate,expected in ((lambda b:b[0]['organization'].update(id='not-an-id'),2),
                                (lambda b:b[1]['accounts'][0].update(id=TX),3),
                                (lambda b:b[1]['accounts'][0].update(type='external'),3),
                                (lambda b:b[1]['accounts'][0].update(status='archived'),3)):
            values=bodies();mutate(values);client,transport=self.client(values)
            with self.assertRaises(Rejected):client.acquire('job',hints(),TIME)
            self.assertEqual(len(transport.calls),expected)
        for response in (HTTPResponse(302,b'PRIVATE'),HTTPResponse(200,b'{}',tls_verified=False),HTTPResponse(200,b'{bad')):
            client,transport=self.client([response])
            with self.assertRaises(Rejected):client.acquire('job',hints(),TIME)
            self.assertEqual(len(transport.calls),2)
    def test_history_cross_account_empty_and_page_overflow_rejected(self):
        for values in (bodies(OTHER),bodies(rows=0),bodies(rows=101)):
            client,transport=self.client(values)
            with self.assertRaises(Rejected):client.acquire('job',hints(),TIME)
            self.assertEqual(len(transport.calls),4)
        for value in ('2026-10-10T00:00:00Z','2026-10-08','bad-time'):
            values=bodies();values[2]['transactions'][0]['createdAt']=value
            client,_=self.client(values)
            with self.assertRaises(Rejected):client.acquire('job',hints(),TIME)
        values=bodies();values[1]['accounts']*=51
        client,transport=self.client(values)
        with self.assertRaises(Rejected):client.acquire('job',hints(),TIME)
        self.assertEqual(len(transport.calls),3)
    def test_hints_cannot_supply_routes_expressions_ranges_or_future_dates(self):
        for changes in ({'url':'https://evil.example/'},{'reads':[]},{'accountId':ACCOUNT+'/../../foo'},
                        {'intervalStart':'2026-09-08'},{'intervalEnd':'2026-10-10'},
                        {'intervalStart':'2026-10-09'},{'intervalEnd':'2026-02-31'}):
            client,transport=self.client();candidate=hints();candidate.update(changes)
            with self.assertRaises(Rejected):client.acquire('job',candidate,TIME)
            self.assertEqual(transport.calls,[])
        client,transport=self.client(max_reads=3)
        with self.assertRaisesRegex(Rejected,'recipe_limits'):client.acquire('job',hints(),TIME)
        self.assertEqual(transport.calls,[])
    def test_credential_origin_kind_and_legacy_profile_hint_rejected(self):
        for changes in ({'origin':'https://evil.example'},{'kind':'cookie'},{'value':'a\r\nX-Evil: b'}):
            credential={'origin':ORIGIN,'kind':'bearer','value':'PRIVATE'};credential.update(changes)
            with self.assertRaises(Rejected):BankClient(mercury_campaign(),credential,SyntheticTransport())
        with self.assertRaises(Rejected):self.client(profile_id='1')
    def test_descriptor_is_measured_bounded_data_not_selector_code(self):
        for changes in ({'identityPath':['$.organization.id']},{'maxReads':5},{'historyPath':'/api/v1/../secret'},
                        {'historyPath':'/api/v1/account/{evil}/transactions'},{'identityScope':'human'},
                        {'maxItems':1000},{'maxWindowDays':31},{'unexpected':'eval'}):
            c=mercury_campaign();c['sourceDescriptor'].update(changes)
            with self.assertRaises(Rejected):validate_campaign(c)
        c=mercury_campaign();c['sources'][0]['paths'].append('/api/v1/account/{id}/payments')
        with self.assertRaises(Rejected):validate_campaign(c)
    def test_artifact_private_values_and_history_counts_omitted(self):
        artifacts=[]
        for rows in (1,20):
            client,_=self.client(bodies(rows=rows));reads=client.acquire('job',hints(),TIME)
            artifact=extract_artifact(mercury_campaign(),reads);artifacts.append(artifact)
            text=canonical(artifact).decode()
            for value in (ORG,ACCOUNT,OTHER,TX,'PRIVATE','193.45','2026-09-09','2026-10-09'):
                self.assertNotIn(value,text)
            self.assertIn('organization_duplicates_only',artifact['limitations'])
            self.assertNotIn('account_duplicates_only',artifact['limitations'])
            self.assertEqual(artifact['coverage'],{'readCount':3,'historyMinimumSatisfied':True})
            self.assertEqual(artifact['relationships'][0]['sourceField'],'$.accounts[].id')
        self.assertEqual(*artifacts)
        artifact=copy.deepcopy(artifacts[0]);artifact['limitations'].remove('no_human_identity_claim')
        with self.assertRaises(Rejected):validate_artifact(mercury_campaign(),artifact)
    def test_two_selected_accounts_same_organization_have_same_private_dedup(self):
        fingerprints=[]
        for account in (ACCOUNT,OTHER):
            client,_=self.client(bodies(account));reads=client.acquire('job',hints(account=account),TIME)
            fingerprints.append(account_fingerprints(KEY,mercury_campaign(),reads,reads[0].account_id))
        self.assertEqual(*fingerprints)
    def test_fixed_stage_codes_distinguish_missing_identity_membership_and_binding(self):
        cases=[('org_id_missing',lambda b:b[0]['organization'].pop('id')),
               ('org_id_invalid',lambda b:b[0]['organization'].update(id='invalid')),
               ('account_not_in_page',lambda b:b[1]['accounts'].pop(0)),
               ('transaction_account_missing',lambda b:b[2]['transactions'][0].pop('accountId')),
               ('transaction_account_mismatch',lambda b:b[2]['transactions'][0].update(accountId=OTHER))]
        for code,mutation in cases:
            values=bodies();mutation(values);client,_=self.client(values)
            with self.assertRaisesRegex(Rejected,'^'+code+'$'):client.acquire('job',hints(),TIME)
        for response,code in ((HTTPResponse(200,b'PRIVATE-HTML'),'bank_response_non_json'),
                              (HTTPResponse(403,b'PRIVATE-ERROR'),'bank_http_unauthorized'),
                              (HTTPResponse(429,b'PRIVATE-ERROR'),'bank_http_client_error'),
                              (HTTPResponse(503,b'PRIVATE-ERROR'),'bank_http_server_error')):
            client,_=self.client([response])
            with self.assertRaisesRegex(Rejected,'^'+code+'$'):client.acquire('job',hints(),TIME)

    def test_real_bank_http_errors_never_read_or_export_private_body(self):
        for status,code in ((302,'bank_http_redirect'),(403,'bank_http_unauthorized'),
                            (429,'bank_http_client_error'),(503,'bank_http_server_error')):
            client,server=socket.socketpair()
            server.sendall(f'HTTP/1.1 {status} Error\r\nContent-Length: 9999999\r\nConnection: close\r\n\r\n'.encode())
            context=Mock();context.wrap_socket.return_value=client
            try:
                with patch('transcripts.transport.public_socket',return_value=client),patch('ssl.create_default_context',return_value=context):
                    with self.assertRaisesRegex(Rejected,'^'+code+'$'):
                        HTTPTransport('direct').request_bank(ORIGIN+'/api/v1/organization',
                            headers={'Authorization':'Bearer SYNTHETIC'},timeout=.2)
            finally:client.close();server.close()

    def test_actual_401_https_lifecycle_does_not_read_waiting_error_body(self):
        client,server=socket.socketpair()
        # Body deliberately never sent: any read attempt would timeout.
        server.sendall(b'HTTP/1.1 401 Unauthorized\r\nContent-Length: 9999999\r\nConnection: close\r\n\r\n')
        context=Mock();context.wrap_socket.return_value=client
        try:
            with patch('transcripts.transport.public_socket',return_value=client),patch('ssl.create_default_context',return_value=context):
                result=HTTPTransport('direct').probe_authentication(ORIGIN+'/api/v1/organization',timeout=.2)
            self.assertEqual((result.status,result.body,result.headers),(401,b'',()))
            sent=server.recv(4096)
            self.assertIn(b'GET /api/v1/organization ',sent)
            self.assertNotIn(b'Authorization',sent);self.assertNotIn(b'Cookie',sent)
        finally:client.close();server.close()


class RuntimeAcquisitionTests(unittest.TestCase):
    def test_positive_runtime_and_organization_duplicate_before_second_grade(self):
        from transcripts.tests.test_runtime import RuntimeTests,FakeProvider
        from transcripts.common import digest
        fixture=RuntimeTests('test_archive_before_payment_and_exports_only_redacted_data');fixture.setUp()
        try:
            c=mercury_campaign(maxContributors=2)
            fixture.policy['campaigns']=[c];fixture.runtime.policy['campaigns']=[c]
            fixture.runtime.policy_digest=digest(fixture.policy);fixture.epoch._dedup_key=KEY
            fixture.runtime.payment.preflight_recipient=Mock()
            for index,account in enumerate((ACCOUNT,OTHER)):
                with patch('transcripts.runtime.time.time',return_value=TIME):
                    r=request(c,wallet=index+1);r['expiresAt']=TIME+600
                    job=fixture.runtime.dispatch('reserve',r)
                    fixture.epoch.ledger.submit(job['jobId'],job['bindingDigest'],TIME)
                    values=bodies(account);transport=SyntheticTransport(values);fixture.runtime.transport=transport
                    payload={'credential':{'origin':ORIGIN,'kind':'bearer','value':'PRIVATE-TOKEN'},'profileId':None,
                             'recipe':hints(account=account),'inferenceKey':'PRIVATE-INFERENCE','notes':'','transcript':{}}
                    fixture.runtime.jobs.acquire()
                    with patch('transcripts.providers.ProviderClient',FakeProvider):fixture.runtime.process(job['jobId'],payload)
                    self.assertEqual(payload,{})
                    self.assertEqual(len(transport.calls),4)
                    self.assertEqual(fixture.epoch.ledger.status(job['jobId'])['state'],'paid' if index==0 else 'rejected')
            self.assertEqual(len(FakeProvider.instances),1)
            self.assertEqual(fixture.coordinator.calls,1)
            fixture.runtime.payment.preflight_recipient.assert_called_once_with('0x'+f'{1:040x}',10_000_000)
            self.assertEqual(fixture.epoch.ledger.status(job['jobId'])['reason'],'duplicate_account')
            for record in fixture.archive.records:
                text=canonical(record).decode()
                for value in ('PRIVATE-TOKEN','PRIVATE-INFERENCE',ORG,ACCOUNT,OTHER,TX,'PRIVATE-MEMO','193.45'):
                    self.assertNotIn(value,text)
        finally:fixture.tearDown()

    def test_signed_preflight_checks_source_before_authorization_without_admission(self):
        from transcripts.tests.test_runtime import RuntimeTests
        from transcripts.common import digest
        for status in (401,403):
            fixture=RuntimeTests('test_archive_before_payment_and_exports_only_redacted_data');fixture.setUp()
            try:
                c=mercury_campaign();fixture.policy['campaigns']=[c];fixture.epoch.pause()
                transport=SyntheticTransport(probe=HTTPResponse(status,b''));fixture.runtime.transport=transport
                signing={'keyId':'synthetic','wallet':fixture.epoch.wallet,'signingVerified':True,'broadcast':False}
                with patch.object(fixture.runtime.payment,'funding_balances',return_value=(0,0)), \
                     patch.object(fixture.epoch,'check_payout_signing',return_value=signing,create=True), \
                     patch.object(fixture.runtime.rpc,'call',return_value='0x4'):
                    if status==401:
                        result=fixture.runtime.operator(fixture.operator_message('preflight'))
                        checks=result['preflight']['sourceChecks']
                        self.assertEqual(checks,[{'descriptorDigest':digest(c['sourceDescriptor']),
                                                 'anonymousStatus':401,'invalidCredentialStatus':401}])
                        self.assertFalse(result['health']['accepting'])
                        self.assertEqual(fixture.runtime.funding_preflight,digest(fixture.epoch.public_descriptor()))
                        self.assertEqual([call[2]['invalid_credential'] for call in transport.calls],[False,True])
                    else:
                        with self.assertRaisesRegex(Rejected,'unauthenticated_source'):
                            fixture.runtime.operator(fixture.operator_message('preflight'))
                        self.assertIsNone(fixture.runtime.funding_preflight)
                        self.assertIsNone(fixture.epoch.ledger.runtime_state().get('fundingPreflight'))
                self.assertEqual(fixture.epoch.activations,[])
                self.assertEqual(fixture.epoch.ledger.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
                self.assertEqual(fixture.archive.records,[])
            finally:fixture.tearDown()

    def test_durable_source_preflight_authorization_restores_without_network_reprobe(self):
        from transcripts.tests.test_durable import DurableFixture
        from transcripts.tests.test_runtime import OPERATOR,FakeArchive
        from transcripts.runtime import Runtime
        from verification.common import b64
        from transcripts.common import digest
        fixture=DurableFixture();fixture.setUp()
        try:
            fixture.policy['campaigns']=[mercury_campaign()]
            first=fixture.epoch();transport=SyntheticTransport()
            runtime=Runtime(fixture.policy,first,transport,FakeArchive([]),attester=lambda *args:b'quote')
            payload={'action':'preflight','epochId':first.epoch_id,'wallet':first.wallet,'nonce':'a'*64,'expiresAt':NOW+60}
            with patch('transcripts.runtime.time.time',return_value=NOW+5), \
                 patch.object(runtime.payment,'funding_balances',return_value=(0,0)), \
                 patch.object(runtime.payment,'check_continuity'),patch.object(runtime.rpc,'call',return_value='0x7'):
                result=runtime.operator({'payload':payload,'signature':b64(OPERATOR.sign(canonical(payload)))})
            saved=first.ledger.runtime_state()['fundingPreflight']
            self.assertEqual(saved['sourceChecks'],result['preflight']['sourceChecks'])
            self.assertEqual(len(transport.calls),2)
            second=fixture.epoch()
            restored=Runtime(fixture.policy,second,None,FakeArchive([]),attester=lambda *args:b'quote')
            self.assertEqual(restored.funding_preflight,digest(second.public_descriptor()))
            self.assertFalse(second._active)
            bad=copy.deepcopy(saved);bad['sourceChecks'][0]['anonymousStatus']=403
            with self.assertRaisesRegex(Rejected,'funding_preflight_required'):restored.validate_funding_authorization(bad)
        finally:fixture.tearDown()

    def test_actual_measured_candidate_policy_validates(self):
        import json
        from pathlib import Path
        policy=json.loads((Path(__file__).parents[1]/'policy.json').read_text())
        c=next(item for item in policy['campaigns'] if 'sourceDescriptor' in item)
        validate_campaign(c)
        self.assertEqual(c['bankId'],'us/mercury')
        self.assertEqual(c['rewardMinor'],10_000_000);self.assertEqual(c['maxContributors'],1)
        self.assertIn('api.mercury.com',policy['egressHosts'])

    def test_auth_and_post_identity_failure_release_slot_without_billing_or_dedup(self):
        from transcripts.tests.test_runtime import RuntimeTests,FakeProvider
        cases=[(HTTPResponse(200,b''),bodies(),'unauthenticated_source',1),
               (HTTPResponse(401,b''),bodies(rows=0),'insufficient_history',4),
               (HTTPResponse(401,b''),bodies(OTHER),'transaction_account_mismatch',4)]
        for probe,values,reason,count in cases:
            fixture=RuntimeTests('test_archive_before_payment_and_exports_only_redacted_data');fixture.setUp()
            try:
                c=mercury_campaign();fixture.policy['campaigns']=[c];fixture.runtime.policy['campaigns']=[c]
                with patch('transcripts.runtime.time.time',return_value=TIME):
                    req=request(c);req['expiresAt']=TIME+600
                    job=fixture.runtime.dispatch('reserve',req)
                    fixture.epoch.ledger.submit(job['jobId'],job['bindingDigest'],TIME)
                    transport=SyntheticTransport(values,probe);fixture.runtime.transport=transport
                    payload={'credential':{'origin':ORIGIN,'kind':'bearer','value':'PRIVATE-TOKEN'},'profileId':None,
                             'recipe':hints(),'inferenceKey':'PRIVATE-INFERENCE','notes':'','transcript':{}}
                    fixture.runtime.jobs.acquire()
                    with patch('transcripts.providers.ProviderClient',FakeProvider):fixture.runtime.process(job['jobId'],payload)
                    self.assertEqual(FakeProvider.instances,[]);self.assertEqual(payload,{})
                    status=fixture.epoch.ledger.status(job['jobId'])
                    self.assertEqual((status['state'],status['reason']),('rejected',reason))
                    self.assertEqual(fixture.archive.records,[]);self.assertEqual(len(transport.calls),count)
                    row=fixture.epoch.ledger.db.execute('SELECT account_hmac,account_aliases FROM jobs WHERE id=?',(job['jobId'],)).fetchone()
                    self.assertEqual(tuple(row),(None,None))
                    replacement=fixture.runtime.dispatch('reserve',req)
                    self.assertNotEqual(replacement['jobId'],job['jobId'])
            finally:fixture.tearDown()
