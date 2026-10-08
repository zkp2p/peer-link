#!/usr/bin/env bash
# Linux amd64 disposable build host only. No keys or live credentials needed.
set -euo pipefail
umask 077
source_root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$source_root"
out=${1:-"$source_root/.local/transcript-build"}
install -d -m 700 "$out"
out=$(realpath "$out")
test "$(nitro-cli --version)" = 'Nitro CLI 1.5.0'
export NITRO_CLI_ARTIFACTS="$out/nitro-artifacts"
install -d -m 700 "$NITRO_CLI_ARTIFACTS"
base='python@sha256:4b4c524dc3dce996864e030c7bd9c6b0e517597189fee48f48e05b499442444b'
docker build --platform linux/amd64 --no-cache --build-arg "BASE_IMAGE=$base" \
  -f transcripts/infra/Dockerfile -t peer-link-transcripts:candidate .
nitro-cli build-enclave --docker-uri peer-link-transcripts:candidate \
  --output-file "$out/unsigned.eif" > "$out/build-measurements.json"
nitro-cli describe-eif --eif-path "$out/unsigned.eif" > "$out/unsigned-description.json"
python3.11 - "$out" "$base" <<'PY'
import hashlib, json, sys
from pathlib import Path
directory, base = Path(sys.argv[1]), sys.argv[2]
description = json.loads((directory/'unsigned-description.json').read_text())
assert description['CheckCRC'] is True and description['IsSigned'] is False
with (directory/'unsigned.eif').open('rb') as stream:
    image_hash = hashlib.file_digest(stream, 'sha384').hexdigest()
report = {'status':'unsigned-candidate', 'baseImage':base, 'nitroCliVersion':'1.5.0',
          'measurements': description['Measurements'], 'eifSha384':image_hash,
          'signed':False, 'hardwareVerified':False, 'liveAcceptance':False}
(directory/'candidate-build.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report))
PY
echo 'Unsigned candidate only. Sign with a dedicated review key; record signed PCR8/hash and verify on Nitro.'
