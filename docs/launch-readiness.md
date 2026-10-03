# Launch review — October 2, 2026

## Status update — October 2, 2026 (evening)

- Landing (`link.peer.xyz`) and docs (`docs.peer.xyz/developer/peer-link`) are in
  production. The Merit project holds **$1,000** across 20 banks at $50 each; see
  [incentives](incentives.md).
- A review pass fixed one medium owner-client bug (stale attestation after slow
  owner input) and several session-burning robustness bugs, made `enclave-compare`
  fail when a build fails, hardened worker IAM, the ledger and expiry alarms, and
  added a CSP. GitHub secret scanning, push protection and Dependabot alerts are on.
  AWS now has a $50 tag-filtered budget, an active `Project` cost tag, a protected
  ledger, an emptied default security group and a termination-protected network stack.
- The compiled Mercury adapter and reference oracle agreed on every supported record
  of a live company history page ([evidence](../verification/infra/evidence/2026-10-02-mercury-live-adapter-check.json)).
  The enclave path has hardware evidence only with synthetic data. Replaying a web
  session from AWS is not attempted: it needs the session cookie outside the
  browser and may trip Mercury's device and IP controls. Prefer a read-only Mercury
  API token with its own reviewed adapter surface for the first live enclave run.
- The generic attestation endpoint now separates caller-selected freshness nonces
  from session-context quotes. The owner refreshes only an issued, unchanged,
  active challenge; controller and client reject a generic quote for an invented
  context. This protocol change needs new hardware evidence before live release.
- Still open: a second human code owner and environment reviewer, creating the
  OIDC invoke role at activation, a persistent tested human alert route and final
  hardware validation. PR #81 has merged; bank access remains disabled.

The sections below are the earlier launch review, kept for history.

**Production is on hold.** The project is named **Peer Link**, as selected by the
owner. No three-user testing gate applies.

## Gap assessment and completed work

