"""Host-only archive mirror checks; synthetic records, no AWS or hardware calls."""
import base64
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from transcripts.infra import archive_sync as mirror
from transcripts.infra.archive_template import bucket_name, host_statements, template

JOB = 'ab' * 16
BUCKET = 'peerlink-transcripts-000000000000'
REGION = 'us-east-1'


def record(state='paid', job=JOB, campaign='mercury-api-source-v1', bank='us/mercury', **extra):
    payload = {'version': 1, 'policyDigest': '0' * 64,
               'job': {'jobId': job, 'campaignId': campaign, 'state': state},
               'artifact': {'bankId': bank, 'campaignId': campaign, 'version': 1}}
    payload.update(extra)
    # Same canonical encoding the host archive writes.
    body = json.dumps({'payload': payload, 'signature': 'c2lnbmF0dXJl'}, sort_keys=True,
                      separators=(',', ':'), ensure_ascii=True).encode()
    return hashlib.sha256(body).hexdigest() + '.json', body


class PlanTests(unittest.TestCase):
    def test_exact_bytes_under_content_address_and_browsable_key(self):
        name, body = record()
        stem = name[:-5]
        self.assertEqual(mirror.plan(name, body), [
            ('records/' + stem + '.json', body),
            ('by-bank/us/mercury/mercury-api-source-v1/' + JOB + '/paid-' + stem[:12] + '.json', body)])

    def test_each_settlement_state_has_its_own_browsable_key(self):
        keys = {mirror.plan(*record(state))[1][0].rsplit('/', 1)[1].split('-')[0]
                for state in ('accepted', 'payout_pending', 'paid')}
        self.assertEqual(keys, {'accepted', 'payout_pending', 'paid'})

    def test_filename_must_be_the_sha256_of_its_bytes(self):
        name, body = record()
        with self.assertRaisesRegex(mirror.Skip, 'digest_mismatch'):
            mirror.plan(name, body + b' ')
        with self.assertRaisesRegex(mirror.Skip, 'digest_mismatch'):
            mirror.plan('0' * 64 + '.json', body)

    def test_temporary_and_foreign_names_are_never_records(self):
        _, body = record()
        for name in ('a' * 64 + '.tmp', 'notes.json', 'A' * 64 + '.json', 'a' * 63 + '.json', '../' + 'a' * 64 + '.json'):
            with self.assertRaisesRegex(mirror.Skip, 'not_a_record'):
                mirror.plan(name, body)

    def test_key_parts_come_only_from_strictly_validated_fields(self):
        cases = [dict(state='rejected'), dict(state='reserved'), dict(job='AB' * 16), dict(job='ab' * 15),
                 dict(job='../' + 'ab' * 16), dict(campaign='a/b'), dict(campaign='..'), dict(campaign=''),
                 dict(bank='../secrets'), dict(bank='us//mercury'), dict(bank='/us/mercury'), dict(bank='us/mercury/'),
                 dict(bank='US/Mercury'), dict(bank='us/..'), dict(bank='a/b/c/d/e'), dict(bank='us mercury'), dict(bank=7)]
        for case in cases:
            with self.subTest(case=case), self.assertRaisesRegex(mirror.Skip, 'record_invalid'):
                mirror.plan(*record(**case))

    def test_artifact_and_job_campaigns_must_agree(self):
        payload = {'job': {'jobId': JOB, 'campaignId': 'one', 'state': 'paid'},
                   'artifact': {'bankId': 'us/mercury', 'campaignId': 'two'}}
        body = json.dumps({'payload': payload, 'signature': 's'}, sort_keys=True, separators=(',', ':')).encode()
        with self.assertRaisesRegex(mirror.Skip, 'record_invalid'):
            mirror.plan(hashlib.sha256(body).hexdigest() + '.json', body)

    def test_malformed_unsigned_duplicate_key_and_oversized_files_are_refused(self):
        for body in (b'{', b'[]', b'{"payload":{}}', b'{"payload":{},"signature":"s","extra":1}',
                     b'{"payload":[],"signature":"s"}', b'{"payload":{},"signature":1}',
                     b'{"payload":{"job":{},"job":{}},"signature":"s"}', '{"payload":{},"signature":"é"}'.encode()):
            with self.subTest(body=body), self.assertRaisesRegex(mirror.Skip, 'record_invalid'):
                mirror.plan(hashlib.sha256(body).hexdigest() + '.json', body)
        big = b' ' * (mirror.MAX_RECORD + 1)
        with self.assertRaisesRegex(mirror.Skip, 'record_size'):
            mirror.plan(hashlib.sha256(big).hexdigest() + '.json', big)

    def test_refusal_codes_never_echo_record_content(self):
        name, body = record(bank='../4111111111111111')
        with self.assertRaises(mirror.Skip) as caught:
            mirror.plan(name, body)
        self.assertEqual(str(caught.exception), 'record_invalid')


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.source, self.state = root/'artifacts', root/'state'
        self.source.mkdir()
        self.puts = []

    def put(self, bucket, region, key, path, body):
        self.assertEqual((bucket, region), (BUCKET, REGION))
        self.assertEqual(Path(path).read_bytes(), body)
        self.puts.append(key)

    def write(self, **fields):
        name, body = record(**fields)
        (self.source/name).write_bytes(body)
        return name[:-5]

    def run_sync(self, put=None):
        return mirror.sync(self.source, self.state, BUCKET, REGION, put or self.put)

    def test_uploads_both_objects_once_and_is_idempotent(self):
        first, second = self.write(state='accepted'), self.write(state='paid')
        counts = self.run_sync()
        self.assertEqual((counts['uploaded'], counts['failed'], counts['skipped']), (2, 0, 0))
        self.assertEqual(len(self.puts), 4)
        self.assertEqual({key for key in self.puts if key.startswith('records/')},
                         {'records/' + first + '.json', 'records/' + second + '.json'})
        self.assertTrue(all(key.startswith(('records/', 'by-bank/us/mercury/')) for key in self.puts))
        self.puts.clear()
        again = self.run_sync()
        self.assertEqual((again['uploaded'], again['alreadyUploaded'], self.puts), (0, 2, []))

    def test_only_valid_records_leave_the_host(self):
        good = self.write()
        (self.source/('f' * 64 + '.tmp')).write_bytes(b'in progress')
        (self.source/'operator-notes.txt').write_bytes(b'private')
        (self.source/('e' * 64 + '.json')).write_bytes(b'{"payload":{},"signature":"s"}')
        (self.source/'nested').mkdir()
        (self.source/'nested'/('d' * 64 + '.json')).write_bytes(b'{}')
        (self.source/('c' * 64 + '.json')).symlink_to(self.source/(good + '.json'))
        counts = self.run_sync()
        self.assertEqual((counts['uploaded'], counts['skipped'], counts['failed']), (1, 1, 0))
        self.assertEqual(sorted(self.puts)[1], 'records/' + good + '.json')
        self.assertEqual(len(self.puts), 2)

    def test_partial_failure_is_not_marked_and_is_retried(self):
        stem = self.write()
        calls = []

        def failing(bucket, region, key, path, body):
            calls.append(key)
            if key.startswith('by-bank/'):
                raise subprocess.CalledProcessError(254, ['aws'])

        counts = self.run_sync(failing)
        self.assertEqual((counts['uploaded'], counts['failed']), (0, 1))
        self.assertFalse((self.state/'uploaded'/stem).exists())
        retried = self.run_sync()
        self.assertEqual((retried['uploaded'], retried['failed']), (1, 0))
        self.assertTrue((self.state/'uploaded'/stem).exists())

    def test_record_written_during_a_pass_is_mirrored_in_the_same_run(self):
        self.write(state='accepted')
        late = []

        def put(bucket, region, key, path, body):
            if not late:
                late.append(self.write(state='paid'))
            self.puts.append(key)

        counts = self.run_sync(put)
        self.assertEqual(counts['uploaded'], 2)
        self.assertIn('records/' + late[0] + '.json', self.puts)

    def test_missing_archive_directory_is_a_clean_no_op(self):
        counts = mirror.sync(self.source/'absent', self.state, BUCKET, REGION, self.put)
        self.assertEqual(counts, {'scanned': 0, 'uploaded': 0, 'alreadyUploaded': 0, 'skipped': 0, 'failed': 0})
        self.assertEqual(self.puts, [])
        self.assertFalse(self.state.exists())

    def test_cli_reports_counts_only_and_fails_when_an_upload_failed(self):
        stem = self.write()
        argv = ['--source', str(self.source), '--state', str(self.state), '--bucket', BUCKET, '--region', REGION]
        with patch.object(mirror, 'put_object', side_effect=OSError('no route')), patch('builtins.print') as printed:
            self.assertEqual(mirror.main(argv), 1)
        output = printed.call_args.args[0]
        self.assertEqual(json.loads(output)['failed'], 1)
        self.assertNotIn(stem, output)
        self.assertNotIn(JOB, output)
        with patch.object(mirror, 'put_object') as put, patch('builtins.print') as printed:
            self.assertEqual(mirror.main(argv), 0)
            self.assertEqual(put.call_count, 2)
            self.assertEqual(json.loads(printed.call_args.args[0])['uploaded'], 1)
        with patch.object(mirror, 'put_object') as put, patch('builtins.print') as printed:
            self.assertEqual(mirror.main(argv), 0)  # Idle retry: no upload and no journal line.
            self.assertEqual((put.call_count, printed.call_count), (0, 0))
        for bad in (['--bucket', 'Bad_Bucket', '--region', REGION], ['--bucket', BUCKET, '--region', 'us-east-1; id']):
            with patch.object(mirror, 'put_object') as put, self.assertRaises(SystemExit):
                mirror.main(['--source', str(self.source), '--state', str(self.state)] + bad)
            self.assertEqual(put.call_count, 0)


