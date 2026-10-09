"""Credential-free AWS authentication/Recipient CMS boundary tests."""
import base64
import copy
import datetime
import hashlib
import os
import socket
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,ec
from transcripts.aws_state import Master,AWS,Credentials,cms_unwrap
from transcripts.tests.test_durable import CONFIG
from transcripts.common import Rejected,canonical
from transcripts.transport import HTTPResponse,HTTPTransport


class CMSAWS:
    def __init__(self):self.requests=[];self.bad_key=False;self.plaintext=False
    def call(self,service,action,request):
        self.requests.append(copy.deepcopy(request))
        assert service=='kms' and request['Recipient']['KeyEncryptionAlgorithm']=='RSAES_OAEP_SHA_256'
        public=serialization.load_der_public_key(base64.b64decode(request['Recipient']['AttestationDocument']))
        self.public=public
        issuer=ec.derive_private_key(1,ec.SECP256R1())
        name=x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME,'synthetic recipient')])
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(public).serial_number(1)
              .not_valid_before(datetime.datetime(2020,1,1)).not_valid_after(datetime.datetime(2100,1,1))
              .sign(issuer,hashes.SHA256()))
        with tempfile.TemporaryDirectory() as folder:
            # Public certificate only; no key or plaintext file ever written.
            path=Path(folder)/'recipient.pem';path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            result=subprocess.run(['openssl','cms','-encrypt','-binary','-outform','DER','-aes-256-cbc',
                                   '-recip',str(path),'-keyopt','rsa_padding_mode:oaep',
                                   '-keyopt','rsa_oaep_md:sha256','-keyopt','rsa_mgf1_md:sha256'],
                                  input=b'fixed-synthetic-32-byte-data-key!'[:32],capture_output=True,timeout=5)
        assert result.returncode==0,'synthetic CMS construction failed'
        response={'KeyId':CONFIG['wrappingKeyId'],'CiphertextForRecipient':base64.b64encode(result.stdout).decode(),
                  'CiphertextBlob':base64.b64encode(b'synthetic-KMS-wrapped-master').decode()}
        if self.bad_key:response['KeyId']='wrong-key'
        if self.plaintext:response['Plaintext']='unexpected'
        return response

