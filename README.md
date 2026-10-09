# PeerLink

**Contribute your bank. Earn USDC for useful evidence.**

PeerLink is building a transcript contribution service. Your local agent learns the
read-only route to your bank's transaction history. An attested AWS Nitro enclave
acquires fresh bank responses, extracts redacted endpoint/schema evidence, and uses
your inference API key to grade its usefulness. Peer engineers turn accepted evidence
into Curator metadata and attestation transformers. You do not write a provider or
open a contribution PR.

**Status: unreleased; not accepting bank credentials or paid contributions.** A bank
listing, a deployed host, or synthetic tests do not establish live availability.
Only use an independently verified approved [release](transcripts/release.json)
and an active, funded bank campaign.

[Website](https://link.peer.xyz) · [Contribution guide](CONTRIBUTING.md) ·
[Campaign issues](https://github.com/zkp2p/peer-link/issues) · [Rewards](docs/incentives.md)

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
independent model attestation. Live funded inference remains unverified.

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
candidate's measured budget is $5 for one $5 contribution; allocation follows a
separate $1 recovery test and its confirmed return, not another $50 deposit.
The current paused Wise experiment permits one contributor, not five.
The revised payout design uses a non-exportable AWS KMS signing key. Authorized
operator IAM and the host signing broker can sign outside the enclave and recover
funds; this is not exclusive enclave custody. The ledger and deduplication authority
remain RAM-only. Restart requires operator review and does not make wallet reuse
or old-job continuation safe. Live collection remains closed until the new measured
release gates pass. The built
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
independent signature verification passed; a full enclave image is still unverified.

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
[Verification](docs/verification.md) · [Operations](docs/transcript-operations.md) ·
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
