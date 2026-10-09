"""Enclave-authenticated AWS state authority and Recipient-only state keys.

The host forwards temporary IAM credentials and opaque TLS packets, never KMS
plaintext or an asserted 'latest' state. Only the pinned immutable Lambda can
advance the strongly consistent encrypted head. No bank/provider secrets here.
"""
import base64
import copy
import hashlib
import hmac
import os
import re
import secrets
import socket
import subprocess
import time
from urllib.parse import quote

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .common import Rejected, canonical, digest, fields, integer, require, strict_json
from .kms_signer import KEY_ARN
from .transport import json_response
from .wire import exact, send
import struct

MAX_CIPHERTEXT = 327680
MAX_RECORD = 40960
JOB_STORAGE_ALLOWANCE = 49152
# A paid row is final apart from its last signed receipt.
PAID_STORAGE_ALLOWANCE = 4096
# Distinct campaign definitions a snapshot may reference; one per stored job at most.
MAX_SNAPSHOT_CAMPAIGNS = 64
AUTHORITY_FIELDS = {'kind','region','functionArn','namespace','wrappingKeyId',
                    'credentialRoleArn','maxCiphertextBytes','initialWalletNonce'}
HEAD_FIELDS = {'revision','writerGeneration','ciphertextDigest','ciphertext','wrappedMaster','lastOpId','writeCommitment'}


def b64(value):return base64.b64encode(value).decode('ascii')


