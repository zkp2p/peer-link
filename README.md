# PeerLink

**Contribute your bank. Earn USDC for useful evidence.**

PeerLink is building a transcript contribution service. Your local agent learns the
read-only route to your bank's transaction history. An attested AWS Nitro enclave
acquires fresh bank responses, extracts redacted endpoint/schema evidence, and uses
your inference API key to grade its usefulness. Peer engineers turn accepted evidence
into Curator metadata and attestation transformers. You do not write a provider or
open a contribution PR.

**Mercury: experimental first-contributor source validation, $10 USDC for one
accepted organization.** Its first positive live API acquisition is pending;
this is not a completed Peer integration. Check [Mercury #1](https://github.com/zkp2p/peer-link/issues/1)
and the independently approved [release](transcripts/release.json), then obtain a
funded reservation before keys or inference. Capacity is not guaranteed. Other
bank rewards remain planned; Wise is excluded from reward recruitment.

[Website](https://link.peer.xyz) · [Contribution guide](CONTRIBUTING.md) ·
[Campaign issues](https://github.com/zkp2p/peer-link/issues) · [Rewards](docs/incentives.md) ·
[Merit project profile](https://terminal.merit.systems/zkp2p/peer-link)

## Start with your local agent

> Read AGENTS.md and skills/contribute-transcript/SKILL.md in
> https://github.com/zkp2p/peer-link. Check the release and my bank's campaign first.
> Help me contribute a read-only banking transcript using my own inference key.
> Verify attestation before encrypting credentials. Do not initiate payments or
> publish banking data. Stop if the release or campaign is unavailable.

The [contribution skill](skills/contribute-transcript/SKILL.md) owns the current
runbook. The account owner signs in and completes MFA. The agent checks scope,
privacy consent, job limits and capacity, prepares a recipe, verifies the measured
release and encryption key, and encrypts the submission to the enclave.

The enclave performs the actual approved bank reads over TLS. Local captures are
navigation hints, not authenticated evidence. Deterministic structural redaction
happens **before grading**: ordinary approved inference providers receive only the
redacted artifact, not raw bank responses, session credentials or payout keys.
Provider-visible inference still requires explicit consent. Confidential NEAR
inference is unavailable until its attested encrypted adapter is verified.

The ordinary NEAR route is implemented for canonical `z-ai/glm-5.3-flash`,
with explicit consent to NEAR and its approved Chutes upstream. It requests no
aliasing, rejects alias/model mismatches and unapproved serving-provider headers,
and makes at most one grading call. Those gateway assertions over TLS are not
independent model attestation. Paid provider-visible tool-call and strict-JSON
schema checks passed; confidential inference remains unavailable.

## Rewards and costs

Each bank has one campaign issue with a fixed **$5 or $10 USDC reward per accepted
contribution**, its access status and available capacity. Collect **1–5 distinct
contributors per bank**; pay at most once per contributor/account per campaign.
There is no issue-claim comment, assignment or provider PR requirement.

**You pay inference even for rejected or failed jobs.** Peer pays infrastructure,
payout gas and accepted rewards. Code enforces bank authenticity, eligibility,
redaction, duplicates, budget and the fixed payout; the model cannot choose an
amount or recipient. Reward availability is campaign-specific, not implied by
an issue listing. See [terms](docs/incentives.md) and [privacy](docs/privacy.md).

The architecture caps rewards at $50 USDC with no automatic refill. The revised
candidate's measured budget is $5 for one $5 contribution. The separate $1
operator KMS recovery test confirmed its return. A supervised Wise job then
completed authenticated enclave reads, redaction and paid NEAR grading, followed
by a [confirmed $5 payout](https://basescan.org/tx/0x88899fbe3b6036390f19207ec911493db6f1245ab1c50811c44ca2ee4752c677).
The job first returned `payout_pending` and needed one signed operator reconciliation.
A fresh client restored the same signed receipt without another reservation or
submission. That completed one-slot test allocation has no remaining capacity;
it does not establish public availability.
The revised payout design uses a non-exportable AWS KMS signing key. Authorized
operator IAM and the host signing broker can sign outside the enclave and recover
funds; this is not exclusive enclave custody. The completed one-slot pilot
kept ledger and deduplication authority RAM-only. Restart of that historical pilot
requires operator review and does not make its wallet reuse or old-job continuation
safe. The durable Wise tests below provide internal validation only. The built
operator retirement flow permanently closes admission, finishes and archives
existing obligations, and refunds remaining USDC only to the fixed deployer address.
Its runtime accepts no arbitrary refund recipient or ETH sweep; its live refund
path has not yet been demonstrated. Operator KMS recovery is separate from that
runtime flow. The earlier enclave-only pilot's $50 remains unrecovered at this
checkpoint; changing custody for a new release does not recover its old key.

Before funding the revised wallet, the signed operator preflight must exercise
real Base RPC and KMS refund signing while paused with zero USDC. The public
operator response excludes raw signed bytes, and code does not broadcast. The
host broker can see the signature/digest and reconstruct the fixed one-unit refund;
this is not signature secrecy from the operator. The new host signing route and
independent signature verification passed. The KMS candidate at `c2bc4b0` was
independently reproduced in [CI 37874831981](https://github.com/zkp2p/peer-link/actions/runs/37874831981)
and verified on live Nitro hardware, including key/wallet/policy bindings. Public
release approval remains a separate gate. The
[$1 operator recovery receipt](https://basescan.org/tx/0xf1447663200c551dbe42d2d989982563209076b56f9d1f56f8175895eb39e5da)
verified the fixed deployer return and zero remaining USDC with the relay stopped;
it does not prove the enclave retirement flow.

## Internal Wise validation; Mercury source-validation campaign

**Mercury first-contributor source validation:** [$10 USDC for one accepted
organization](https://github.com/zkp2p/peer-link/issues/1). Its first positive live
API acquisition is pending and would come from the contributor; this is not a
completed Peer integration. Other bank rewards remain planned. Wise is an existing
integration/reference and is excluded from rewards; its paid tests are internal
validation only. Independently verify the approved release and obtain a funded
reservation before keys or inference. Static copy cannot guarantee capacity.

The internal validation service was `https://9lb70whku9.execute-api.us-east-1.amazonaws.com`,
with measured source `629b8798fe4181a1d8e7d52fb3ad0c85d1339c7e`.
Fresh Nitro verification, authenticated Wise reads, ordinary NEAR grading, an
automatic confirmed $5 payout and paid-job recovery after an enclave restart passed.
Recovery preserved the signed receipt without another reservation, submission or
model call. See the separately scoped
[durable evidence](transcripts/durable-pilot-evidence.json) for verified scope and remaining limitations.

The v3 release uses encrypted job/deduplication/payout snapshots and a
version-fenced state authority. Restore stays paused for operator review and
chain reconciliation; interrupted bank/model calls fail without a paid retry.
Bank sessions and inference keys remain transient. Bank-upload ingress keys are
fresh per boot and never persisted; only the separate receipt signer is encrypted
in durable state. Later snapshot recovery cannot recover prior upload decryption
keys. KMS administrators remain trusted for metadata/deduplication secrecy.
The Wise hardware and paid-job/restart scope was verified; see the
[durable contract and release gates](docs/transcript-contributions-prd.md).

## Develop and inspect

Node 20.19+, npm, Python 3.11+ and OpenSSL. Credential-free checks need no bank
account or inference key.

```sh
npm ci --ignore-scripts
npm run check:bank
npm run verify:setup
npm run check
npm run transcripts:setup
npm run transcripts:test
npm run dev
```

`transcripts/` contains the new service. `app/` is the public landing page.
Existing `banks/` adapters, fixtures and reports remain reference assets under
MIT; their presence does not make them the paid contribution workflow.

[PRD](docs/transcript-contributions-prd.md) · [Evidence](docs/evidence.md) ·
[Legacy verifier](docs/verification.md) · [Operations](docs/transcript-operations.md) ·
[Developer docs](https://docs.peer.xyz/developer/peer-link) · [Security](SECURITY.md)

## Retired provider program

The provider-authoring bounty program is retired. Its
[archived terms](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/docs/incentives.md) and
[archived adapter instructions](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/skills/contribute-bank/SKILL.md)
remain historical records, not current enrollment instructions. Previously earned
or accepted awards retain their original terms. Closing a legacy PR for the program
change does not cancel an accepted obligation or decide a disputed claim.

PeerLink is independent of Plaid and the named banks; bank names identify source
campaigns and reference integrations. Copyright (c) 2026 Sachin Kumar and contributors.
[MIT](LICENSE).
