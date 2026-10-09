# Transcript contribution rewards

**The service is unreleased: no new transcript jobs or rewards are available yet.**
The [release manifest](../transcripts/release.json), independently verified release
and active bank campaign control availability. A bank issue, logo, host deployment
or synthetic test does not prove acceptance is open.

## Campaign terms

One campaign issue per bank publishes scope, approved source access, fixed reward,
available capacity, provider/model and privacy choices, limits and the
[contribution skill](../skills/contribute-transcript/SKILL.md). Existing bank issue
URLs are retained where possible. There is no claim-comment, assignment, provider
implementation or code PR requirement.

- Fixed **$5 or $10 USDC for each accepted contribution**. Initial US campaigns
  use $10; other rates are explicit campaign policy, not inferred from personal data.
- Collect **1–5 distinct contributors per bank**, ordinarily targeting five but
  stopping earlier when the evidence is sufficient.
- At most one paid contribution per contributor/account per bank campaign.
  Different wallets or GitHub accounts alone do not establish different people;
  account deduplication is not proof of humanity.
- Contributions require an active verified source campaign, available slots and
  reserved funds. Campaigns can pause, complete or reject admission before inference.
  Do not infer that all listed banks are funded.

The reserved job binds the campaign terms, reward, recipient, model/provider,
privacy consent, limits and expiry. Later policy edits do not retroactively change
those reserved terms. USDC has 6 decimals; code stores rewards as integer minor units.

## Costs and acceptance

**The contributor pays inference even when the job fails or is rejected.** Review
provider/model, limits, privacy mode, possible reward and provider spending controls
before releasing the key. The ordinary NEAR route uses prepaid contributor
credits and one canonical-model call, with consent naming NEAR and Chutes. Provider quota enforcement may lag; published token/call
limits are not a guaranteed exact dollar ceiling. A reward may not cover inference cost.
Peer pays infrastructure, payout gas and accepted rewards. There is no Peer
inference key or fallback billing route.

Acceptance requires fresh authorized bank reads over verified TLS, authenticated
account identity, useful history/schema evidence, approved provider/model and consent,
safe redaction, no duplicate award and available reserved budget. The model grades
only redacted structure. Code owns eligibility, amount, recipient and signing;
the model cannot override mandatory checks. Unknown or insufficient evidence is rejected.

An enabled service automatically pays the fixed reward after acceptance and artifact
receipt. Failed, rejected, expired or cancelled jobs receive no reward. A pending
chain result must be reconciled against the same signed transaction; retrying does
not authorize a new award. Acceptance does not enable a bank in Peer or establish
recipient credit, final settlement or production approval.

## Pilot budget and availability

The architecture reward ceiling is **$50 USDC**, with separate bounded gas
and no automatic refill. The revised candidate has a measured **$5 USDC budget**
and one available contributor slot in the paused Wise experiment, allocated only
after a separate $1 recovery test confirms
the return. These are budget and verification plans, not a statement that funds are
already deposited or that every bank has a funded slot. Admission stops when
reserved capacity or funds run out.

The revised payout authority is a non-exportable AWS KMS key, recoverable through
authorized operator IAM; the host broker can also request signatures. Runtime
payout rules apply to the measured service, not to independent operator signing.
The ledger and deduplication state remain RAM-only. A restart requires operator
review and does not safely restore old jobs or justify reusing the funded wallet.
Operators must verify the new measured release, funding, bank access,
inference and payout evidence before enabling any campaign. A signed retirement
action irreversibly closes admission, settles/archives existing obligations and
refunds remaining USDC to the fixed deployer address. This has synthetic coverage,
not a live refund demonstration; the runtime performs no ETH sweep or ledger
restore. Operator KMS recovery is a separate trust boundary. The earlier
enclave-only pilot's funded $50 remains unrecovered at this checkpoint; new custody
does not restore its old signing key.

## Retired provider awards

The $50-per-provider/Merit authoring program is retired for new work. Its
[original terms](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/docs/incentives.md), including historical funding records,
remain an immutable archive. The old assignment/deadline/PR procedure is not the
new transcript enrollment flow.

Previously earned or accepted awards retain their original written terms. A legacy
PR closing with a program-change notice does not cancel an accepted obligation or
prove an earlier disputed claim is invalid. Preserve prior acceptance, assignment,
commit and discussion records; review disputes under their original scope rather
than applying the new $5/$10 rules retroactively. Do not promise an automatic
legacy award merely because work or a PR exists.
