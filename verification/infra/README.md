# Isolated Nitro pilot runbook

Owner: Peer Link. Environment: pilot. Scope: a new tagged Nitro build/test host only.
The deployer must supply and verify its AWS account, profile, region, VPC and subnet.
Never reuse an existing payment attestor, its keys, or its bank sessions.

Before provisioning:

1. Record caller identity, region, exact source commit and local tests. Confirm no
   existing Peer Link pilot is running. Verify the subnet belongs to the specified VPC.
2. Estimate c6i.xlarge instance, 24 GB gp3 volume, public IPv4 and transfer charges.
   Reserve a conservative upper bound in `verification.cli reserve-expense` within
   the task's $50 cap. AWS credits do not increase the authorized spending limit.
3. Validate `pilot.cfn.json`. Inspect IAM and network changes. The role has SSM
   management access only; no production secrets or application data permissions.
4. Deploy one named stack with explicit account/profile/region and project tags.
   No inbound ports are allowed. Use Systems Manager to build and test.

The host is configured to shut down after 110 minutes and terminate on shutdown;
its root volume is deleted. This is a one-time resource-lifetime guard, not an agent
judgment schedule. Confirm that shutdown is actually scheduled before starting work.
If bootstrap fails, terminate through the owning stack. Do not leave a failed build
host running. External operator cleanup remains required; this timer is not a formal
guarantee against arbitrary provider billing.

Build the enclave from the exact source archive and pinned dependencies. Do not put
API keys or sessions in image layers, Docker arguments, SSM commands or user-data.
Publish a release only after independent rebuilds agree, real Nitro attestation is
verified, negative security tests pass, and policy/consent bindings are checked.
Never fill `release.json` with example measurements and call it approved.

For non-interactive SSM builds, set `NITRO_CLI_ARTIFACTS` to a dedicated writable
build directory. Nitro bootstrap does not preserve Docker PATH/WORKDIR assumptions:
the image uses an absolute Python executable and `verification/boot.py` to resolve
its package location. Do not add debug mode to a release test; debug measurements
must be rejected. Debug console diagnosis is limited to disposable images without secrets.

Record instance ID, source/archive digest, enclave image measurements, test results,
actual lifecycle and conservative cost. Keep account-specific coordinates under ignored
`.local/verification/`, not in contributor instructions.

Rollback/cleanup: stop accepting attempts; terminate the pilot enclave, delete the
owning CloudFormation stack, verify the instance is terminated and its volume deleted.
Preserve public build evidence and private cost accounting. Never delete unrelated
instances, roles, images, log groups or keys by a name-prefix guess.

## Bank egress relay

The October 2 synthetic hardware test exercised this relay with TLS terminating
inside Nitro. It did not approve a live bank source policy. After source-policy
approval, install the same reviewed source policy on the parent
and in the measured enclave image. Run `python -m verification.relay --enclave-cid
<verified-cid>` on the parent using the actual enclave CID from the current launch.
The relay binds vsock port 5001, checks the peer CID and has no TCP listener. Do not
add a caller-selected hostname, port, HTTP proxy or host-side TLS termination.
Select `transport="nitro"` in the trusted enclave acquisition call. Bank credentials
never belong on the parent. Restart/review the relay when the enclave CID changes.

Keep the pilot lifetime guard and budget reservation in force. Relay time/byte/rate
limits are per process, not a substitute for persistent controller admission. Test
real vsock TLS, wrong CID, stalled DNS and certificate rejection on the disposable
pilot before calling this transport hardware verified. The checked-in source policy
is disabled, so the relay intentionally refuses to start.

## Rebuild comparison

Use the same immutable base digest, exact source archive and pinned Nitro toolchain.
Build twice with `docker build --no-cache`, then run `nitro-cli build-enclave` for
each image. Compare every PCR measurement and separately compare complete EIF
SHA-384 hashes; neither comparison substitutes for the other. Run
`nitro-cli describe-eif --eif-path <image>` to inspect metadata differences.

The Dockerfile disables pip bytecode compilation and normalizes installation/source
mtimes. The [September 23 experiment](evidence/2026-09-23-nitro-reproducibility.json)
obtained matching PCR0/1/2 on one host, but different EIF hashes. Do not publish
these experimental measurements in `release.json`: independent reproduction,
byte-identical artifact handling and signed hardware validation remain unresolved.

CI now runs `build_measurements.sh` on two separate disposable Ubuntu runners and
compares source/toolchain/base pins and PCR0/1/2. The builder uses a digest-pinned
Amazon Linux container and Nitro CLI 1.5.0. Reports and installed package inventories
are retained seven days; unsigned EIF files are not published as releases. Complete
EIF hashes are reported separately and may differ due to metadata. This workflow
must pass before independent-runner measurement agreement is claimed.

The builder container controls the runner's Docker socket. Run this script only on
a disposable, credential-free Linux build host, never alongside production containers
or bank sessions. It neither starts an enclave nor provisions AWS. Matching CI
measurements do not establish hardware attestation, PCR8 signing or release approval.

