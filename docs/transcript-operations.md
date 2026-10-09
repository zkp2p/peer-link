# Transcript pilot operations

This is a dedicated PeerLink deployment. It does not change a production attestor,
reuse its signing key, or inherit its approval. The deployment may expose public
campaign/status/attestation metadata while live contribution and payout gates remain
closed. Infrastructure creation, a signed EIF and a successful synthetic job do not
establish live bank acceptance.

## Architecture and limits

`transcripts/infra/pilot.cfn.json` provisions one `c6i.xlarge` (4 vCPU, 8 GiB), with
2 enclave vCPU and 2048 MiB reserved by the Nitro allocator. The parent retains 2
vCPU and approximately 6 GiB. Its 32 GiB gp3 root is encrypted and deleted on
instance termination. VPC and public subnet are explicit parameters; an existing
dedicated verification network can be reused after live route/ownership checks.

The generated API Gateway HTTPS endpoint requires no external domain. It proxies
to the dedicated host's stable Elastic IP on TCP 8080. The host API translates
bounded public HTTP commands into length-prefixed JSON RPC on enclave CID 16,
vsock 5100. Credentials and private job data must already be application-encrypted
to the freshly attested enclave key. API Gateway, host HTTP and operators never
receive bank-session or inference plaintext. Never put a key in an HTTP header,
query string, URL, SSM command, Docker layer or log. Public receipt/status data must
also follow the transcript API's redaction contract.

TCP 8080 is publicly reachable because API Gateway's public HTTP integration has
no exclusive source security group. Gateway rate limits (2 requests/second, burst
5) can be bypassed through that address; server/enclave admission, body sizes,
timeouts and concurrency bounds remain mandatory. This route protects confidentiality
through the application encryption protocol, not through host-side TLS. Do not
advertise a host HTTP URL as the contributor endpoint. A future private VPC link
and load balancer can narrow network exposure at additional fixed cost.

Egress uses enclave-to-parent vsock CID 3, port 5101. The enclave sends a bounded
newline-terminated JSON connection request `{"host":"approved.example","port":443}`.
The parent checks enclave CID, configured hostname allowlist, public resolved IP
and port, replies exactly `OK\n`, then forwards opaque bytes. Bank/provider TLS,
certificate verification, HTTP paths/methods and tool rules live inside the enclave.
The parent cannot substitute a TLS certificate or read cookies/model content.

The revised host IAM role allows SSM transport and explicitly scoped
`kms:GetPublicKey`/`kms:Sign` for the one policy-bound payout key. Production
secrets, S3, other KMS keys, role assumption and Parameter Store remain outside
that role. Native KMS signing is not restricted to enclave PCRs; authorized host
and operator IAM are part of the custody trust boundary.
There is no SSH key or port 22. Operators transfer reviewed source/EIF files through
SSM or a short-lived presigned URL; the URL is access-bearing and must stay out of
public docs and durable command-output captures.

## Provision

Use the actual verified account, region and network in the commands below. Shell
variables contain coordinates only; never put application secrets in them. Check
STS account ID and subnet VPC, explicit default route through an Internet Gateway,
current stack ownership, expected AMI architecture and Nitro instance support.
Do not overwrite an existing unrelated stack or change the reused network.

```bash
aws sts get-caller-identity --profile "$profile" --region "$region"
aws ec2 describe-subnets --profile "$profile" --region "$region" --subnet-ids "$subnet"
aws ec2 describe-instance-types --profile "$profile" --region "$region" --instance-types c6i.xlarge
python3 transcripts/infra/template.py > transcripts/infra/pilot.cfn.json
aws cloudformation validate-template --profile "$profile" --region "$region" \
  --template-body file://transcripts/infra/pilot.cfn.json
aws cloudformation create-stack --profile "$profile" --region "$region" \
  --stack-name "$stack" --template-body file://transcripts/infra/pilot.cfn.json \
  --capabilities CAPABILITY_IAM \
  --parameters ParameterKey=VpcId,ParameterValue="$vpc" \
    ParameterKey=SubnetId,ParameterValue="$subnet" \
    ParameterKey=LifetimeHours,ParameterValue=24
```

