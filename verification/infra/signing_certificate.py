"""Create a public Nitro signing certificate using a non-exportable KMS key.

The operator assumes only the dedicated signing role. AWS credentials remain in
process memory; neither the KMS private key nor session credentials are output.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def der(tag, value):
    size = len(value)
    length = bytes([size]) if size < 128 else size.to_bytes((size.bit_length() + 7) // 8, 'big')
    if size >= 128:
        length = bytes([0x80 | len(length)]) + length
    return bytes([tag]) + length + value


def certificate(public_key, sign_digest, now):
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(public_key.curve, ec.SECP384R1):
        raise ValueError('P-384 signing key required')
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Peer Link enclave release signing')])
    # This ephemeral key only lets the X.509 builder encode the unsigned TBS.
    # Its signature is discarded; KMS signs the exact TBS digest below.
    unsigned = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(public_key).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ec.generate_private_key(ec.SECP384R1()), hashes.SHA384()))
    tbs = unsigned.tbs_certificate_bytes
    signature = sign_digest(hashlib.sha384(tbs).digest())
    public_key.verify(signature, tbs, ec.ECDSA(hashes.SHA384()))
    algorithm = bytes.fromhex('300a06082a8648ce3d040303')  # ecdsa-with-SHA384
    result = x509.load_der_x509_certificate(der(0x30, tbs + algorithm + der(0x03, b'\0' + signature)))
    result.verify_directly_issued_by(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--role-arn', required=True)
    parser.add_argument('--key-arn', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    match = re.fullmatch(r'arn:aws:kms:us-east-1:([0-9]{12}):key/[a-f0-9-]{36}', args.key_arn)
    if not match or args.role_arn != f'arn:aws:iam::{match[1]}:role/peer-link-release-signing':
        raise ValueError('unexpected signing authority')
    if args.output.exists():
        raise ValueError('refusing to replace existing certificate')
    assumed = subprocess.run(['aws', 'sts', 'assume-role', '--profile', args.profile,
        '--region', 'us-east-1', '--role-arn', args.role_arn, '--role-session-name',
        'peer-link-certificate', '--duration-seconds', '900', '--output', 'json'],
        capture_output=True, text=True, check=True)
    credentials = json.loads(assumed.stdout)['Credentials']
    env = {k: v for k, v in os.environ.items() if not k.startswith('AWS_')}
    env.update(AWS_DEFAULT_REGION='us-east-1', AWS_EC2_METADATA_DISABLED='true',
               AWS_CONFIG_FILE='/dev/null', AWS_SHARED_CREDENTIALS_FILE='/dev/null')
    for name, field in [('AWS_ACCESS_KEY_ID', 'AccessKeyId'), ('AWS_SECRET_ACCESS_KEY', 'SecretAccessKey'),
                        ('AWS_SESSION_TOKEN', 'SessionToken')]:
        env[name] = credentials[field]
    def kms(command, **values):
        result = subprocess.run(['aws', 'kms', command, '--cli-input-json', json.dumps({'KeyId': args.key_arn, **values}),
            '--output', 'json'], env=env,
            capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    public = kms('get-public-key')
    assert public['KeyUsage'] == 'SIGN_VERIFY' and public['KeySpec'] == 'ECC_NIST_P384'
    key = serialization.load_der_public_key(base64.b64decode(public['PublicKey']))
    cert = certificate(key, lambda digest: base64.b64decode(kms('sign',
        Message=base64.b64encode(digest).decode(), MessageType='DIGEST',
        SigningAlgorithm='ECDSA_SHA_384')['Signature']), datetime.datetime.now(datetime.timezone.utc))
    with args.output.open('xb') as output:
        output.write(cert.public_bytes(serialization.Encoding.PEM))
    print(json.dumps({'certificateSha256': cert.fingerprint(hashes.SHA256()).hex(),
                      'kmsKeyArn': args.key_arn, 'privateKeyExported': False}))


if __name__ == '__main__':
    main()