class TransportTests(unittest.TestCase):
    def test_put_uses_instance_role_fixed_endpoint_and_integrity_checksum(self):
        name, body = record()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/name
            path.write_bytes(body)
            environment = {'AWS_PROFILE': 'operator', 'AWS_ACCESS_KEY_ID': 'injected', 'AWS_ENDPOINT_URL_S3': 'https://example.invalid',
                           'HTTPS_PROXY': 'http://proxy.invalid', 'AWS_CA_BUNDLE': '/tmp/ca.pem', 'PATH': '/usr/bin'}
            with patch.dict(mirror.os.environ, environment, clear=True), patch.object(mirror.subprocess, 'run') as run:
                mirror.put_object(BUCKET, REGION, 'records/' + name, path, body)
        command, options = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(command[:3], ['aws', 's3api', 'put-object'])
        pairs = dict(zip(command[3::2], command[4::2]))
        self.assertEqual(pairs['--endpoint-url'], 'https://s3.us-east-1.amazonaws.com')
        self.assertEqual((pairs['--bucket'], pairs['--key'], pairs['--body']), (BUCKET, 'records/' + name, str(path)))
        self.assertEqual(pairs['--server-side-encryption'], 'AES256')
        self.assertEqual(base64.b64decode(pairs['--checksum-sha256']).hex(), name[:-5])
        self.assertTrue(options['check'] and options['capture_output'] and options['timeout'] <= 60)
        env = options['env']
        for removed in ('AWS_PROFILE', 'AWS_ACCESS_KEY_ID', 'AWS_ENDPOINT_URL_S3', 'HTTPS_PROXY', 'AWS_CA_BUNDLE'):
            self.assertNotIn(removed, env)
        self.assertEqual((env['AWS_CONFIG_FILE'], env['AWS_SHARED_CREDENTIALS_FILE']), ('/dev/null', '/dev/null'))
        # No bucket-read, list or delete call exists in the mirror at all.
        source = Path(mirror.__file__).read_text()
        for forbidden in ('get-object', 'list-objects', 'delete-object', 's3 sync', 's3 rm', 's3 cp'):
            self.assertNotIn(forbidden, source)