Supply `AlarmTopicArn` only for an existing SNS topic with a confirmed, tested
subscription. With its default empty value, alarms exist but send no notifications;
the pilot requires active operator supervision. Bootstrap installs Nitro CLI 1.5.0,
Docker and Python 3.11, starts SSM/allocator, and deliberately starts no application.
Check CloudFormation events and SSM online status before transferring source. Through
SSM, verify `cloud-init status`, the package version, allocator YAML, Docker, and
`nitro-cli describe-enclaves` (empty before first launch).

## Build and measured candidate

Create a private source archive of the exact reviewed tree. Record both Git commit
and archive SHA-256, including uncommitted implementation content if the pilot
precedes its final commit. Normalize extraction permissions (`umask 022`,
`tar --no-same-permissions --no-same-owner`) before builds. Verify the archive digest
on the host before extraction. No sessions, secrets, wallet keys or ignored `.local/`
content enter the archive. Inspect the actual file list.

On a disposable Linux amd64 build host:

```bash
bash transcripts/infra/build_candidate.sh /opt/peer-link-transcripts/build
```

This uses the immutable Python base and exact-version, hash-pinned verification
and transcript dependency locks, installing binary wheels only with required hash
verification. The Dockerfile has an explicit runtime-file allowlist; the published
release manifest, host tools, tests and caches are outside the measured image.
It produces an **unsigned candidate**, measurements
and a complete image SHA-384. Compare independent rebuild PCR0/1/2; record complete
EIF hashes separately. Volatile metadata can change whole-file hashes. The existing
`verification/infra/normalize_eif.py` may normalize an unsigned v4 candidate before
signing, after its payload-preservation checks and identical PCRs are verified.
Never normalize a signed image.

Sign with a dedicated transcript release certificate/key; do not reuse production
attestor or wallet keys. Keep release signing keys outside the parent host/source/CI
artifacts. A supervised candidate test may generate a separate short-lived ECDSA
P-384 signing key on the dedicated build host with directory mode 0700 and file
mode 0600. Never export/upload that key, treat it as a production release authority,
or retain it after the candidate's test lifecycle. Its certificate/PCR8 is public.
Nitro CLI supports `sign-eif --eif-path <candidate> --signing-certificate <certificate>
--private-key <protected-path-or-supported-KMS-ARN>`. Capture `describe-eif` after
signing: valid CRC/signature, real PCR0/1/2/8 and complete signed EIF SHA-384. The
operator-owned measurement manifest has exactly `eifSha384` and `measurements`
containing string keys `0`, `1`, `2`, `8`; all are lowercase SHA-384 hex, nonzero.
It is a comparison input, not a release approval flag.

Install on the dedicated SSM host:

```bash
bash transcripts/infra/install_release.sh "$source_root" "$signed_eif" "$measurement_manifest"
```

The installer refuses an active release/enclave, verifies the signed file and all
four PCRs against the manifest, installs pinned dependencies, and starts fixed
CID 16 without debug. Services use `Restart=no` and are deliberately **not enabled**
at boot. Reboot or enclave loss requires a new explicitly checked epoch. There is
no automatic ledger restoration, reactivation or wallet refill. KMS custody survives
enclave loss, but wallet reuse requires operator review. Operational logs discard application
stdout/stderr; diagnose only fixed status/reason codes and credential-free probes.

The enclave invokes `transcripts.runtime --vsock-port 5100 --egress-port 5101`;
the parent invokes `transcripts.server --port 8080 --enclave-cid 16 --vsock-port
5100 --egress-port 5101`. Changing policy, image contents or the boot command
requires new measurements and review.

## Attestation and smoke gates

