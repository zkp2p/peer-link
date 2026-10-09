# Transcript privacy

**Current status: unreleased. Do not send bank sessions or inference keys.** Use
only the approved independently verified [release](../transcripts/release.json)
and an active source campaign through the
[contribution skill](../skills/contribute-transcript/SKILL.md).

## Where data goes

| Boundary | Data it may receive |
| --- | --- |
| Account owner's browser and local agent | Authorized transaction-history navigation and local bank content. |
| PeerLink Nitro enclave | Application-encrypted submission after attestation verification; fresh authenticated bank responses, transient session and inference key. |
| Approved ordinary inference provider | Validated redacted structural artifact and fixed grading instructions only; no raw bank response, session or payout key. |
| Parent host/API infrastructure | Encrypted submission, public routing/status metadata, approved egress hostname and opaque TLS bytes. |
| Retained/public outputs | Templated endpoints, allowlisted field paths/types, coverage, limitations and opaque receipt identifiers/digests. |

A cloud-backed local agent can separately process browser content. Explain that
boundary and obtain the owner's consent before inspection; repository instructions
do not authorize sharing banking data with an unrelated service.

The pilot performs deterministic redaction **before inference**. Ordinary
provider-visible inference requires explicit consent to the named provider/model
and approved upstream routing even though the content is structural. Peer enclave
protection does not establish the provider's confidentiality or retention policy.
The ordinary NEAR route is implemented for canonical `z-ai/glm-5.3-flash`,
with explicit consent to NEAR and its approved Chutes upstream. It requests no
aliasing, rejects alias/model mismatches and unapproved serving-provider headers,
and makes at most one grading call. Those gateway assertions over TLS are not
independent model attestation. Paid ordinary schema probes and the supervised
Wise pilot exercised this route; confidential inference and the changed durable
release still require separate verification.

NEAR confidential inference is unavailable until its exact attestation and encrypted
request/response adapter have been verified. Failed confidential verification must
not downgrade to ordinary inference.

## Credentials and acquisition

The owner logs in and completes MFA. The encrypted job includes only the authorized
session/API credential needed for approved reads, the recipe and the contributor's
inference key; never passwords, MFA codes or private payout keys. Verify fresh
Nitro attestation, the pinned approved image, encryption key and policy binding
before encryption. Reject debug/unreleased images and changed scope or privacy mode.

Bank/provider TLS and HTTP processing terminate inside the enclave. The host relay
sees destination metadata and ciphertext. Submitted captures are hints; the enclave
must acquire new bank responses and derive account identity from those authenticated
responses. No payment initiation or account changes are permitted.

Keys remain transient and are not read from an environment fallback, returned in
errors, included in model prompts, or logged. After the job, revoke the inference
key and use the bank's logout/session controls. Logout is not a universal bank-token
revocation guarantee. Python reference removal is not guaranteed memory zeroization;
enclave destruction is the final key-erasure boundary.

## Redaction and retention

Retain endpoint templates, safe parameter/header names, field paths and types,
list/detail and authenticated Wise profile/balance/history relationships, read
coverage and limitations. The policy allowlists 59 public schema field names;
unknown or dynamic keys still become wildcards. Remove names, account
numbers, balances, exact amounts, memos, transaction IDs and credentials, including
values in URL segments, queries, nested bodies and dynamic object keys. Unknown
field names become structural wildcards. Model free text is not retained as a
supposedly safe banking transcript.

Account deduplication uses purpose-scoped keyed identifiers derived from live bank
account evidence. Never publish those identifiers or ordinary hashes of guessable
banking values. Public receipts hash already-redacted artifacts only.

The revised payout key is non-exportable in AWS KMS. Authorized operator IAM and
the host broker can request signatures outside the enclave and recover funds;
neither exclusive enclave custody nor PCR-restricted KMS access is claimed.
Attestation binds the KMS key ARN and wallet to the measured policy, not exclusive
control over every possible signature. Runtime payout limits do not constrain an
operator signing independently through IAM.

Bank and inference credentials remain transient inside the enclave after encrypted
submission; the signing broker does not receive them. The completed pilot lost its
RAM-only ledger, deduplication authority and in-process artifacts on restart. KMS custody
recovery does not restore that state or make reusing a funded wallet safe. Operator
review is required before restarting a campaign. This is not durable production
storage or payment reconciliation.

## Durable-state release under development

The v3 release is preparing AES-GCM snapshots containing authoritative job,
deduplication, durable receipt keys and payout state. Attested KMS Recipient
decryption binds approved PCR0 and host-role PCR3; an immutable Lambda/DynamoDB
revision and writer-generation authority rejects stale writes. Bank sessions,
inference keys, raw bank reads and submission envelopes are never persisted.
Snapshots bind exact policy/campaigns/wallet/namespace/authority; absent, mismatched
or stale state must stop admission. Restore starts paused for signed operator
resume and chain reconciliation. These protections require separate live
verification before public collection.

The bank-upload ingress private key is fresh per boot and never persisted. A
separate durable receipt signer is encrypted in the snapshot; it cannot decrypt
old uploads. Later snapshot recovery or state-key policy changes therefore cannot
recover an earlier boot's ingress key. KMS administrators remain trusted for the
secrecy of encrypted metadata and deduplication state. Cloud state availability
and operator custody remain explicit trust boundaries; do not describe them as
exclusive enclave authority.

## Local handling and publication

Avoid exporting whole HARs, browser profiles, cookie jars, statements or agent
transcripts. If temporary local files are necessary, keep them in ignored `.local/`
with restricted permissions and an explicit cleanup plan. Never put secrets in
command arguments, shell history, URLs, screenshots, GitHub, CI or support requests.
Use invented synthetic values for repository fixtures, including expected outputs.
Sanitized copies do not become authenticated original evidence.

Before committing/pushing public maintenance changes:

```sh
npm run privacy -- --staged
npm run privacy -- --range origin/main..HEAD
git diff origin/main...HEAD
```

The privacy scanner flags many credential/capture patterns without printing matched
values. It can miss names, amounts and uncommon identifiers. Review every changed
file version yourself; deleting a file later does not remove a pushed leak.

For exposure, stop sharing, have the owner revoke affected credentials, and report
privately through [SECURITY.md](../SECURITY.md). Never repeat the secret in a comment.
The landing page provides discovery/instructions and accepts no plaintext bank uploads.

The former adapter publication workflow is [archived](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/docs/privacy.md);
its shape-printing tools are reference utilities, not the transcript submission API.
