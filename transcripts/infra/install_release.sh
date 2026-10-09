#!/usr/bin/env bash
# Run through SSM on this dedicated host only. Installs a checked candidate;
# cryptographic checking is not campaign/release approval.
set -euo pipefail
umask 077
if [[ $# != 3 && $# != 4 ]]; then
  echo 'usage: install_release.sh SOURCE_ROOT SIGNED_EIF MEASUREMENT_MANIFEST [HOST_INSTANCE_ID]' >&2
  exit 2
fi
source_root=$(realpath "$1")
image=$(realpath "$2")
manifest=$(realpath "$3")
# Validate the durable invocation before any provisioning command, file copy,
# virtualenv, symlink or systemd change. A corrected rerun must remain possible.
durable_mode=$(python3.11 - "$source_root/transcripts/policy.json" <<'PYTHON'
import json, sys
print('durable' if json.load(open(sys.argv[1])).get('stateAuthority') is not None else 'ram')
PYTHON
)
if [[ "$durable_mode" == durable && $# != 4 ]]; then
  echo 'Durable installation requires a valid reviewed host instance ID.' >&2
  exit 1
fi
if [[ $# == 4 && ! "$4" =~ ^i-[0-9a-f]{17}$ ]]; then
  echo 'Installation requires a valid reviewed host instance ID.' >&2
  exit 1
fi
base=/opt/peer-link-transcripts
test "$(nitro-cli --version)" = 'Nitro CLI 1.5.0'
test -f "$source_root/transcripts/runtime.py"
test -f "$source_root/transcripts/server.py"
if python3.11 - "$source_root/transcripts/policy.json" <<'PY'
import json, sys
sys.exit(0 if json.load(open(sys.argv[1])).get('payoutAuthority', {}).get('kind') == 'aws_kms' else 1)
PY
then
  # KMS is brokered by the host's narrowly scoped instance role, never live keys.
  command -v aws >/dev/null
  test -f "$source_root/transcripts/kms_broker.py"
  test -f "$source_root/transcripts/kms_signer.py"
fi
# Refuse to overwrite an active epoch or silently discard a funded wallet.
test ! -e "$base/current"
test "$(nitro-cli describe-enclaves | python3.11 -c 'import json,sys; print(len(json.load(sys.stdin)))')" = 0
install -d -m 700 "$base/releases/candidate"
nitro-cli describe-eif --eif-path "$image" > "$base/releases/candidate/eif-description.json"
python3.11 - "$image" "$manifest" "$base/releases/candidate/eif-description.json" <<'PY'
import hashlib, json, re, sys
from pathlib import Path
image, manifest, description = map(Path, sys.argv[1:])
expected = json.loads(manifest.read_text())
actual = json.loads(description.read_text())
assert actual.get('CheckCRC') is True, 'EIF CRC rejected'
assert actual.get('IsSigned') is True, 'unsigned EIF rejected'
assert actual.get('SignatureCheck') is True, 'EIF signature rejected'
assert re.fullmatch('[0-9a-f]{96}', expected.get('eifSha384', '')), 'missing exact signed image hash'
with image.open('rb') as stream:
    assert hashlib.file_digest(stream, 'sha384').hexdigest() == expected['eifSha384'], 'image hash mismatch'
measurements = expected.get('measurements', {})
assert set(measurements) == {'0', '1', '2', '8'}, 'expected PCR0/1/2/8 required'
for index, value in measurements.items():
    assert re.fullmatch('[0-9a-f]{96}', value) and value != '0'*96, 'invalid PCR'
    assert actual['Measurements']['PCR' + index] == value, 'PCR mismatch'
print('Signed candidate hash, CRC, signature, and PCR0/1/2/8 match; hardware quote still required.')
PY
cp "$image" "$base/releases/candidate/image.eif"
cp "$manifest" "$base/releases/candidate/measurement-manifest.json"
cp -a "$source_root/transcripts" "$base/releases/candidate/transcripts"
install -d "$base/releases/candidate/verification/trust"
for file in __init__.py common.py attestation.py nsm.py; do
  cp "$source_root/verification/$file" "$base/releases/candidate/verification/$file"
done
cp "$source_root/verification/trust/aws-nitro-root.pem" "$base/releases/candidate/verification/trust/"
cp "$source_root/verification/requirements.lock" "$base/releases/candidate/verification/"
python3.11 -m venv "$base/venv"
"$base/venv/bin/pip" install --disable-pip-version-check --no-cache-dir \
  -r "$base/releases/candidate/verification/requirements.lock"
"$base/venv/bin/pip" install --disable-pip-version-check --no-cache-dir --only-binary=:all: \
  -r "$base/releases/candidate/transcripts/requirements.lock"
ln -s "$base/releases/candidate" "$base/current"
# Durable state calls use enclave TLS/SigV4. Start the memory-only credential
# forwarder before enclave boot; exact instance identity comes from the reviewed
# installation target, never a contributor or arbitrary runtime request.
durable_dependencies=''
if [[ "$durable_mode" == durable ]]; then
  credential_role=$(python3.11 - "$source_root/transcripts/policy.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))['stateAuthority']['credentialRoleArn'])
PY
)
  bash "$base/current/transcripts/infra/install_credentials.sh" "$credential_role" "$4"
  durable_dependencies='peer-link-transcript-credentials.service'
fi
cat > /etc/systemd/system/peer-link-transcript-enclave.service <<'UNIT'
[Unit]
Description=Dedicated PeerLink transcript enclave candidate
After=nitro-enclaves-allocator.service peer-link-transcript-relay.service
Requires=nitro-enclaves-allocator.service peer-link-transcript-relay.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/peer-link-transcripts/current
RuntimeDirectory=peer-link-transcripts
RuntimeDirectoryMode=0700
ExecStart=/bin/bash -c 'umask 077; /usr/bin/nitro-cli run-enclave --eif-path image.eif --cpu-count 2 --memory 2048 --enclave-cid 16 > /run/peer-link-transcripts/enclave.json'
ExecStop=/opt/peer-link-transcripts/venv/bin/python /opt/peer-link-transcripts/current/transcripts/infra/stop_enclave.py /run/peer-link-transcripts/enclave.json
Restart=no
StandardOutput=null
StandardError=null
UNIT
if [[ -n "$durable_dependencies" ]]; then
  install -d -m 700 /etc/systemd/system/peer-link-transcript-enclave.service.d
  cat > /etc/systemd/system/peer-link-transcript-enclave.service.d/durable-state.conf <<UNIT
[Unit]
After=$durable_dependencies
Requires=$durable_dependencies
[Service]
Type=notify
NotifyAccess=main
RemainAfterExit=no
TimeoutStartSec=150
TimeoutStopSec=75
ExecStart=
ExecStart=$base/venv/bin/python -m transcripts.infra.supervise_enclave --root $base/current --instance-id $4 --record /run/peer-link-transcripts/enclave.json
ExecStop=
UNIT
else
  # An explicitly reviewed non-durable install cannot inherit a stale drop-in.
  rm -f /etc/systemd/system/peer-link-transcript-enclave.service.d/durable-state.conf
fi
cat > /etc/systemd/system/peer-link-transcript-relay.service <<'UNIT'
[Unit]
Description=Ciphertext ingress and TLS-byte egress for dedicated transcript enclave
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
NotifyAccess=main
TimeoutStartSec=35
WorkingDirectory=/opt/peer-link-transcripts/current
ExecStart=/opt/peer-link-transcripts/venv/bin/python -m transcripts.server --port 8080 --enclave-cid 16 --vsock-port 5100 --egress-port 5101 --kms-port 5103
Restart=no
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
StateDirectory=peer-link-transcripts
StateDirectoryMode=0700
RestrictAddressFamilies=AF_INET AF_INET6 AF_VSOCK AF_UNIX
StandardOutput=null
StandardError=null
UNIT
# Continuous service needs a separate hardware/nonce/release gate for this image.
for unit in enclave relay credentials; do
  rm -f "/etc/systemd/system/peer-link-transcript-$unit.service.d/continuous.conf"
done
systemctl disable peer-link-transcript-enclave.service peer-link-transcript-relay.service peer-link-transcript-credentials.service peer-link-transcript-health.service 2>/dev/null || true
systemctl daemon-reload
# Deliberately do not enable: a host reboot must not silently create a new RAM epoch.
# Type=notify waits for egress5101/archive5102/KMS5103 bind/listen. The separate
# credential Type=notify service already confirmed5104 before this point.
systemctl start peer-link-transcript-relay.service
systemctl start peer-link-transcript-enclave.service
"$base/venv/bin/python" - "$base/current" <<'PY'
import signal, sys, time
from pathlib import Path
from urllib.request import build_opener, ProxyHandler

deadline = time.monotonic() + 90

def deadline_expired(*_):
    raise TimeoutError('candidate_health_failed')

def check_health():
    root = Path(sys.argv[1])
    sys.path.insert(0, str(root))
    from transcripts.common import digest, require, strict_json
    from transcripts.artifacts import validate_epoch_descriptor
    policy = strict_json((root/'transcripts/policy.json').read_bytes(), 1_000_000)
    expected = digest(policy)
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open('http://127.0.0.1:8080/health',
                             timeout=min(5, max(0.01, deadline-time.monotonic()))) as response:
                require(response.status == 200, 'candidate_health_failed')
                health = strict_json(response.read(16_385), 16_384)
            require(health.get('service') == 'peerlink-transcripts'
                    and type(health.get('version')) is int and health['version'] == 1
                    and health.get('mode') == 'nitro-pilot'
                    and health.get('accepting') is False
                    and health.get('policyDigest') == expected, 'candidate_health_failed')
            validate_epoch_descriptor(health.get('epoch'), policy)
            return
        except Exception:
            time.sleep(min(0.5, max(0, deadline-time.monotonic())))
    raise RuntimeError('candidate_health_failed')

try:
    signal.signal(signal.SIGALRM, deadline_expired)
    signal.alarm(90)
    check_health()
except Exception:
    print('Candidate health verification failed.', file=sys.stderr)
    sys.exit(1)
finally:
    signal.alarm(0)
PY
if ! systemctl is-active --quiet peer-link-transcript-enclave.service peer-link-transcript-relay.service; then
  echo 'Candidate health verification failed.' >&2
  exit 1
fi
echo 'Candidate started; independently verify fresh Nitro quote and all gates before credentials/funding.'
