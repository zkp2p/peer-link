# Transcript contribution rewards

Each campaign pays a fixed **$5 or $10 USDC on Base** for one accepted
transcript. All campaigns in a release share one funded budget of at most
**$50**, with no automatic refill. A successful reservation, made by the client
after it verifies the enclave against the pinned
[release manifest](../transcripts/release.json), is what admits a job. A bank
issue, a logo or this page does not guarantee remaining capacity; run
`campaigns --live` for the current unsigned hint.

## Campaign terms

| Campaign kind | Banks | Reward | Slots |
| --- | --- | --- | --- |
| `open_recipe` | The twenty banks with a `<bank>-open-v1` campaign in [`transcripts/policy.json`](../transcripts/policy.json) | $10 for Chase, Bank of America and Wells Fargo; $5 for the others | 2 per bank |
| `reviewed_descriptor` | Mercury, [`mercury-api-source-v1`](https://github.com/zkp2p/peer-link/issues/1) | $10 | 1 organization |

Mercury remains first-contributor [source validation](source-validation.md):
its first positive live API acquisition is pending and would come from the
contributor. Wise is an existing integration and is excluded from rewards.

One campaign issue per bank publishes its scope and reward, and the
[campaign index](https://github.com/zkp2p/peer-link/issues/64) lists them.
There is no claim comment, assignment, provider implementation or code PR
requirement. Rewards are paid by the PeerLink service, not through Merit; the
single [Merit project profile](https://terminal.merit.systems/zkp2p/peer-link)
is for discovery only.

- At most one paid contribution per bank account per campaign. Different
  wallets or GitHub accounts alone do not establish different people, and
  account deduplication is not proof of humanity. For open campaigns the account
  is identified by the value at the contributor's `identity` selector.
- A payout address can hold one active or paid job per campaign.
- Campaigns can fill, pause or be retired before a contribution is admitted.

The reserved job binds the campaign terms, reward, recipient, provider, model,
inference endpoint, privacy consent, limits and expiry. Later policy edits do not
change reserved terms. USDC has 6 decimals; code stores rewards as integer minor
units.

## Costs and acceptance

**The contributor pays inference even when the job fails or is rejected.** Each
job makes one model call on the contributor's key. For open campaigns the
contributor chooses any OpenAI-compatible endpoint and model; reviewed campaigns
pin theirs. Token and deadline limits are bound into the reservation but are not
an exact dollar ceiling, and a reward may not cover the inference cost. Peer
pays infrastructure, payout gas and accepted rewards. There is no Peer inference
key or fallback billing route.

An open-recipe contribution is accepted when all of these hold:

- the reads ran from the enclave over verified TLS on the campaign's bank
  domain, and the identity and history requests were not served without a
  session;
- the history response held at least three records;
- the transcript passed redaction validation;
- the account was not already paid in the campaign and budget was reserved;
- the field mapping scored at least 85 of 100. The model proposes which history
  field is the payment id (25), amount (25), timestamp (20), counterparty (15),
  status (10) and currency (5); code verifies each proposal on the live records
  and adds the weight only when it holds. The first four are required.

The model's reply cannot set the score, the recipient or the amount, which is
why any inference endpoint may be used. Reviewed campaigns instead use a pinned
model's usefulness grade of the allowlisted artifact together with the source
checks in [source validation](source-validation.md).

The service pays the fixed reward immediately after acceptance and after the
enclave host acknowledges the signed record. Failed, rejected, expired or
cancelled jobs receive no reward. A pending chain result is reconciled against
the same signed transaction; retrying does not authorize a new award. Acceptance
does not enable a bank in Peer or establish recipient credit, final settlement
or production approval.

## Pilot budget and availability

The architecture reward ceiling is **$50 USDC** per funded epoch, with separate
bounded gas and no automatic refill. The open-recipe release funds that ceiling
once and shares it across every campaign, first come first served; refilling
means retiring the epoch and publishing a new measured release. The completed
supervised Wise experiment used a measured
**$5 USDC budget** and one contributor slot after a confirmed $1 recovery test.
That $5 reward was paid; **that completed test allocation has no remaining capacity**.
The separate durable Wise tests provide internal validation, not public enrollment. Future campaigns must publish available
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

## Internal Wise validation

Wise is already an integration/reference and is excluded from new transcript
incentivization. The completed operator-owned tests used bounded reward transfers
to validate acquisition, grading, payout and restart recovery; they are not public
campaigns or a promise of funded slots. See the separately scoped
[durable evidence](../transcripts/durable-pilot-evidence.json). The open-recipe
flow was exercised the same way, on separate validation releases whose only
campaigns were operator-owned Wise slots; see [evidence](evidence.md).

## Retired provider awards

The [legacy Bank of America commitment record #74](https://github.com/zkp2p/peer-link/issues/74)
is archived after Primuez [voluntarily withdrew on October 9, 2026](https://github.com/zkp2p/peer-link/issues/74#issuecomment-6074393805),
citing unavailable authorized account access for live verification. This attempt
was not accepted as a live-verified integration and is closed without payout;
there is no active assignment or deadline. The original $50 terms, submitted
code and discussion remain preserved. This records a withdrawal, not a reduction
of an accepted award to the transcript rate. There are no active individual
Merit award listings.
The new Bank of America campaign is [#235](https://github.com/zkp2p/peer-link/issues/235),
at **$10 per accepted transcript**. It is the open-recipe campaign
`bank-of-america-open-v1` and requires authorized Bank of America account access.
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