`inspect_eif.py` is a read-only diagnostic for unsigned x86_64 EIF v4. It verifies
CRC, section bounds/counts and payload sizes, then emits per-section hashes without
extracting payloads. It rejects signed or unknown formats. CI compares every
non-metadata section and the installed builder package inventory across runners,
in addition to PCRs. This diagnostic does not normalize images, verify signatures
or authorize release; its purpose is to locate byte-reproduction differences before
any metadata rewrite is considered.

`normalize_eif.py` is a separate pre-signing tool. It accepts only the inspected
unsigned x86_64 v4 layout, replaces volatile informational metadata with canonical
JSON and a source-commit label, recomputes offsets/CRC, and verifies that every
non-metadata payload digest is unchanged. It creates a new file exclusively and
refuses signed inputs. Source labels are not authenticated provenance.

CI then asks Nitro CLI to inspect the normalized file, requires valid CRC and
identical original PCR0/1/2, and compares normalized whole-file SHA-384 across the
two runners. This experiment must succeed before byte-reproducibility is claimed.
No signed artifact is normalized, no attestation checks are removed, and hardware
launch/signing/release approval remain separate requirements.

When rebuilding a GitHub source archive, preserve the same file modes as a Git
checkout. Root extraction of the codeload tarball retained `664/775` modes and
changed PCR2. In the disposable hardware test, extracting into an empty directory
with `(umask 022; tar --no-same-permissions --no-same-owner -xzf source.tar.gz
--strip-components=1 -C source)` restored checkout-equivalent `644/755` modes and
produced the exact CI-normalized EIF hash. Never accept a new hash merely because
a build used a different extraction method.


## Fixed manual controller

Generate a reviewable CloudFormation template with
`python -m verification.infra.manual_template > manual.cfn.json`. Its required
inputs name the dedicated VPC/subnet, a private versioned worker bundle, the
bundle SHA-256 and an independently approved release digest. Deploy with
`DispatchEnabled=false`. The bundle is operator-built and contains the reviewed
EIF, parent relay and pinned dependencies; never build it from a contributor PR
in a privileged job. The current synthetic pilot's image filename is
`synthetic.eif`; this template is not an approved bank release.

The worker role pins the S3 object version with an allow and an explicit deny for
other or missing versions, so another bucket-policy grant cannot widen that pin.
It can read only that S3 object version and open SSM transport. It
cannot read Parameter Store or Secrets Manager, use KMS, assume roles or access
other artifacts. Explicit denies cover every other action and S3 resource, so a
resource policy elsewhere in the shared account cannot widen the role. User data verifies the bundle digest before extraction, starts
one enclave without debug mode and binds its opaque gateway to localhost. There
are no inbound security-group rules. Public IPv4 plus outbound TLS avoids a NAT
gateway; the enclave's bank allowlist is narrower than the host's egress policy.

The operator seeds the single DynamoDB `budget` row with `committedMicroUsd`
including **all earlier task reservations** and `paused: true`. Creation must use
`attribute_not_exists(id)`. Never reset this row to recover from an error or stack
redeploy. The ledger is retained on stack deletion and has deletion protection and
point-in-time recovery; disabling protection is a separate, explicit cleanup step.
A new stack creates a new table, so carry forward the retained ledger's committed
total before unpausing. A separately reviewed
approval row `approval/<32-hex-id>` contains `state: approved`, `releaseDigest`,
`artifactDigest` and an unexpired integer `expiresAt`. No credentials go in rows.

After the trusted deployment and GitHub protection gates pass, the operator can
unpause the ledger and enable dispatch. One transaction reserves $2, acquires the
sole active lease and consumes an exact approval. Only the immutable launch
template version supplies deployment settings; request fields cannot override
an AMI, role, network, user data or instance count. A launch failure burns the
reservation and keeps its lease until the external reconciler establishes that
no worker remains. Never retry an uncertain launch automatically.

The expiry Lambda runs every five minutes, terminates only this stack's tagged
workers older than 110 minutes or in stopping/stopped state, and clears a lease
only after termination is observed. A host shutdown timer is an additional guard.
CloudWatch alarms on expiry errors and on a reaper that stops running. Pass
`AlarmTopicArn` (an SNS topic with a confirmed, tested subscription) to route both;
without it they notify no one. The current pilot has operator supervision, not
unattended alerts.

The checked-in manual GitHub workflow is disabled by default. Before activation,
verify protected main and CODEOWNERS review, required CI, environment reviewers,
prevent-self-review, main-only environment deployment rules and restricted
repository/environment variable administration. Publish a reviewed controller
Lambda **version**. An OIDC role must trust only the exact repository/environment
and allow only `lambda:InvokeFunction` on that version ARN. It must have no
`PassRole`, deployment, SSM, secret or bank-data permissions. Record the live
protection responses; merely adding CODEOWNERS or YAML is not enforcement.

