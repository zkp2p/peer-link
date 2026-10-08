#!/usr/bin/env bash
# Run through SSM on this dedicated host only. Installs a checked candidate;
# cryptographic checking is not campaign/release approval.
set -euo pipefail
umask 077
if [[ $# != 3 ]]; then
  echo 'usage: install_release.sh SOURCE_ROOT SIGNED_EIF MEASUREMENT_MANIFEST' >&2
  exit 2
fi
source_root=$(realpath "$1")
image=$(realpath "$2")
manifest=$(realpath "$3")
base=/opt/peer-link-transcripts
test "$(nitro-cli --version)" = 'Nitro CLI 1.5.0'
test -f "$source_root/transcripts/runtime.py"
test -f "$source_root/transcripts/server.py"
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
cat > /etc/systemd/system/peer-link-transcript-enclave.service <<'UNIT'
[Unit]
Description=Dedicated PeerLink transcript enclave candidate
After=nitro-enclaves-allocator.service
Requires=nitro-enclaves-allocator.service

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
cat > /etc/systemd/system/peer-link-transcript-relay.service <<'UNIT'
[Unit]
Description=Ciphertext ingress and TLS-byte egress for dedicated transcript enclave
After=peer-link-transcript-enclave.service network-online.target
Requires=peer-link-transcript-enclave.service
BindsTo=peer-link-transcript-enclave.service

[Service]
Type=simple
WorkingDirectory=/opt/peer-link-transcripts/current
ExecStart=/opt/peer-link-transcripts/venv/bin/python -m transcripts.server --port 8080 --enclave-cid 16 --vsock-port 5100 --egress-port 5101
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
systemctl daemon-reload
# Deliberately do not enable: a host reboot must not silently create a new wallet.
systemctl start peer-link-transcript-enclave.service
systemctl start peer-link-transcript-relay.service
systemctl is-active --quiet peer-link-transcript-enclave.service peer-link-transcript-relay.service
echo 'Candidate started; independently verify fresh Nitro quote and all gates before credentials/funding.'
