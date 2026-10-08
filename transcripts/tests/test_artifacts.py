"""Synthetic Wise structural usefulness and redaction; no bank/network access."""
import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path

from transcripts.artifacts import WISE_PATH_BINDINGS,extract_artifact,validate_artifact
from transcripts.common import Rejected,canonical
from transcripts.recipe import LiveRead
from transcripts.tests.test_core import campaign as generic_campaign,read as synthetic_read


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.campaign=json.loads((Path(__file__).parents[1]/'policy.json').read_text())['campaigns'][0]
        self.profile=9100001;self.balance=9200002;self.job='a'*32

    def reads(self):
        profile,balance=self.profile,self.balance
        urls=['https://api.wise.com/v1/profiles',
              f'https://api.wise.com/v4/profiles/{profile}/balances?types=STANDARD',
              f'https://api.wise.com/v1/profiles/{profile}/balance-statements/{balance}/statement.json'
              '?currency=USD&intervalStart=2099-01-01&intervalEnd=2099-02-01&type=COMPACT']
        bodies=[[{'id':profile,'firstName':'SYNTHETIC-PRIVATE-NAME'}],
                [{'id':balance,'type':'STANDARD','profileId':profile,'currency':'USD'}],
                {'transactions':[{'type':'SYNTHETIC-PRIVATE-TYPE','date':'SYNTHETIC-PRIVATE-DATE',
                   'referenceNumber':'SYNTHETIC-PRIVATE-REFERENCE','amount':{'value':99991.33,'currency':'USD'},
                   'exchangeDetails':{'forAmount':{'value':77771.22,'currency':'SGD'},'rate':1.123456789},
                   'details':{'senderAccount':'SYNTHETIC-PRIVATE-ACCOUNT','sourceAmount':{'value':42.22,'currency':'EUR'},
                              'targetAmount':{'value':43.33,'currency':'USD'},'merchant':{
                                  'name':'SYNTHETIC-PRIVATE-MERCHANT','category':'SYNTHETIC-PRIVATE-CATEGORY',
                                  'firstLine':'SYNTHETIC-PRIVATE-STREET','postCode':'SYNTHETIC-PRIVATE-POSTCODE'}},
                   'SYNTHETIC-PRIVATE-DYNAMIC-KEY':{'SYNTHETIC-PRIVATE-NESTED-KEY':'SYNTHETIC-PRIVATE-MEMO'}}],
                 'endOfStatementBalance':{'value':123456.78,'currency':'USD'},
                 'query':{'accountId':balance,'intervalStart':'SYNTHETIC-PRIVATE-START','intervalEnd':'SYNTHETIC-PRIVATE-END'},
                 'issuer':{'name':'SYNTHETIC-PRIVATE-ISSUER'},'bankDetails':{'id':'SYNTHETIC-PRIVATE-BANK-DETAIL'},
                 'accountHolder':{'firstName':'SYNTHETIC-PRIVATE-NAME','lastName':'SYNTHETIC-PRIVATE-LAST'}}]
        return [LiveRead(self.job,url,'GET',200,body,'wise-profile:'+str(profile),1000,True,True,
                         ('content-type','authorization','SYNTHETIC-PRIVATE-HEADER')) for url,body in zip(urls,bodies)]

    def test_wise_profile_and_balance_parameter_roles_preserved_without_values(self):
        artifact=extract_artifact(self.campaign,self.reads())
        self.assertEqual(artifact['relationships'],list(WISE_PATH_BINDINGS))
        encoded=canonical(artifact).decode()
        for private in ('SYNTHETIC-PRIVATE',str(self.profile),str(self.balance),'99991.33','77771.22',
                        '1.123456789','123456.78','2099-01-01','2099-02-01','wise-profile:','authorization'):
            self.assertNotIn(private,encoded)
        self.assertTrue(all(endpoint['headerNames']==['Content-Type'] for endpoint in artifact['endpoints']))
        statement=next(endpoint for endpoint in artifact['endpoints'] if endpoint['path'].endswith('statement.json'))
        fields={field['path']:field['types'] for field in statement['fields']}
        self.assertEqual(fields['$.transactions[].exchangeDetails.forAmount.value'],['number'])
        self.assertEqual(fields['$.transactions[].details.merchant.category'],['string'])
        self.assertEqual(fields['$.transactions[].details.senderAccount'],['string'])
        self.assertEqual(fields['$.endOfStatementBalance.value'],['number'])
        self.assertEqual(fields['$.query.accountId'],['integer'])
        self.assertIn('$.transactions[].{key}.{key}',fields)
        validate_artifact(self.campaign,artifact)

    def test_relationships_require_matching_authenticated_same_job_account_membership(self):
        changes=[(0,{'authenticated':False}),(0,{'tls_verified':False}),
                 (0,{'job_id':'b'*32}),(0,{'account_id':'wise-profile:999999'}),
                 (0,{'body':[{'id':999999}]}),(0,{'body':[{'id':str(self.profile)}]})]
        for index,modification in changes:
            with self.subTest(change=modification):
                reads=self.reads();reads[index]=replace(reads[index],**modification)
                artifact=extract_artifact(self.campaign,reads)
                self.assertFalse(any(r.get('parameter')=='profileId' for r in artifact['relationships']))
        reads=self.reads();reads[1]=replace(reads[1],body=[{'id':999999,'type':'STANDARD'}])
        self.assertFalse(any(r.get('parameter')=='balanceId' for r in extract_artifact(self.campaign,reads)['relationships']))

    def test_cross_profile_statement_does_not_claim_profile_balance_link(self):
        reads=self.reads();reads[2]=replace(reads[2],url=reads[2].url.replace(str(self.profile),'9300003'))
        artifact=extract_artifact(self.campaign,reads)
        self.assertEqual(artifact['relationships'],[WISE_PATH_BINDINGS[0]])

    def test_relations_require_source_before_target_and_do_not_duplicate(self):
        reads=self.reads()
        artifact=extract_artifact(self.campaign,[reads[2],reads[1],reads[0]])
        self.assertEqual(artifact['relationships'],[])
        artifact=extract_artifact(self.campaign,[reads[0],reads[1],reads[1],reads[2]])
        self.assertEqual(artifact['relationships'],list(WISE_PATH_BINDINGS))

    def test_relationship_validator_rejects_private_values_unreviewed_roles_and_extra_keys(self):
        original=extract_artifact(self.campaign,self.reads())
        for field,value in [('sourceField','$[].SYNTHETIC-PRIVATE-KEY'),('parameter','SYNTHETIC-PRIVATE-NAME'),
                            ('placeholder',2),('placeholder',True),('detailPath','/v1/profiles/9100001/balances'),
                            ('accountId','SYNTHETIC-PRIVATE-ACCOUNT')]:
            with self.subTest(field=field):
                artifact=copy.deepcopy(original);artifact['relationships'][0][field]=value
                with self.assertRaises(Rejected):validate_artifact(self.campaign,artifact)
        artifact=copy.deepcopy(original)
        artifact['endpoints']=list(filter(lambda endpoint:endpoint['path']!='/v1/profiles',artifact['endpoints']))
        with self.assertRaises(Rejected):validate_artifact(self.campaign,artifact)

    def test_live_read_repr_and_nested_debug_output_never_format_private_data(self):
        read=self.reads()[2]
        for output in (repr(read),str(read),repr([read]),repr({'evidence':read})):
            self.assertNotIn('SYNTHETIC-PRIVATE',output)
            self.assertNotIn(str(self.profile),output);self.assertNotIn(str(self.balance),output)
            self.assertNotIn('https://',output);self.assertNotIn('wise-profile:',output)
            self.assertIn('private evidence omitted',output)

    def test_existing_generic_list_detail_relationship_remains_supported(self):
        policy=generic_campaign(sources=[{'origin':'https://bank.example','paths':['/api/accounts','/api/accounts/{id}'],
                                        'methods':['GET'],'parameterNames':[],'headerNames':[]}])
        reads=[replace(synthetic_read(self.job),url='https://bank.example/api/accounts'),
               replace(synthetic_read(self.job),url='https://bank.example/api/accounts/synthetic-account')]
        artifact=extract_artifact(policy,reads)
        self.assertEqual(artifact['relationships'],[{'origin':'https://bank.example','listPath':'/api/accounts',
                                                    'detailPath':'/api/accounts/{id}','relation':'list_detail'}])
        validate_artifact(policy,artifact)

    def test_field_policy_cannot_be_bypassed_by_wise_relationships(self):
        policy=copy.deepcopy(self.campaign);policy['safeSchemaFields'].remove('id')
        artifact=extract_artifact(policy,self.reads())
        self.assertEqual(artifact['relationships'],[])
        self.assertFalse(any(field['path']=='$[].id' for endpoint in artifact['endpoints'] for field in endpoint['fields']))


if __name__=='__main__':unittest.main()
