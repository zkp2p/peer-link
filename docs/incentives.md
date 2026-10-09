# Transcript contribution rewards

**Wise has an approved release: successful reservation is required before secret input.**
The [release manifest](../transcripts/release.json), independently verified release
and a successful live reservation control admission. Approval and static issue
text cannot guarantee remaining capacity. A bank issue, logo, host deployment
or synthetic test does not prove acceptance is open.

## Campaign terms

One campaign issue per bank publishes scope, approved source access, fixed reward,
available capacity, provider/model and privacy choices, limits and the
[contribution skill](../skills/contribute-transcript/SKILL.md). Existing bank issue
URLs are retained where possible. There is no claim-comment, assignment, provider
implementation or code PR requirement.

GitHub bank issues remain public campaign and discovery pages. New transcript
rewards are paid through PeerLink, not Merit; contributors do not need to claim
a Merit bounty. The [campaign index](https://github.com/zkp2p/peer-link/issues/64)
lists planned rates and availability. The single [Merit project profile](https://terminal.merit.systems/zkp2p/peer-link)
links to PeerLink for discovery; bank campaigns are not separate Merit bounties.
Keeping either page visible does not open a paid slot.

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
and no automatic refill. The completed supervised Wise experiment used a measured
**$5 USDC budget** and one contributor slot after a confirmed $1 recovery test.
That $5 reward was paid; **that completed test allocation has no remaining capacity**.
The separate durable Wise release has its own initial allocation and verification. Future campaigns must publish available
capacity and reserve their reward funds before accepting contributions. A budget
ceiling or a planned per-transcript rate is not a funded award.

The revised payout authority is a non-exportable AWS KMS key, recoverable through
authorized operator IAM; the host broker can also request signatures. Runtime
payout rules apply to the measured service, not to independent operator signing.
The completed pilot kept ledger and deduplication state RAM-only. A restart requires operator
review and does not safely restore old jobs or justify reusing the funded wallet.
Operators must verify the new measured release, funding, bank access,
inference and payout evidence before enabling any campaign. A signed retirement
action irreversibly closes admission, settles/archives existing obligations and
refunds remaining USDC to the fixed deployer address. This has synthetic coverage,
not a live refund demonstration; the runtime performs no ETH sweep or ledger
restore. Operator KMS recovery is a separate trust boundary. The earlier
enclave-only pilot's funded $50 remains unrecovered at this checkpoint; new custody
does not restore its old signing key.

## Approved Wise campaign

[Wise #239](https://github.com/zkp2p/peer-link/issues/239) has an initial allocation
of two $5 Base USDC awards ($10 total). An operator-paid validation contribution counts toward that limit. Other
banks remain planned. No static page promises a remaining slot: obtain a successful
reservation before sharing keys or paying for inference. The authenticated Wise
job paid automatically, and the same signed receipt was recovered after restart
without another submission or model call. See the separately scoped
[durable evidence](../transcripts/durable-pilot-evidence.json); the older RAM-only
pilot does not approve this release.

## Retired provider awards

The [legacy Bank of America commitment record #74](https://github.com/zkp2p/peer-link/issues/74)
was administratively closed and removed from award discovery. Its preserved
**$50 original commitment**, Primuez assignment and **October 16, 2026** terms
remain historical obligations for review. Closure neither accepts nor rejects the
work or cancels a valid prior payment commitment; the amount is not reduced to
the transcript rate. There are no active individual Merit award listings.
The new Bank of America campaign is [#235](https://github.com/zkp2p/peer-link/issues/235),
at **$10 per accepted transcript**, with 1–5 distinct contributors when enabled.
No new transcript campaigns are enrolled as Merit bounties.

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