The workflow requests GitHub's OIDC token directly and exchanges it with the
fixed regional STS HTTPS endpoint for a 15-minute session. This keeps the organization rule that
permits only GitHub/Peer-owned Actions intact. It verifies the account, role and
numeric controller version before requesting a token, rejects redirects and
unexpected assumed identities, and passes credentials only to the invocation
subprocess. No token file, cross-step credential export or repository checkout is
used. STS exchange stays in memory; the Lambda CLI has retries explicitly disabled. Failures are redacted and are never retried automatically.

Cleanup: pause the budget and disable dispatch first; let the owning reaper
terminate the exact test worker, verify its disk deletion and lease clearance,
then remove the test stack. Export audit rows before disposing of an explicitly
disposable synthetic ledger. An artifact stack with `DeletionPolicy: Retain`
requires separate cleanup of its exact owned object versions and bucket; do not
leave it behind assuming stack deletion removes it. Keep the task-wide cost
reservation until billing reconciliation. Never delete by broad name prefix.


## Persistent operations and owner approval

Generate `verification.infra.operations_template` for a private, versioned artifact
bucket, a dedicated non-exportable P-384 KMS signing key, a signing-only role and
persistent CloudWatch → SNS → encrypted SQS delivery. The operator ARN is explicit;
no runtime worker, GitHub workflow or Peer production role can sign. An email subscription
must be confirmed by its recipient and tested before unattended dispatch.
The operator permission key is separate Ed25519 authority kept outside the checkout
in an owner-only file; only its public key belongs in an approved image.

The fixed controller accepts `LedgerTableName` to reuse the retained canonical
ledger. Verify its existing budget and active lease before deployment; never seed
or replace an existing row. `ControllerName` allows an exact stable function name.
Deploy disabled, inspect the exact bundle version/digest, test refusal, then publish
an immutable numeric Lambda version. The old disabled version remains a rollback
coordinate, but ledger pause is the immediate stop for every published version.

Create or reuse the account's GitHub OIDC provider only after checking its URL and
`sts.amazonaws.com` audience. Generate `verification.infra.invoke_template` with
that numeric controller version. Its role permits only that invocation, with explicit
denies preventing another resource policy from widening it. Apply these variables:

- Repository `PEER_LINK_DISPATCH_ENABLED`: `false` until the activation gates pass.
- Protected environment `PEER_LINK_AWS_ACCOUNT`: the verified account ID.
- Protected environment `PEER_LINK_INVOKE_ROLE`: the stack's invoke-role ARN.
- Protected environment `PEER_LINK_CONTROLLER_VERSION_ARN`: the numeric version ARN.

For the initial Peer Link operation, Kohai (`kohai-peer`) triggers the main-branch
workflow and Sachin (`0xSachinK`) is the sole required environment reviewer. Keep
`prevent_self_review` enabled and deployment branches restricted to `main`. Kohai
cannot approve, write AWS admission rows, deploy, sign or access bank credentials
through this workflow. GitHub repository administrators remain a trust boundary.

A synthetic operational drill may use the independently reproduced, signed image
whose bank and operator policies are disabled. Confirm real hardware attestation,
fixed deployment identity, denial of source overrides, approval replay, concurrent
launches and budget exhaustion. This drill grants no live bank access. The earlier
full synthetic acquisition/adapter/receipt test is separate evidence; neither
substitutes for an approved bank policy and account-owner consent.

Before live activation, freeze and review the source policy, operator public key,
image hash, PCR0/1/2/8, artifact and release digests together. Rebuild independently,
verify the exact hardware release, and obtain owner consent on the owner's device.
Never transplant synthetic measurements into a bank release.

Rollback: set the repository dispatch variable false and atomically pause the
existing DynamoDB budget. Revoke unconsumed approvals; already issued offline
permits can survive up to two minutes. Terminate only workers tagged with this
controller stack ID, verify volume deletion, then let the owning reaper clear the
matching lease. Preserve reserved spending and signing/artifact evidence. Do not
delete retained ledgers, keys or artifact versions as part of an ordinary rollback.


### Signing a reproduced image

Create and retain one public X.509 certificate for the dedicated KMS key with
`python -m verification.infra.signing_certificate --help`. The tool uses a
15-minute signing-only session, verifies the returned certificate signature and
refuses to overwrite a certificate. Keep the certificate unchanged for its validity
period: PCR8 identifies the certificate, so generating another changes PCR8.
The KMS private key is never exportable and is not placed in CI or on workers.

A disposable signing host may temporarily assume only the dedicated signing role
while it signs an already reproduced, digest-checked EIF. Pin its S3 input version
and output object, keep the normal expiry guard, and remove that exact host from
the signing-role trust before launching the signed worker. Do not run submitted
adapter code on the signing host. Compare PCR0/1/2 before and after signing; record
PCR8 and the complete signed EIF hash. Runtime workers have neither signing nor
role-assumption permissions.
