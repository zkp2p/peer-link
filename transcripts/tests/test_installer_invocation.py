"""Invalid durable CLI must exit before provisioning commands or partial release."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path('transcripts/infra/install_release.sh').resolve()


class InstallerInvocationTests(unittest.TestCase):
    def run_invalid(self, fourth=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source'
            (source/'transcripts').mkdir(parents=True)
            (source/'transcripts/policy.json').write_text(json.dumps({'stateAuthority': {'kind': 'synthetic'}}))
            image, manifest = root/'image.eif', root/'manifest.json'
            image.write_bytes(b'synthetic')
            manifest.write_text('{}')
            binary = root/'bin'
            binary.mkdir()
            (binary/'python3.11').symlink_to(sys.executable)
            touched = root/'provisioning-called'
            # Reaching even the first Nitro query violates upfront validation;
            # stop the spy before any fixed /opt or systemd operation can occur.
            spy = binary/'nitro-cli'
            spy.write_text('#!/bin/sh\n: > "$INSTALLER_TEST_MARKER"\nexit 99\n')
            spy.chmod(0o700)
            args = ['bash', str(INSTALLER), str(source), str(image), str(manifest)]
            if fourth is not None:
                args.append(fourth)
            env = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'], INSTALLER_TEST_MARKER=str(touched))
            result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn('valid reviewed host instance ID', result.stderr)
            self.assertFalse(touched.exists(), 'Invalid invocation reached provisioning')
            self.assertEqual(sorted(p.name for p in source.iterdir()), ['transcripts'])

    def test_missing_host_id_leaves_no_install_side_effects(self):
        self.run_invalid()

    def test_malformed_host_id_leaves_no_install_side_effects(self):
        for value in ['', 'i-1234', 'i-0123456789ABCDEF0', 'wrong-host', 'i-0123456789abcdef0;echo data']:
            with self.subTest(value=value):
                self.run_invalid(value)


if __name__ == '__main__':
    unittest.main()
