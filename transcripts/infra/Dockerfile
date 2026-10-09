# Same reviewed amd64 base as the existing verification build. Override only with
# another reviewed immutable digest; this image never contains live credentials.
ARG BASE_IMAGE=python@sha256:4b4c524dc3dce996864e030c7bd9c6b0e517597189fee48f48e05b499442444b
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/peer-link
COPY verification/requirements.lock /tmp/verification-requirements.lock
COPY transcripts/requirements.lock /tmp/transcript-requirements.lock
RUN pip install --no-cache-dir --no-compile --require-hashes --only-binary=:all: -r /tmp/verification-requirements.lock \
    && pip install --no-cache-dir --no-compile --require-hashes --only-binary=:all: -r /tmp/transcript-requirements.lock
# Shared primitives only: no previous verifier controller or release policy.
COPY verification/__init__.py verification/common.py verification/nsm.py verification/attestation.py /opt/peer-link/verification/
COPY verification/trust/aws-nitro-root.pem /opt/peer-link/verification/trust/aws-nitro-root.pem
# Exact enclave import closure. Never copy release.json: its PCR manifest is
# independently pinned discovery metadata and cannot recursively measure itself.
# Host relay/client/CLI, tests, infrastructure configs and local caches stay out.
COPY transcripts/__init__.py transcripts/artifacts.py transcripts/channel.py \
    transcripts/common.py transcripts/epoch.py transcripts/eth_payout.py \
    transcripts/ledger.py transcripts/kms_signer.py transcripts/payout.py transcripts/policy.py \
    transcripts/providers.py transcripts/recipe.py transcripts/runtime.py \
    transcripts/storage.py transcripts/transport.py transcripts/wire.py /opt/peer-link/transcripts/
COPY transcripts/policy.json /opt/peer-link/transcripts/policy.json
COPY transcripts/infra/boot.py /opt/peer-link/transcripts/infra/boot.py
# Import-only verification creates no epoch, keys or connections.
RUN python -B -c "import transcripts.runtime"
RUN find /usr/local /opt /tmp -exec touch -h -d @0 {} +
ENTRYPOINT ["/usr/local/bin/python", "/opt/peer-link/transcripts/infra/boot.py"]