class InfrastructureTests(unittest.TestCase):
    def test_bucket_is_private_versioned_encrypted_and_retained(self):
        generated = template()
        self.assertEqual(json.loads(Path('transcripts/infra/archive.cfn.json').read_text()), generated)
        self.assertEqual(set(generated['Resources']), {'Archive', 'ArchivePolicy'})
        bucket = generated['Resources']['Archive']
        self.assertEqual((bucket['DeletionPolicy'], bucket['UpdateReplacePolicy']), ('Retain', 'Retain'))
        properties = bucket['Properties']
        self.assertEqual(set(properties['PublicAccessBlockConfiguration'].values()), {True})
        self.assertEqual(len(properties['PublicAccessBlockConfiguration']), 4)
        self.assertEqual(properties['VersioningConfiguration'], {'Status': 'Enabled'})
        self.assertEqual(properties['OwnershipControls']['Rules'], [{'ObjectOwnership': 'BucketOwnerEnforced'}])
        self.assertEqual(properties['BucketEncryption']['ServerSideEncryptionConfiguration'][0]
                         ['ServerSideEncryptionByDefault'], {'SSEAlgorithm': 'AES256'})
        self.assertNotIn('LifecycleConfiguration', properties)
        statements = generated['Resources']['ArchivePolicy']['Properties']['PolicyDocument']['Statement']
        self.assertEqual([(s['Effect'], s['Condition']) for s in statements],
                         [('Deny', {'Bool': {'aws:SecureTransport': 'false'}})])
        self.assertNotIn('Allow', json.dumps(generated))
        self.assertEqual(bucket_name('000000000000'), BUCKET)

    def test_host_grant_is_write_only_on_the_two_record_prefixes(self):
        allow, deny = host_statements(BUCKET)
        resources = ['arn:aws:s3:::' + BUCKET + '/records/*', 'arn:aws:s3:::' + BUCKET + '/by-bank/*']
        self.assertEqual(allow, {'Sid': 'WriteOnlyTranscriptArchive', 'Effect': 'Allow', 'Action': 's3:PutObject', 'Resource': resources})
        self.assertEqual(deny, {'Sid': 'DenyOtherArchiveWrites', 'Effect': 'Deny', 'Action': 's3:PutObject', 'NotResource': resources})
        # Every key the mirror can produce falls under those two prefixes.
        for key, _ in mirror.plan(*record()):
            self.assertTrue(key.startswith(('records/', 'by-bank/')))

    def test_installer_validates_arguments_before_any_change_and_spares_enclave_units(self):
        installer = Path('transcripts/infra/install_archive_sync.sh')
        text = installer.read_text()
        self.assertLess(text.index('exit 1'), text.index('install -d'))
        for forbidden in ('peer-link-transcript-relay', 'peer-link-transcript-enclave', 'peer-link-transcript-credentials',
                          'peer-link-transcript-health', '/opt/peer-link-transcripts/', 'nitro-cli', 'systemctl restart', 'systemctl stop'):
            self.assertNotIn(forbidden, text)
        self.assertIn('ProtectSystem=strict', text)
        for arguments in ([], ['script', 'not-a-digest', BUCKET, REGION], ['script', '0' * 64, 'Bad_Bucket', REGION],
                          ['script', '0' * 64, BUCKET, 'us-east-1;id']):
            result = subprocess.run(['bash', str(installer)] + arguments, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