class AWSStateTests(unittest.TestCase):
    def test_actual_oaep_sha256_cms_unwrap_recipient_only_and_context_binding(self):
        aws=CMSAWS();master=Master(CONFIG,'a'*64,'0x'+'2'*40,aws,lambda nonce,key,user:key)
        key,wrapped=master.obtain()
        self.assertEqual(key,b'fixed-synthetic-32-byte-data-key!'[:32]);self.assertEqual(aws.public.key_size,2048)
        request=aws.requests[-1]
        self.assertEqual(request['EncryptionContext'],{'Namespace':CONFIG['namespace'],'PolicyDigest':'a'*64,
            'PayoutWallet':'0x'+'2'*40,'AuthorityArn':CONFIG['functionArn']})
        again,old=master.obtain(wrapped);self.assertEqual((again,old),(key,wrapped))
        self.assertIn('CiphertextBlob',aws.requests[-1]);self.assertNotIn('KeySpec',aws.requests[-1])
        for option in ('bad_key','plaintext'):
            setattr(aws,option,True)
            with self.assertRaisesRegex(Rejected,'state_key_invalid'):master.obtain()
            setattr(aws,option,False)
        with self.assertRaisesRegex(Rejected,'state_key_invalid'):cms_unwrap(b'not-CMS',rsa.generate_private_key(public_exponent=65537,key_size=2048))

    def test_real_sigv4_fixed_aws_services_and_temporary_credentials_cleared(self):
        value={'accessKeyId':'SYNTHETIC_ACCESS','secretAccessKey':'synthetic-not-real-secret','sessionToken':'synthetic-not-real-token'}
        credentials=Mock();credentials.get.side_effect=lambda:dict(value)
        transport=Mock();transport.request.return_value=HTTPResponse(200,b'{"value":1}')
        aws=AWS(CONFIG,transport,credentials)
        self.assertEqual(aws.call('kms','Decrypt',{'KeyId':CONFIG['wrappingKeyId']}),{'value':1})
        args,kwargs=transport.request.call_args
        self.assertEqual(args,('POST','https://kms.us-east-1.amazonaws.com/'))
        headers=kwargs['headers']
        self.assertEqual(headers['X-Amz-Target'],'TrentService.Decrypt')
        self.assertEqual(headers['X-Amz-Security-Token'],value['sessionToken'])
        self.assertIn('/us-east-1/kms/aws4_request',headers['Authorization'])
        aws.call('lambda','Invoke',{'version':1})
        args,kwargs=transport.request.call_args
        self.assertTrue(args[1].startswith('https://lambda.us-east-1.amazonaws.com/2015-03-31/functions/arn%3A'))
        self.assertIn('/us-east-1/lambda/aws4_request',kwargs['headers']['Authorization'])
        with self.assertRaisesRegex(Rejected,'state_service_invalid'):aws.call('sts','Invoke',{})

    def test_aws_headers_and_json_only_on_exact_hosts_and_supported_targets(self):
        client,server=socket.socketpair();body=b'{"value":1}'
        server.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/x-amz-json-1.1\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
        server.shutdown(socket.SHUT_WR);context=Mock();context.wrap_socket.return_value=client
        try:
            with patch('transcripts.transport.public_socket',return_value=client),patch('ssl.create_default_context',return_value=context):
                response=HTTPTransport('direct').request('POST','https://kms.us-east-1.amazonaws.com/',
                    headers={'Content-Type':'application/x-amz-json-1.1','X-Amz-Date':'20990101T000000Z',
                             'X-Amz-Security-Token':'synthetic','X-Amz-Target':'TrentService.Decrypt'},body=b'{}')
            self.assertEqual(response.body,body)
        finally:client.close();server.close()
        for url,target in [('https://bank.example/','TrentService.Decrypt'),
                           ('https://kms.us-east-1.amazonaws.com/','TrentService.Encrypt'),
                           ('https://lambda.us-east-1.amazonaws.com/','TrentService.Decrypt')]:
            with patch('transcripts.transport.public_socket') as connect:
                with self.assertRaisesRegex(Rejected,'unsafe_headers'):
                    HTTPTransport('direct').request('POST',url,headers={'X-Amz-Target':target})
                connect.assert_not_called()

    def test_forwarded_credentials_bound_size_role_and_expiry(self):
        value={'version':1,'accessKeyId':'SYNTHETIC_ACCESS','secretAccessKey':'synthetic-secret',
               'sessionToken':'synthetic-token','expiration':2000,'roleArn':CONFIG['credentialRoleArn'],'instanceId':'i-1234567890abcdef0'}
        def get(candidate,header=None):
            connection=Mock();connection.__enter__=Mock(return_value=connection);connection.__exit__=Mock(return_value=False)
            data=canonical(candidate);parts=[struct.pack('!I',header or len(data)),data]
            connection.recv.side_effect=parts
            with patch('transcripts.aws_state.socket.socket',return_value=connection),patch('transcripts.aws_state.socket.AF_VSOCK',40,create=True),patch('transcripts.aws_state.time.time',return_value=1000):
                return Credentials(CONFIG['credentialRoleArn']).get()
        self.assertEqual(get(value),value)
        self.assertEqual(get({**value,'expiration':1000+21900})['expiration'],22900)
        with self.assertRaisesRegex(Rejected,'credentials_unavailable'):get({**value,'expiration':1000+43201})
        for changed in ({'roleArn':'arn:aws:iam::000000000000:role/wrong'},{'expiration':1001},{'version':True},{'extra':'secret'}):
            with self.assertRaisesRegex(Rejected,'credentials_unavailable'):get({**value,**changed})
        with self.assertRaisesRegex(Rejected,'credentials_unavailable'):get(value,8193)
