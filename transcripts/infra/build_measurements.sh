#!/usr/bin/env bash
# Credential-free transcript build only. Use a disposable Linux x86_64 host with Docker.
set -euo pipefail
umask 077
root=$(git rev-parse --show-toplevel)
cd "$root"
test -z "$(git status --porcelain --untracked-files=normal)" || { echo "Build requires a clean committed checkout" >&2; exit 1; }
revision=$(git rev-parse HEAD)
out="$root/.local/transcript-nitro-build"
mkdir -p "$out"
# Same immutable Python image used by the hardware pilot.
base='python@sha256:4b4c524dc3dce996864e030c7bd9c6b0e517597189fee48f48e05b499442444b'
builder='amazonlinux@sha256:bc20ab39b3e976096f7e5782e9457eb5144810a3cbdbfdbe111d1b31b82f47b4'
docker build --platform linux/amd64 --no-cache --build-arg "BASE_IMAGE=$base" -f transcripts/infra/Dockerfile -t peer-link-transcripts-ci:eif .
# The socket grants control of this disposable build host. Never run on a host
# containing credentials, bank sessions, production containers or signing keys.
docker run --rm --platform linux/amd64 -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$out:/output" -v "$root/verification/infra:/tools:ro" -e SOURCE_REVISION="$revision" "$builder" bash -euc '
    dnf install -y aws-nitro-enclaves-cli-1.5.0 aws-nitro-enclaves-cli-devel-1.5.0 docker
    test "$(nitro-cli --version)" = "Nitro CLI 1.5.0"
    export NITRO_CLI_ARTIFACTS=/tmp/nitro-artifacts
    mkdir -p "$NITRO_CLI_ARTIFACTS"
    nitro-cli build-enclave --docker-uri peer-link-transcripts-ci:eif --output-file /output/image.eif > /output/measurements.json
    python3 /tools/normalize_eif.py /output/image.eif /output/normalized.eif "$SOURCE_REVISION"
    nitro-cli describe-eif --eif-path /output/normalized.eif > /output/normalized-description.json
    rpm -qa | sort > /output/builder-packages.txt
  '
sudo chown -R "$(id -u):$(id -g)" "$out"
python3 verification/infra/inspect_eif.py "$out/image.eif" > "$out/sections.json"
python3 - "$revision" "$base" "$builder" "$out" <<'PY'
import hashlib,json,sys,shlex
from pathlib import Path
revision,base,builder,directory=sys.argv[1:]
p=Path(directory)
m=json.loads((p/'measurements.json').read_text())['Measurements']
assert set(m)=={'HashAlgorithm','PCR0','PCR1','PCR2'}
normalized=json.loads((p/'normalized-description.json').read_text())
assert normalized['CheckCRC'] is True and normalized['IsSigned'] is False
assert normalized['Measurements']==m, 'normalization changed PCRs'
# Capture only the exact files copied into the measured image, rather than a
# broad source-tree digest that would include the independently published PCRs.
dockerfile=Path('transcripts/infra/Dockerfile')
copy_sources=[]
for line in dockerfile.read_text().replace("\\\n", " ").splitlines():
    words=shlex.split(line,comments=True)
    if words and words[0]=='COPY':
        assert len(words)>=3
        for name in words[1:-1]:
            source=Path(name)
            assert source.is_file() and not source.is_symlink() and not source.is_absolute()
            assert '..' not in source.parts and not any(c in name for c in '*?[')
            copy_sources.append(name)
assert 'transcripts/release.json' not in copy_sources
assert not any('/tests/' in name or '__pycache__' in name for name in copy_sources)
inputs={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in sorted(set(copy_sources))}
result={'service':'peerlink-transcript-contributions','sourceCommit':revision,'baseImage':base,'builderImage':builder,'nitroCliVersion':'1.5.0',
        'measurements':m,'eifSha384':hashlib.file_digest((p/'image.eif').open('rb'),'sha384').hexdigest(),
        'normalizedEifSha384':hashlib.file_digest((p/'normalized.eif').open('rb'),'sha384').hexdigest(),
        'normalizationPreservedPcrs':True,'normalizedCrcVerifiedByNitro':True,
        'signed':False,'hardwareAttested':False,'liveVerification':False,
        'eifSections':json.loads((p/'sections.json').read_text()),
        'builderPackagesSha256':hashlib.sha256((p/'builder-packages.txt').read_bytes()).hexdigest(),
        'dockerfileSha256':hashlib.sha256(Path('transcripts/infra/Dockerfile').read_bytes()).hexdigest(),
        'transcriptRequirementsSha256':hashlib.sha256(Path('transcripts/requirements.lock').read_bytes()).hexdigest(),
        'verificationRequirementsSha256':hashlib.sha256(Path('verification/requirements.lock').read_bytes()).hexdigest(),
        'buildContextAllowlistSha256':hashlib.sha256(Path('transcripts/infra/Dockerfile.dockerignore').read_bytes()).hexdigest(),
        'measuredInputs':inputs,
        'measuredInputsSha256':hashlib.sha256(json.dumps(inputs,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
(p/'build-report.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
PY