Resolve the public `ApiUrl` from stack outputs. Probe `/health`, `/v1/campaigns`
and `/v1/release`. The latter is **discovery-only** and names the canonical release
source; it is not an approved PCR manifest or trust anchor. Publish final signed
image measurements and the approved manifest separately after the build, then pin
that manifest independently in the contributor client. Embedding the image's own
final PCRs into itself would be circular. Inspect the pinned manifest's expiry and
actual service/campaign capabilities. From an independent
client, obtain a fresh challenge/quote, verify AWS's Nitro trust chain/signature,
nonce, timestamp, exact PCR0/1/2/8, public-key and policy bindings against independently
reviewed measurements. Reject debug/zero PCRs, wrong nonce/key/policy/measurement,
unsigned/unreleased image and stale quote. Never trust a server `verified` boolean.

Exercise a synthetic encrypted job and the real enclave TLS tunnel before sending
owner-authorized bank credentials: malformed/oversized frames, replayed submission,
expired reservation, wrong CID, hostname/IP/port mismatch, TLS rejection, unapproved
provider/model, consent mismatch and capacity/budget rejection must fail closed.
The host must not log or receive decrypted submission values. Public gateway health
does not prove the bank or inference tool loop works.

Use only an owner's explicitly authorized read-only bank flow for a live check.
Inference uses that contributor's approved provider credential; no Peer fallback
key/billing route exists. Record provider/model, consent mode, billed usage and
fixed limits; delayed provider-side quota enforcement is not an exact dollar cap.
Verify confidential-provider attestation separately from ordinary provider-visible
inference. Do not advertise unavailable modes.

## Verified candidate checkpoint

