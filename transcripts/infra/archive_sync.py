"""Host-only copy of signed redacted archive records to a private S3 bucket.

Not part of the measured enclave image and never imported by it. The enclave already
validated, signed and released each record to the operator host; this only mirrors
those exact bytes off-host. The instance role is write-only (PutObject on two fixed
prefixes): it cannot read, list or delete. Record contents are never logged.

Standard library only, so the single file can be installed outside a release tree.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_RECORD = 1_200_000  # storage.serve_archive accepts at most 1,100,000 bytes.
MAX_FILES = 10_000
MAX_PASSES = 5
STATES = ('accepted', 'payout_pending', 'paid')
DIGEST = re.compile(r'[0-9a-f]{64}')
JOB = re.compile(r'[0-9a-f]{32}')
CAMPAIGN = re.compile(r'[A-Za-z0-9_-]{1,80}')
BANK_SEGMENT = re.compile(r'[a-z0-9][a-z0-9_-]{0,59}')
BUCKET = re.compile(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]')
REGION = re.compile(r'[a-z]{2}-[a-z]+-[0-9]')


class Skip(ValueError):
    """Fixed-code refusal. The code never contains record content."""


def require(condition, code):
    if not condition:
        raise Skip(code)


def unique_pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'record_invalid')
        result[key] = value
    return result


def bank_prefix(value):
    # policy.py permits [a-z0-9][a-z0-9_/-]{0,119}. Require clean nonempty segments
    # so a record can never select another top-level prefix or an empty key part.
    require(isinstance(value, str) and 1 <= len(value) <= 120, 'record_invalid')
    parts = value.split('/')
    require(1 <= len(parts) <= 4 and all(BANK_SEGMENT.fullmatch(part) for part in parts), 'record_invalid')
    return '/'.join(parts)


def plan(name, body):
    """Return [(key, body)] for one archive file, or raise Skip with a fixed code."""
    require(isinstance(name, str) and name.endswith('.json'), 'not_a_record')
    stem = name[:-5]
    require(DIGEST.fullmatch(stem) is not None, 'not_a_record')
    require(isinstance(body, bytes) and 0 < len(body) <= MAX_RECORD, 'record_size')
    require(hashlib.sha256(body).hexdigest() == stem, 'digest_mismatch')
    try:
        record = json.loads(body.decode('ascii'), object_pairs_hook=unique_pairs)
    except (ValueError, RecursionError):
        raise Skip('record_invalid') from None
    require(isinstance(record, dict) and set(record) == {'payload', 'signature'}
            and isinstance(record['signature'], str) and isinstance(record['payload'], dict), 'record_invalid')
    job, artifact = record['payload'].get('job'), record['payload'].get('artifact')
    require(isinstance(job, dict) and isinstance(artifact, dict), 'record_invalid')
    job_id, campaign, state = job.get('jobId'), job.get('campaignId'), job.get('state')
    require(isinstance(job_id, str) and JOB.fullmatch(job_id) is not None, 'record_invalid')
    require(isinstance(campaign, str) and CAMPAIGN.fullmatch(campaign) is not None
            and artifact.get('campaignId') == campaign, 'record_invalid')
    require(isinstance(state, str) and state in STATES, 'record_invalid')
    bank = bank_prefix(artifact.get('bankId'))
    return [('records/' + stem + '.json', body),
            ('by-bank/' + bank + '/' + campaign + '/' + job_id + '/' + state + '-' + stem[:12] + '.json', body)]


def role_environment():
    # Instance-role credentials and the official regional endpoint only. Ignore
    # operator profiles, injected credentials, CA overrides and proxies.
    env = dict(os.environ)
    for key in list(env):
        if (key.startswith(('AWS_ENDPOINT_URL', 'AWS_CONTAINER_', 'AWS_EC2_METADATA_SERVICE_'))
                or key in {'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
                           'AWS_SECURITY_TOKEN', 'AWS_CREDENTIAL_FILE', 'BOTO_CONFIG', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE',
                           'AWS_WEB_IDENTITY_TOKEN_FILE', 'AWS_ROLE_ARN', 'AWS_ROLE_SESSION_NAME',
                           'AWS_CA_BUNDLE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
                           'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'}):
            env.pop(key, None)
    env.update(AWS_CONFIG_FILE='/dev/null', AWS_SHARED_CREDENTIALS_FILE='/dev/null',
               AWS_PAGER='', AWS_EC2_METADATA_DISABLED='false', AWS_MAX_ATTEMPTS='2',
               AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', NO_PROXY='169.254.169.254')
    return env


def put_object(bucket, region, key, path, body):
    # S3 verifies the supplied SHA-256 and rejects a corrupted transfer.
    checksum = base64.b64encode(hashlib.sha256(body).digest()).decode('ascii')
    subprocess.run(['aws', 's3api', 'put-object', '--region', region,
                    '--endpoint-url', 'https://s3.' + region + '.amazonaws.com',
                    '--bucket', bucket, '--key', key, '--body', str(path),
                    '--content-type', 'application/json', '--server-side-encryption', 'AES256',
                    '--checksum-sha256', checksum,
                    '--cli-connect-timeout', '5', '--cli-read-timeout', '20'],
                   env=role_environment(), check=True, capture_output=True, timeout=45)


def mark(state, stem):
    target = state/'uploaded'/stem
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(state/'uploaded', os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def sync_once(source, state, bucket, region, put=None):
    """One pass. A file is marked only after both of its objects were accepted."""
    put = put_object if put is None else put
    counts = {'scanned': 0, 'uploaded': 0, 'alreadyUploaded': 0, 'skipped': 0, 'failed': 0}
    source, state = Path(source), Path(state)
    if not source.is_dir():
        return counts  # Tolerate a release rollover that briefly removes the archive.
    (state/'uploaded').mkdir(parents=True, exist_ok=True, mode=0o700)
    names = sorted(entry.name for entry in os.scandir(source) if entry.is_file(follow_symlinks=False))
    for name in names[:MAX_FILES]:
        if not name.endswith('.json'):
            continue  # In-progress <digest>.tmp files and anything unexpected.
        counts['scanned'] += 1
        stem = name[:-5]
        if DIGEST.fullmatch(stem) and (state/'uploaded'/stem).exists():
            counts['alreadyUploaded'] += 1
            continue
        path = source/name
        try:
            with open(path, 'rb') as stream:
                body = stream.read(MAX_RECORD + 1)
            objects = plan(name, body)
        except (Skip, OSError):
            counts['skipped'] += 1
            continue
        try:
            for key, content in objects:
                put(bucket, region, key, path, content)
            mark(state, stem)
            counts['uploaded'] += 1
        except Exception:
            counts['failed'] += 1  # Retried by the next path/timer activation.
    return counts


def sync(source, state, bucket, region, put=None):
    # alreadyUploaded reports the state before this run; the rest is the final pass.
    total = sync_once(source, state, bucket, region, put)
    progressed, passes = total['uploaded'], 1
    # Records written during a pass are picked up immediately, not a minute later.
    while progressed and passes < MAX_PASSES:
        counts = sync_once(source, state, bucket, region, put)
        progressed, passes = counts['uploaded'], passes + 1
        total['uploaded'] += counts['uploaded']
        total['scanned'], total['skipped'], total['failed'] = counts['scanned'], counts['skipped'], counts['failed']
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--verbose', action='store_true', help='Print the numeric summary even when nothing changed')
    args = parser.parse_args(argv)
    if not BUCKET.fullmatch(args.bucket) or not REGION.fullmatch(args.region):
        raise SystemExit('archive_sync_failed')
    counts = sync(args.source, args.state, args.bucket, args.region)
    # Fixed numeric summary only; never keys, job IDs or record content. Idle
    # one-minute retries stay silent.
    if args.verbose or counts['uploaded'] or counts['failed']:
        print(json.dumps(counts, sort_keys=True))
    return 1 if counts['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