def decode(value, maximum):
    require(isinstance(value,str) and 0 < len(value) <= 4*((maximum+2)//3),'state_invalid')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,TypeError):raise Rejected('state_invalid') from None
    require(0 < len(raw) <= maximum and b64(raw)==value,'state_invalid')
    return raw


def authority_config(value):
    fields(value,AUTHORITY_FIELDS)
    require(value['kind']=='aws_lambda_dynamodb' and value['region']=='us-east-1'
            and re.fullmatch(r'arn:aws:lambda:us-east-1:[0-9]{12}:function:[A-Za-z0-9_-]{1,64}:[1-9][0-9]*',value['functionArn'])
            and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',value['namespace'])
            and KEY_ARN.fullmatch(value['wrappingKeyId'])
            and re.fullmatch(r'arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]{1,512}',value['credentialRoleArn'])
            and value['maxCiphertextBytes']==MAX_CIPHERTEXT,'state_policy_invalid')
    accounts={value['functionArn'].split(':')[4],value['wrappingKeyId'].split(':')[4],value['credentialRoleArn'].split(':')[4]}
    require(len(accounts)==1 and value['wrappingKeyId'].split(':')[3]==value['region'],'state_policy_invalid')
    integer(value['initialWalletNonce'],0,2**64-1,'state_policy_invalid')
    return value


class Credentials:
    def __init__(self,role_arn):self.role_arn=role_arn
    def __repr__(self):return 'Credentials(<private temporary IAM credentials>)'
    def get(self):
        try:
            with socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM) as connection:
                connection.settimeout(10);connection.connect((3,5104))
                send(connection,{'version':1})
                length=struct.unpack('!I',exact(connection,4))[0]
                require(0<length<=8192,'credentials_unavailable')
                value=strict_json(exact(connection,length),8192)
            fields(value,{'version','accessKeyId','secretAccessKey','sessionToken','expiration','roleArn','instanceId'})
            require(type(value['version']) is int and value['version']==1
                    and value['roleArn']==self.role_arn
                    and type(value['expiration']) is int and time.time()+60<=value['expiration']<=time.time()+43200
                    and re.fullmatch(r'i-[0-9a-f]{8,17}',value['instanceId']),'credentials_unavailable')
            require(all(isinstance(value[key],str) and 1<=len(value[key])<=8192
                        and all(33<=ord(char)<127 for char in value[key])
                        for key in ('accessKeyId','secretAccessKey','sessionToken')),'credentials_unavailable')
            return value
        except Exception:raise Rejected('credentials_unavailable') from None


class AWS:
    """SigV4 is authentication to AWS; verified TLS authenticates its responses."""
    def __init__(self,config,transport,credentials):
        self.config=authority_config(config);self.transport=transport;self.credentials=credentials
    def call(self,service,action,payload):
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials as BotocoreCredentials
        require(service in {'kms','lambda'},'state_service_invalid')
        region=self.config['region']
        if service=='kms':
            require(action in {'GenerateDataKey','Decrypt'},'state_service_invalid')
            url=f'https://kms.{region}.amazonaws.com/'
            headers={'Content-Type':'application/x-amz-json-1.1','X-Amz-Target':'TrentService.'+action}
        else:
            require(action=='Invoke','state_service_invalid')
            url=f"https://lambda.{region}.amazonaws.com/2015-03-31/functions/{quote(self.config['functionArn'],safe='')}/invocations"
            headers={'Content-Type':'application/json'}
        value=self.credentials.get()
        try:
            credential=BotocoreCredentials(value['accessKeyId'],value['secretAccessKey'],value['sessionToken'])
            body=canonical(payload);request=AWSRequest(method='POST',url=url,data=body,headers=headers)
            SigV4Auth(credential,service,region).add_auth(request)
            response=self.transport.request('POST',url,headers=dict(request.headers),body=body,
                                            timeout=20,max_bytes=1_000_000)
            require(not any(k.lower()=='x-amz-function-error' for k,_ in response.headers),'state_authority_unavailable')
            return json_response(response,maximum=1_000_000)
        finally:
            value.clear()


class Authority:
    def __init__(self,config,aws):self.config=authority_config(config);self.aws=aws
    def request(self,action,**values):
        nonce=secrets.token_hex(32)
        request={'version':1,'action':action,'namespace':self.config['namespace'],'nonce':nonce,**values}
        response=self.aws.call('lambda','Invoke',request)
        if isinstance(response,dict) and set(response)=={'version','nonce','error'}:
            require(type(response['version']) is int and response['version']==1 and response['nonce']==nonce,'state_invalid')
            code=response['error']
            raise Rejected(code if code in {'state_conflict','state_missing','state_capacity','state_unavailable'} else 'state_authority_unavailable')
        fields(response,{'version','nonce','namespace','head'})
        require(type(response['version']) is int and response['version']==1 and response['nonce']==nonce
                and response['namespace']==self.config['namespace'],'state_invalid')
        head=response['head']
        if head is not None:
            fields(head,HEAD_FIELDS)
            integer(head['revision'],0,2**63-1,'state_invalid');integer(head['writerGeneration'],1,2**63-1,'state_invalid')
            require(re.fullmatch(r'[0-9a-f]{32}',head['lastOpId'])
                    and re.fullmatch(r'[0-9a-f]{64}',head['ciphertextDigest'])
                    and re.fullmatch(r'[0-9a-f]{64}',head['writeCommitment']),'state_invalid')
            ciphertext=decode(head['ciphertext'],MAX_CIPHERTEXT);decode(head['wrappedMaster'],6144)
            require(hashlib.sha256(ciphertext).hexdigest()==head['ciphertextDigest'],'state_invalid')
        require(action=='load' or head is not None,'state_invalid')
        return head
    def load(self):return self.request('load')


def cms_unwrap(ciphertext,private_key):
    """OpenSSL CMS handles AWS's enveloped content, not raw RSA ciphertext.

    Both inputs/outputs stay in enclave memory. The private key goes through an
    anonymous pipe inherited only by the child; no key/ciphertext files/logs.
    """
    require(isinstance(ciphertext,bytes) and 1<=len(ciphertext)<=6144,'state_key_invalid')
    raw=private_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    read_fd,write_fd=os.pipe()
    try:
        require(len(raw)<4096,'state_key_invalid')
        os.write(write_fd,raw);os.close(write_fd);write_fd=None
        result=subprocess.run(['openssl','cms','-decrypt','-inform','DER','-inkey',f'/dev/fd/{read_fd}'],
                              input=ciphertext,capture_output=True,timeout=5,check=False,pass_fds=(read_fd,))
        require(result.returncode==0 and len(result.stdout)==32,'state_key_invalid')
        return result.stdout
    finally:
        os.close(read_fd)
        if write_fd is not None:os.close(write_fd)
        raw=None


class Master:
    def __init__(self,config,policy_digest,wallet,aws,attester):
        self.config,self.aws,self.attester=authority_config(config),aws,attester
        self.context={'Namespace':config['namespace'],'PolicyDigest':policy_digest,
                      'PayoutWallet':wallet,'AuthorityArn':config['functionArn']}
    def obtain(self,wrapped=None):
        recipient=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=recipient.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        quote_nonce=secrets.token_bytes(32)
        attestation=self.attester(quote_nonce,public,bytes.fromhex(self.context['PolicyDigest']))
        request={'KeyId':self.config['wrappingKeyId'],'EncryptionContext':self.context,
                 'Recipient':{'KeyEncryptionAlgorithm':'RSAES_OAEP_SHA_256','AttestationDocument':b64(attestation)}}
        if wrapped is None:request['KeySpec']='AES_256';action='GenerateDataKey'
        else:request['CiphertextBlob']=b64(wrapped);action='Decrypt'
        # AWS must authenticate the response. An untrusted host can synthesize a
        # valid CMS envelope under this public RSA key with an attacker-known key.
        response=self.aws.call('kms',action,request)
        require(isinstance(response,dict) and response.get('KeyId')==self.config['wrappingKeyId']
                and response.get('Plaintext') in (None,'') and 'CiphertextForRecipient' in response,'state_key_invalid')
        key=cms_unwrap(decode(response['CiphertextForRecipient'],6144),recipient)
        if wrapped is None:wrapped=decode(response.get('CiphertextBlob'),6144)
        return key,wrapped


def pack_snapshot(snapshot):
    """Remove duplicated campaign JSON and JSON-string escaping, no compression."""
    value=copy.deepcopy(snapshot);campaigns={}
    for row in value['jobs']:
        campaign=strict_json(row['campaign'],maximum=100000);identity=digest(campaign)
        campaigns[identity]=campaign;row['campaign']=identity
        for field in ('request','artifact','evidence','receipt_job','payout_intent','account_aliases'):
            if row.get(field) is not None:row[field]=strict_json(row[field],maximum=MAX_RECORD)
    value['campaigns']=campaigns
    return value


def unpack_snapshot(value):
    value=copy.deepcopy(value);campaigns=value.pop('campaigns')
    require(isinstance(campaigns,dict) and len(campaigns)<=MAX_SNAPSHOT_CAMPAIGNS,'state_invalid')
    for row in value['jobs']:
        campaign=campaigns.get(row['campaign']);require(campaign is not None,'state_invalid')
        require(digest(campaign)==row['campaign'],'state_invalid');row['campaign']=canonical(campaign).decode()
        for field in ('request','artifact','evidence','receipt_job','payout_intent','account_aliases'):
            if row.get(field) is not None:row[field]=canonical(row[field]).decode()
    return value


class StateAnchor:
    """Atomic encrypted authoritative snapshots; SQLite is a disposable cache."""
    durable=True
    def __init__(self,config,policy_digest,wallet,master,wrapped,authority,head=None):
        self.config,self.authority=authority_config(config),authority
        self.pending=None
        self.wrapped=wrapped;self.head=head;self.generation=head['writerGeneration'] if head else 1
        self.binding={'schemaVersion':1,'namespace':config['namespace'],'policyDigest':policy_digest,
                      'wallet':wallet,'authorityArn':config['functionArn'],'wrappingKeyId':config['wrappingKeyId']}
        self.keys={purpose:HKDF(algorithm=hashes.SHA256(),length=32,salt=digest(self.binding).encode(),
                               info=('peerlink-durable-'+purpose+'-v1').encode()).derive(master)
                   for purpose in ('integrity','dedup','encryption','authorization')}
    def __repr__(self):return 'StateAnchor(<private encrypted state>)'
    def aad(self,revision,generation,op_id):
        return canonical({**self.binding,'revision':revision,'writerGeneration':generation,'opId':op_id})
    def capability(self,revision):
        return hmac.new(self.keys['authorization'],canonical({'namespace':self.config['namespace'],'revision':revision}),hashlib.sha256).digest()
    def open(self,head):
        require(head is not None and decode(head['wrappedMaster'],6144)==self.wrapped,'state_invalid')
        cipher=decode(head['ciphertext'],MAX_CIPHERTEXT)
        try:raw=AESGCM(self.keys['encryption']).decrypt(cipher[:12],cipher[12:],self.aad(head['revision'],head['writerGeneration'],head['lastOpId']))
        except Exception:raise Rejected('state_integrity') from None
        snapshot=unpack_snapshot(strict_json(raw,maximum=MAX_CIPHERTEXT))
        require(snapshot['revision']==head['revision'] and hashlib.sha256(self.capability(head['revision'])).hexdigest()==head['writeCommitment'],'state_integrity')
        return snapshot
    def capacity(self,snapshot):
        packed=pack_snapshot(snapshot);require(len(packed['jobs'])<=64,'state_capacity')
        # Never write a snapshot the reader would refuse.
        require(len(packed['campaigns'])<=MAX_SNAPSHOT_CAMPAIGNS,'state_capacity')
        usage=len(canonical(packed))+28
        for row in packed['jobs']:
            # Reserve room for what an unfinished job can still add. A paid job
            # only gains its final receipt, so the epoch budget, not a fixed
            # per-job allowance, bounds how many paid jobs fit.
            if row['state'] in {'reserved','submitted','verifying','accepted','payout_pending'}:
                usage+=max(0,JOB_STORAGE_ALLOWANCE-len(canonical(row)))
            elif row['state']=='paid':usage+=PAID_STORAGE_ALLOWANCE
        require(usage<=MAX_CIPHERTEXT,'state_capacity')
        return packed
    def read(self):
        head=self.authority.load()
        if head is None:
            require(self.head is None,'state_rollback');return None
        require(self.head is None or head['revision']>=self.head['revision'],'state_rollback')
        snapshot=self.open(head)
        return snapshot['revision'],snapshot['mac']
    def commit_snapshot(self,old,new,snapshot,*,takeover=False):
        packed=self.capacity(snapshot);nonce=secrets.token_bytes(12)
        generation=self.generation+1 if takeover else self.generation
        op_id=secrets.token_hex(16)
        cipher=nonce+AESGCM(self.keys['encryption']).encrypt(nonce,canonical(packed),self.aad(new[0],generation,op_id))
        require(len(cipher)<=MAX_CIPHERTEXT,'state_capacity')
        values={'opId':op_id,'revision':new[0],'writerGeneration':generation,
                'ciphertextDigest':hashlib.sha256(cipher).hexdigest(),'ciphertext':b64(cipher),
                'writeCommitment':hashlib.sha256(self.capability(new[0])).hexdigest()}
        action='create' if old is None else 'commit'
        if old is None:values['wrappedMaster']=b64(self.wrapped)
        else:
            require(self.head is not None and old==(self.head['revision'],self.open(self.head)['mac']),'state_conflict')
            values.update(expectedRevision=old[0],expectedCiphertextDigest=self.head['ciphertextDigest'],
                          expectedWriterGeneration=self.generation,writeCapability=self.capability(old[0]).hex())
        # Keep exact prepared bytes across transport ambiguity. A bounded retry
        # cannot sign/broadcast or perform a different mutation while uncertain.
        candidate=(old,new,digest(snapshot),action,values,generation)
        if self.pending is not None:
            require(self.pending[:3]==candidate[:3],'state_commit_uncertain')
            candidate=self.pending;action,values,generation=candidate[3:]
        self.pending=candidate
        head=None
        for attempt in range(4):
            try:
                head=self.authority.request(action,**values);break
            except Exception:
                try:
                    observed=self.authority.load()
                    if observed is not None and observed['lastOpId']==values['opId']:
                        head=observed;break
                    require(observed==self.head,'state_conflict')
                except Rejected as error:
                    if str(error)=='state_conflict':raise
                except Exception:pass
            if attempt<3:time.sleep(.2)
        require(head is not None,'state_commit_uncertain')
        require(head['lastOpId']==values['opId'] and head['revision']==values['revision']
                and head['writerGeneration']==generation and head['ciphertext']==values['ciphertext']
                and head['ciphertextDigest']==values['ciphertextDigest']
                and head['writeCommitment']==values['writeCommitment'] and decode(head['wrappedMaster'],6144)==self.wrapped,'state_conflict')
        self.head,self.generation=head,generation
        self.pending=None
    def _close(self):
        self.keys.clear();self.pending=None
