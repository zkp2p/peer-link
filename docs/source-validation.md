# First-contributor source validation

The Mercury candidate is an experiment to collect the first authenticated
transcript for a reviewed API source. It is not a completed Peer integration.
There has not yet been a positive live Mercury acquisition in this campaign.
The experimental campaign requires its independently approved measured release,
verified hardware and a successful funded reservation before keys or inference.
A static page cannot guarantee availability.

The experimental campaign is `mercury-api-source-v1`, linked to
[Mercury #1](https://github.com/zkp2p/peer-link/issues/1): one accepted contribution
from one authorized organization, for **10 USDC on Base**. Wise is already an
existing integration and is excluded from incentives.

This page covers the reviewed Mercury campaign only. The other banks use
`open_recipe` campaigns, where the contributor's recipe supplies the requests
and selectors and any model may be used; see the
[recipe guide](transcript-recipes.md).

```mermaid
sequenceDiagram
    participant A as Contributor's agent
    participant T as PeerLink enclave
    participant B as Mercury API
    participant M as Contributor's model provider
    participant S as Encrypted state authority
    participant P as KMS payout wallet
    A->>T: Verify release and attestation; reserve funded slot
    A->>T: Encrypt read-only token, recipe and own inference key
    T->>B: Check authentication, organization, account and history
    B-->>T: Fresh authenticated responses
    T->>T: Check organization duplicate and redact values
    T->>M: Structural artifact and fixed grading prompt
    M-->>T: Usefulness score
    T->>S: Commit accepted evidence and fixed payment obligation
    T->>P: Sign reserved 10 USDC transfer
    T->>S: Persist transaction before broadcast
    T-->>A: Confirmed payment and signed receipt
```

## Reviewed source, bounded contributor hints

The measured policy contains the source descriptor. Contributors cannot supply
executable tools, endpoint URLs, selectors, extra headers or a different host.
Their version-2 recipe supplies only the `account.id` UUID observed in an
owner-authorized Mercury `/api/v1/accounts` response and a nonempty UTC date
interval of at most 30 days, ending no later than the current UTC day. An account
number, name, organization ID or guessed UUID is not a substitute. Account
identifiers stay private. Prefer an interval ending on the previous UTC day to
avoid just-created transactions and clock skew.

The enclave makes at most four bank requests:

1. An anonymous GET of `/api/v1/organization` must return 401. Its body is discarded.
2. An authenticated GET of that same endpoint supplies `organization.id`.
3. An authenticated GET of `/api/v1/accounts?limit=100&order=asc` must include the
   selected active Mercury account.
4. An authenticated GET of `/api/v1/account/{id}/transactions` requests one page
   of at most 100 records for the selected date range. Every returned account ID
   must match the selected account. Useful nonempty history is required.

All calls use `https://api.mercury.com`, verified TLS ending inside the enclave,
bounded responses and time limits. Redirects, pagination and payment endpoints
are unavailable. The documented date filters do not specify which transaction
timestamp they use, so the implementation does not claim a `createdAt` versus
`postedAt` range guarantee. It requires parseable timezone-aware `createdAt`
values no later than the start of enclave acquisition; a transaction created
during the reads can therefore fail this check.

The source contract comes from Mercury's official
[organization](https://docs.mercury.com/reference/getorganization),
[accounts](https://docs.mercury.com/reference/getaccounts) and
[transactions](https://docs.mercury.com/reference/listaccounttransactions)
documentation. A published schema is not positive live-acquisition evidence.

## Consent, cost and identity limits

The owner must authorize sharing the organization's data, create a dedicated
[read-only API token](https://docs.mercury.com/docs/getting-started), and revoke
it after the attempt. Logging out does not necessarily revoke an API token.
The enclave executes reads only; it cannot prove that a supplied token lacks
write permissions.

If the account UUID is not already known, first obtain admission with
`Client.reserve(..., on_reserved=...)` and save its public recovery handle before
collecting keys. The CLI has no standalone reserve command; see the
[SDK reservation example](../skills/contribute-transcript/SKILL.md#mercury).
Only then use the owner's trusted local memory-only tool to GET the same approved
accounts endpoint and privately choose an observed active Mercury `account.id`.
That local discovery is separate from the enclave's four reads. Do not send token
values or raw output to chat, logs or a cloud service without separate informed
consent. Continue the same unexpired reservation with `submit-reserved` and its
original saved terms, not a second `contribute` call. Never collect keys unless
release verification and funded reservation both pass.

Fresh authenticated responses establish possession of API access to the observed
organization. They do not prove legal ownership or a unique human. A private
keyed organization identifier prevents a second award for the same organization
within this campaign; different accounts or API keys do not create another award.
An organization with more than 100 accounts may have to select an account from
the first page. An account with no useful history cannot qualify.

Authentication, membership, minimum structure and duplicate checks run before
grading. A failure before inference does not charge inference or pay a reward.
Failed attempts do not commit an accepted organization identity. A compound
state outage can delay slot release; see the bounded recovery limits in
[operations](transcript-operations.md). Once grading starts, the contributor's
own approved provider may charge even if the contribution is rejected or fails.
There is no Peer inference-key fallback or automatic paid retry.

Only allowlisted schema names, types and templated endpoint relationships reach
the model and retained artifact. Private values, raw records, tokens and error
bodies do not. Model scoring cannot change the recipient, fixed award, budget,
source checks or payment authorization. Confidential NEAR inference remains
unavailable; ordinary provider-visible inference requires explicit consent.

The campaign first ran under its own `mercury-public-v1` state, independent of
the permanently retired Wise epoch. In the open-recipe release it is carried
unchanged in the same measured policy as the open campaigns: state namespace
`open-public-v1`, one shared epoch budget of at most 50 USDC with no automatic
refill, and Mercury still capped at one organization and 10 USDC. The same
operator-recoverable KMS payout wallet is reused only after zero-balance/nonce
checks, a new measured policy and hardware approval. This is not escrow or an
enclave-exclusive signing key. A successful reservation determines admission.

The separately scoped [Mercury release evidence](../transcripts/mercury-source-evidence.json)
records measured-source, hardware and funding checks; positive live bank acquisition
remains pending until the first contributor provides verified evidence.