On October 9, KMS candidate `c2bc4b02e533bc82cfaf349a771d2b616f9981ee`
passed 165 credential-free tests and [CI 37874831981](https://github.com/zkp2p/peer-link/actions/runs/37874831981).
Two independent builds matched measured inputs, PCR0/1/2 and normalized unsigned
EIF hashes. Fresh live Nitro certificate/COSE, nonce/key/policy/epoch, PCR and KMS
descriptor/wallet bindings verified. Paid ordinary NEAR strict-JSON verification
succeeded with 2048 output tokens and low reasoning effort; merchant credit was
verified. These are scoped candidate/provider checks, not public release approval. A separate [$1 external operator recovery](https://basescan.org/tx/0xf1447663200c551dbe42d2d989982563209076b56f9d1f56f8175895eb39e5da)
confirmed the exact fixed-deployer USDC return and zero remaining balance while
the relay was stopped. That confirms operator KMS custody recovery, not enclave
retirement. A supervised Wise job then completed authenticated enclave acquisition,
redacted NEAR grading and a [confirmed $5 reward](https://basescan.org/tx/0x88899fbe3b6036390f19207ec911493db6f1245ab1c50811c44ca2ee4752c677)
after one signed operator reconciliation from `payout_pending`. A fresh client
restored the same signed receipt without new reservations/submissions. The one-slot
test leaves no funded capacity; public collection remains closed. See [evidence](../transcripts/kms-pilot-evidence.json).

## Wallet and state gates

The revised pilot uses a non-exportable AWS KMS payout key. Authorized operator
IAM and the host broker can request signatures outside the enclave and recover
funds. No exclusive-enclave or PCR-restricted key access is claimed. Verify the
immutable key ARN, derived wallet and measured `payoutAuthority` against exact v2
epoch metadata before approval. Do not send bank or inference credentials to KMS
or the signing broker. Keep the changed release paused until independent image,
policy, custody and live signing checks pass.

Before allocating any funds, use the signed operator `preflight` action while
paused with **zero USDC**. It must exercise real Base RPC balances/nonce and KMS
signing of a one-minor-unit USDC refund. Code does not broadcast; the public
operator response omits raw signatures/transaction bytes. The host broker sees
the signature/digest and can reconstruct the fixed refund, so no signature secrecy
from an authorized host/operator is claimed. Preserve that scoped result before funding; a synthetic signer or an old
image's quote cannot establish the new route's availability. Real funding and
confirmed transfers remain separate evidence gates.

The in-memory anchor only prevents replay within its live epoch. Host snapshots,
database rows, signed archives and a surviving KMS key do not restore trusted
ledger/nonce/dedup authority. After restart, stop admissions and require operator
review of old obligations, transactions and balances before any wallet reuse.

After the paused signing preflight, complete a separately authorized $1 KMS recovery
test and confirm its return before allocating the new candidate's measured $5 budget.
The architecture maximum is $50; it is not the current funding amount. The paused
Wise campaign capacity is one contributor. Require
descriptor `budgetMinor` to match measured `pilotBudgetMinor` exactly. Fund only an
independently attested epoch address and once within that exact budget plus bounded
gas. Record address, epoch, funding transaction and chain
receipt in the task's private spend ledger; public records contain no secrets.
There is no automatic refill. A restarted enclave must stay closed to previously
funded claims and old reservations. KMS permits operator fund recovery after enclave
loss, but not safe continuation with a blank ledger. The prior enclave-only wallet
already holds $50 USDC that remains unrecovered at this checkpoint. Leave that
old live enclave intact while reconciling it; installing the KMS release cannot
recover its old key. Broad acceptance stays closed pending verified persistence,
deduplication and reconciliation authority.

Before a planned stop, use the implemented signed operator `retire` action. It
irreversibly closes admission and cancels unused reservations, while submitted,
verifying and payment obligations must finish. Reconcile existing payouts and
archive every pending redacted signed record before retirement finalizes. The
runtime refunds remaining bounded USDC only to the fixed deployer address, using
one immutable refund transaction identity. It accepts no arbitrary destination,
performs no ETH sweep or ledger restore. Operator KMS recovery is a separate path
outside measured runtime payout rules. The flow has
synthetic coverage; do not call its live refund verified until a real receipt and
destination-balance check are recorded.

Independently confirm terminal job/archive state, retirement state, the exact USDC
refund receipt and recipient before stopping a funded enclave. Refund confirmation
is not permission to assume remaining ETH was swept. If retirement is blocked or
uncertain, keep the funded epoch under supervision and reconcile the same operation;
do not discard its process to update code. KMS recovery does not reconstruct its
ledger; a new image or restored EBS volume cannot recover the old enclave-only key.
Plan this before the infrastructure lifetime deadline.

### Operator KMS recovery

This recovery CLI is for the new policy-bound KMS wallet only. It cannot recover
the old enclave-only wallet. Quiesce every signer for that KMS wallet, including
the enclave and operators on other machines, before planning or executing recovery;
the CLI's local file lock does not coordinate their nonces.

```bash
.local/transcript-venv/bin/python -m transcripts.operator_recovery \
  --policy transcripts/policy.json --state .local/revamp/operator-recovery.json
```

The default is plan-only: read the KMS public key and Base balances, fees and
nonce. It uses AWS profile `peer`, region `us-east-1`, and checks the exact
policy-bound ARN/wallet, Base chain 8453, native USDC and fixed deployer refund
recipient. Review the destination, balance and proposed bounded transfer before
adding `--execute` under the task's fund-transfer authority. The maximum is $50
USDC and residual ETH is not swept.

Execution signs and fsyncs the raw transaction/hash to the ignored local state
before broadcasting. Re-run the same command and state path to reconcile the
same identity and confirm a two-block receipt. Never delete, replace or regenerate
pending state, start another signer, or publish that file. Recovery can return
funds but does not restore jobs, deduplication or payment ledger authority. Its
live outcome requires actual chain evidence; implemented tooling alone is not a
successful recovery.

`confirmed_but_balance_nonzero` means the saved refund confirmed but the wallet
still has USDC. Preserve the confirmed record; choose a new state path only after
independently verifying that receipt and quiescing every signer. For
`recovery_nonce_conflict` or `unknown_pending_nonce`, inspect latest/pending nonces
and identify the competing pending or mined transaction. Preserve the saved raw
bytes/hash and reconcile its receipt or verified replacement/failure. Do not delete
state or re-sign blindly; establish that the original cannot later settle before
starting a new operation.

## Monitoring, lifetime and rollback

CloudWatch alarms monitor EC2 status-check failures, API 5xx, expiry Lambda errors
and a missing expiry heartbeat. The external expiry Lambda executes every five
minutes and can stop **only instances tagged with this CloudFormation stack ID**
after `LifetimeHours` (24 by default) since launch. It has no production stop or
secret authority. Restart is manual; restarting the host resets EC2 launch-time
age and needs an explicit new cost/epoch check. Stop preserves the encrypted root
but destroys enclave memory. The guard is a cost bound, not fund recovery.

Reconcile the funded epoch **before** its lifetime deadline. Do not fund close to
expiry or rely on the five-minute polling gap. The operator must plan the shutdown
or explicitly extend the authorized supervised test through a reviewed stack update
before risking authoritative job state or the old enclave-only key. No schedule
alone guarantees complete cleanup or spend. The earlier enclave-only host has a
bounded shutdown deadline of **2026-10-10 17:11:57 UTC**; reconcile its unrecovered
$50 before that deadline or explicitly authorize a reviewed supervised extension.

Rollback first stops admission/relay while keeping any funded enclave alive long
enough for reviewed reconciliation. `systemctl stop peer-link-transcript-relay`
removes network ingress without restarting the enclave. Once safe to discard its
ephemeral ledger state, stop `peer-link-transcript-enclave`; its stop helper targets only the
recorded enclave ID. Do not use `nitro-cli terminate-enclave --all` on shared hosts.

Delete only the named owning stack after verifying current account, tags and wallet
disposition and a separate authorized KMS retention/recovery plan. Do not infer
permission to delete or disable the payout key from permission to remove compute.
Confirm stack deletion, EC2 termination, encrypted root deletion,
Elastic IP release, API/roles/schedule/alarm removal, and no remaining artifact
copies with credentials. The reused VPC/subnet remain outside this stack. Stopping
the host alone leaves EBS, Elastic IP, API and alarm charges. Preserve redacted
hardware evidence, source/image hashes and actual cost accounting.

## Cost assumptions

Checked October 9, 2026 for Linux/shared/on-demand `c6i.xlarge` in us-east-1 using
AWS Pricing API: **$0.17/hour** (SKU `JPN4K2NQVRWGTQGS`, price effective October 1).
At that rate the host costs $4.08/24h or $124.10/730h. One public IPv4 costs
[$0.005/hour](https://aws.amazon.com/vpc/pricing/) ($0.12/day, $3.65/730h).
At [$0.08/GB-month gp3](https://aws.amazon.com/ebs/pricing/), 32 GiB costs about
$2.56/month. Combined base infrastructure is approximately **$4.29/day or $130.31
per 730-hour month**, before four CloudWatch alarms, detailed API metrics, API
requests, Lambda/EventBridge, S3 artifacts and transfer. [HTTP API
pricing](https://aws.amazon.com/api-gateway/pricing/) is usage based; check the
current regional request tier. No NAT gateway/load balancer/custom domain is
required. Do not assume AWS credits/free tier or quote a final reconciled bill.
Rewards, gas and contributor-funded inference are separate ledger entries.

AWS reference: [HTTP proxy integrations](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-http.html),
[Nitro supported instance families](https://docs.aws.amazon.com/enclaves/latest/user/nitro-enclave.html),
[enclave allocator](https://docs.aws.amazon.com/enclaves/latest/user/multiple-enclaves.html).

The completed owner-authorized KMS pilot retired with zero USDC and zero obligations.
The runtime reported `refunded` with amount zero and no refund transaction; this
checks empty-epoch closure, not a nonzero runtime refund. Operator KMS recovery
was separately verified with the $1 transfer. The dedicated NEAR test key was
disabled after the job and its local in-memory credential process was stopped.

## Settlement retries after the live pilot

The follow-up runtime starts at most 60 settlement attempts within a 120-second
monotonic window, with existing per-call transport timeouts. It retries explicit
transient RPC, KMS and archive failures using the accepted job and saved payment
identity. It never repeats bank acquisition or inference. Pause and permanent
validation failures stop the loop; exhausted obligations remain for signed operator
reconciliation. Final archival retries cannot mutate an already published signed
receipt. Credential-free regressions cover these cases; the live evidence above
continues to describe the earlier `c2bc4b0` image and its assisted reconciliation.
