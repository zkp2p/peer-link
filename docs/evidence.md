# Transcript evidence and receipts

A submitted recipe or local capture is a navigation hint. Only fresh reads made by
the enclave's authenticated bank transport establish source acquisition. Synthetic
fixtures, browser self-reports, model inference and bank listings do not prove live
acceptance. The [current release](../transcripts/release.json) is unreleased.

## Source and account identity

The transport enforces approved HTTPS origins/paths and read-only methods, no
redirects, certificate/hostname verification, response sizes, JSON parsing, read
counts and deadlines. Private DNS destinations are rejected by the host relay;
TLS authentication and HTTP policy remain inside the enclave.

Account identity must come from fresh authenticated bank evidence, never an uploaded
account ID. In the Wise pilot, the authenticated profiles response must contain
the selected profile; multiple profiles require explicit selection. Balance reads
establish statement balance membership. All retained live reads bind to the same
account and job. Other banks remain unavailable pending their own reviewed identity
and acquisition adapters.

## Redacted evidence

The structural artifact contains campaign/bank identifiers, verified source origins,
endpoint templates, safe parameter/header names, field paths/types, authenticated
Wise profile-to-balance-to-history relationships,
coverage and limitations. Dynamic object keys and URL/query values are redacted.
No names, credentials, account numbers, balances, exact amounts, memos or transaction
IDs remain. Code validates the artifact before it reaches the grader.

The grader receives that redacted artifact and fixed instructions. Its only accepted
result is the exact versioned rubric, integer score and boolean usefulness. Extra
fields, arbitrary prose, unsupported models, incomplete results or unavailable
usage information fail closed. The result cannot choose a wallet, amount, source
or trust rule. Provider-visible inference requires explicit consent; confidential
NEAR is not an available verified capability. Ordinary NEAR is implemented for
canonical `z-ai/glm-5.3-flash`, with aliases rejected, one call, and consent naming
NEAR/Chutes. No funded live inference has demonstrated this route yet; returned
routing headers are gateway assertions, not independent model proof.

## Receipts and interpretation

A receipt binds the job/campaign policy, redacted artifact digest, fixed grading
request/result digests, provider/model, privacy mode and bounded inference usage.
Public outputs contain opaque identifiers, redacted metadata and confirmed payout
coordinates where applicable, never raw model completions or private account
fingerprints. Inspect the exact released API contract for available fields.

Code checks authenticated source acquisition, job binding/expiry, useful history,
redaction, duplicates and reserved budget independently of the model score. It
reserves one fixed payout and reconciles uncertain chain submission using the same
transaction identity. A model score alone is not acceptance or payment evidence.
The pilot epoch is RAM-only and non-restorable: no durable storage, deduplication
or payout-recovery claim may be carried across a process restart.

Keep separate evidence for:

| Evidence | What it establishes |
| --- | --- |
| Synthetic tests | Tested behavior on invented inputs, including rejection and leak checks. |
| Real Nitro verification | Fresh hardware quote bound to the reviewed image, key and policy. |
| Actual provider response/usage | The chosen inference route ran and billed the contributor. |
| Owner-authorized fresh bank reads | The reviewed source/account adapter acquired the demonstrated scope. |
| Confirmed on-chain receipt | The specific fixed USDC transfer reached its specified recipient. |

No category substitutes for another. Report scope, exact source/image revision,
date and remaining limitations accurately. A paid transcript does not prove final
bank settlement, recipient credit, support for every payment type, or readiness in
Peer production. Peer engineers separately review metadata and transformers.

## Legacy reports

Existing files under `banks/*/*/reports/` remain historical revision-specific
self-reports; they are not current transcript submissions or automatic rewards.
Their [archived format and merge rules](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/docs/evidence.md) remain available
for maintenance of those reference assets. Reporter handles/counts are not verified
unique humans or live account identities. Do not rewrite historical observations
as authenticated transcript evidence.