| Area | Finding and implementation | Remaining release gate |
| --- | --- | --- |
| Repository | Canonical workspace migration preserved Git history, uncommitted work and linked worktrees. GitHub transfer and rename to `zkp2p/peer-link` are verified by stable repository ID. Launch PR #72 is published with required CI and review protection. | Independent trusted review and approved merge. The PR author cannot approve their own CODEOWNERS review. |
| Private adoption | Original public candidate mapping makes precision, identity provenance and unauthenticated source status explicit. Private Peer code and signing fields stay private. | Each bank still needs its own private-service review and production approval. |
| Verifier | The previous components were not a deployable end-to-end manual service. Runtime execution, owner client, exact-version receipts, minimization and controller admission are now connected. | Independent rebuild and hardware validation of the final release candidate; approved source policy, signing identity and owner-consented live test. |
| Deployment | Dedicated VPC, least-privilege roles, immutable worker launch settings, durable budget/lease and external cleanup were exercised on AWS. The protected `peer-link-verification` environment now permits only `main`, requires a reviewer, prevents self-review and disables administrator bypass. | Exercise denied-ref/approval cases, publish a pinned controller version and configure an invoke-only OIDC role. Dispatch stays disabled. |
| Incentives | A 500 USDC sponsor deposit is confirmed. Proposed awards total $175, each bank capped at $50. Claims were checked before retiring 58 non-priority unfunded proposals and replacing the two priority proposals. | Confirm project allocation and payout eligibility before announcing funded assignments. |
| Docs and copy | Peer Link docs are in [draft PR #2037](https://github.com/zkp2p/zkp2p-clients/pull/2037); final docs CI and preview passed. Shoku provided Peer Link copy and video v6 for review only. | Independent review and explicit production approval. |
| Landing hosting | The existing Vercel project is renamed `peer-link`, transferred to Peer and connected to `zkp2p/peer-link`. Production and rollback history moved with it. The Peer-hosted preview passed desktop/mobile checks. | Approve production promotion and the final branded domain. Old domains remain compatibility addresses until a replacement is configured and verified. |

## Concrete security findings

- **A 100× amount mismatch was corrected before release.** Native minor units
  cannot be copied directly into Peer's current two-decimal settlement input.
  The original bridge would have passed 25,000 VND as 25,000 settlement units.
  It now produces 2,500,000, retains source precision and rejects rounding or
  integer overflow. This change is original contract mapping; no private parser
  implementation or fixture was copied.

- **Live bank access is not approved.** The checked-in source policy and release
  remain disabled. The synthetic test's disposable signer and approved fixture
  policy are not production credentials or bank evidence. Being logged in to a
  bank is not client consent.
- **GitHub privilege protection is an external dependency.** The manual workflow
  contains no checkout or bank secrets. Contributor code cannot supply deployment
  inputs. It must remain disabled until actual repository/environment controls
  and the exact AWS OIDC policy are verified after transfer.
- **Private evidence needed tighter handling.** The trusted reader now validates
  duplicate selection before minimizing the selected record. The guest receives
  necessary payment identifiers, not credentials, names, balances, memos or other
  transactions. Guest strings never appear in the public receipt. Required
  identifiers are still sensitive while inside the enclave.
- **Company Mercury data warrants a narrower read surface.** The existing web
  history operation can retrieve up to 100 records inside the enclave. The client
  now discloses that scope. Mercury documents a [read-only token tier](https://docs.mercury.com/docs/getting-started)
  and [single-transaction endpoint](https://docs.mercury.com/reference/gettransaction).
  Review that surface's field semantics and a separately scoped API adapter before
  preferring it over a company browser session. No company session was accessed
  during these tests; do not infer API/web schema equivalence.
- **Same-account separation has limits.** The dedicated VPC has no peering or
  inbound rules. Worker roles cannot read production secrets, use KMS or assume
  roles; the manual worker could read only its pinned synthetic bundle version.
  Account administrators, AWS control plane, quotas and billing remain shared.
- **Resource guards are bounded controls, not a billing guarantee.** Atomic
  admission reserved $2 per worker against a $50 infrastructure limit, including
  previous reservations; concurrency is one. Host shutdown and an independent
  expiry Lambda limit lifetime. Billing lag, service failure or administrator
  overrides remain risks. Actual billing has not yet been reconciled.
- **Monitoring is not unattended yet.** Cleanup results and CloudTrail were
  inspected directly, and expiry errors have a CloudWatch alarm. An end-to-end
  notification route still needs a real delivery test before unattended use.
- **The trusted computing base remains substantial.** AWS attestation, the
  owner client, release approver, Python, Wasmtime and the enclave kernel are
  trusted. Memory is not guaranteed zeroized; timing/outcome channels and software
  vulnerabilities remain. A report does not establish recipient credit or final
  settlement, and never authorizes payout or a production attestation.

See the [architecture diagram and attack paths](architecture.md).

## Validation evidence

The current local candidate passes `npm run check`: 77 TypeScript tests, 165
Python tests, types, lint, coverage, fixture/report validation, privacy scanning
and the landing build. The later operator CLI and settlement mapping changes
have local coverage; the hardware record below names the earlier source it
actually tested. It is not hardware evidence for the final candidate.

The [synthetic hardware record](../verification/infra/evidence/2026-10-02-synthetic-e2e.json)
identifies the source commit, Wasm hash, EIF hash, measured PCRs and receipt digest.
It records real AWS attestation, client encryption, enclave-terminated HTTPS,
compiled guest execution, independent oracle comparison and receipt verification.
Wrong nonce/policy/measurement, replay and an invalid source credential were
rejected. AWS tests rejected unapproved/overridden requests, a concurrent worker,
consumed approvals and paused admission. Both test workers terminated, both
encrypted disks were deleted, and the active lease was cleared. The test fixture
and worker artifacts are disposable; no production release is implied.

## Release and rollback proposal

The reviewed docs preview currently corresponds to commit
`0edd2dcb59ec805daf13d17bb46c4107e4f3eb9e`, deployment
`dpl_Gci3fNTkVqjX3pSscxZSxeQ5tmgo`; [CI run 9538](https://github.com/zkp2p/zkp2p-clients/actions/runs/36992657720)
and all four Vercel preview builds passed. The [docs preview](https://docs-o3gn20ajj-zkp2p.vercel.app/developer/peer-link)
was checked in the browser, including the source-to-settlement unit example. The previous
docs production coordinate is commit `39918abc349f0e0e9142230738c7f8850c964d41`,
deployment `dpl_BzUq3XgEVqWyFS5AGh1nedpJSue7`. Re-read these immediately before
approval/promotion because other releases can advance them. No production
verifier exists to roll back to; disabling admission is its safe baseline.

1. The repository transfer, branch publication and protection settings are
   complete. Obtain independent trusted review without bypassing CODEOWNERS or
   protected-branch checks. Keep ordinary PR CI free of AWS/signing/bank credentials.
2. Confirm the Merit project allocation, recheck claims, activate the published
   bank scopes and smaller amounts, then reply to Vietcombank and Monobank. Preserve earned
   obligations. Funding receipts do not themselves activate an award.
3. Freeze the verifier candidate; obtain independent matching builds, isolated
   signer/operator authority and an approved bank source policy. Repeat hardware
   negative tests and complete one owner's explicit local-client consent test.
   No bank session belongs in a chat, workflow, issue or AI prompt.
4. Present the exact commits, image/adapter digests, protection evidence, live-test
   result, cost ledger and previous deployment identifiers for Sachin's production
   approval. Do not enable public bank sessions with the synthetic manifest.
5. After approval, merge through main and fast-forward `releases/docs/prod` only
   when it has no unique commits. Verify the resulting Vercel SHA at docs.peer.xyz.
   Deploy the landing page explicitly, and enable only the approved manual
   verifier release. Social copy/video remain review-only until approved.

Rollback starts by disabling dispatch and pausing admission, then revoking the
release manifest and terminating exact owned workers. Verify termination, disk
deletion and lease clearance before removing infrastructure. Retain cost/audit
records and never refund uncertain reservations automatically. Restore docs or
landing content with a reviewed revert through normal release history; do not
force a production branch or reactivate an old signing authority.
