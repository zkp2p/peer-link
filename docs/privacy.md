# Transcript privacy

A contribution sends a bank session to PeerLink's enclave and leaves behind a
value-free transcript. This page says where each kind of data goes. Follow the
[contribution skill](../skills/contribute-transcript/SKILL.md) and run `preview`
before contributing: it prints, on your own machine, exactly what would be kept.

## Where data goes

| Boundary | Data it may receive |
| --- | --- |
| Account owner's browser and local agent | The bank pages and requests the owner chooses to inspect, and the session used to replay them. |
| PeerLink Nitro enclave | The encrypted submission after the client has verified attestation: recipe, notes, bank session or token, inference key. Fresh bank responses to the recipe's reads. All of it in memory only. |
| The bank | The recipe's requests with the session headers, from the enclave, to the single host the contributor declared inside the campaign's bank domain. |
| The owner's chosen model provider | One request on the owner's key: PeerLink's fixed instructions, the contributor's notes and the value-free transcript. No session, token, raw response, id, name, amount or payout key. |
| Parent host and API gateway | Ciphertext of the submission, public job status, destination hostnames and opaque TLS bytes. |
| Retained by Peer (enclave host disk and a private S3 bucket) | For accepted jobs only: the signed record containing the transcript, the notes, the code-verified field mapping and score, inference metadata, and the payout coordinates. |
| Public | Campaign terms and the on-chain USDC transfer. A contributor holds their own signed receipt. |

A cloud-backed local agent can separately process whatever it reads in the
browser. Explain that boundary and obtain the owner's consent before inspection;
repository instructions do not authorize sharing banking data with an unrelated
service.

## What the enclave sends to a model

The enclave builds the prompt itself. PeerLink's instructions come first, the
contributor's notes and the transcript sit in the middle, and PeerLink's output
contract comes last. **The bank session is never placed in a prompt.** The
enclave uses the session only to make the reads; the model sees structure, not
values. For open campaigns the owner may choose any OpenAI-compatible endpoint
and model, so consent to that provider is the owner's decision and is recorded
with `--consent`. Enclave protection applies to Peer's handling of the session
and raw data; it does not make the chosen provider confidential or govern its
retention. Confidential NEAR inference is not available and a job never
downgrades silently from a mode it reserved.

The model cannot grant a reward. It proposes which transaction field plays each
role, and code verifies every proposal against the live records and computes the
score. Reviewed campaigns such as Mercury keep their pinned provider and model
routes and send only the allowlisted structural artifact described in
[source validation](source-validation.md).

## Credentials and acquisition

The owner logs in and completes MFA. The encrypted job includes only the session
headers or API token needed for the reads, the recipe, the notes and the
contributor's inference key; never passwords, MFA codes or private payout keys.
The client verifies fresh Nitro attestation, the pinned image measurements,
encryption key and policy before encryption, and rejects debug or unreleased
images.

Bank and provider TLS end inside the enclave. The host relay sees destination
hostnames and ciphertext. The enclave sends the bank credential only to the
`https://host` the contributor declared, which must be the campaign's bank
domain or a subdomain, and the inference key only to the reserved endpoint.
Before the authenticated reads, the enclave sends the identity and history
requests without credentials and stops if they return JSON, so a public endpoint
cannot stand in for an account. No payment initiation or account change is part
of a contribution; for POST reads the enclave refuses requests that are
obviously named as state changes, and the contributor remains responsible for
replaying only requests the bank's site issues while viewing history.

Keys are transient inside the enclave: never read from the enclave's
environment, returned in errors, included in prompts, logged or written to
durable state. On the contributor's machine, secrets may come from environment
variables the owner exports, from the stdin payload, or from a terminal prompt;
never from a command argument. After the job, log out of the bank session,
revoke any dedicated token and revoke or cap the inference key. Logging out does
not revoke an API token. Python reference removal is not guaranteed memory
zeroization; enclave destruction is the final key-erasure boundary.

## Redaction and retention

For open campaigns the transcript contains, and the validator admits, only:

- request method, host, path template and query parameter names, with path
  segments and query values that are not plain words replaced by `{id}` or a
  format class;
- the names of the credential headers, never their values;
- for a POST, the body's field names and format classes and a GraphQL operation
  name, never the document text or variable values;
- response field paths with JSON types and closed-vocabulary format classes
  such as `decimal:neg:2`, `datetime:iso8601:utc` or `text:short:alpha`;
- short tokens under keys ending in `status`, `state`, `type`, `kind`,
  `currency`, `scheme`, `direction`, `method`, `rail` or `network`, unless the
  key sits under an object describing a person or address, or the same text
  also appears as an ordinary value;
- the contributor's notes, which are rejected if they contain emails, long digit
  runs, token-like strings, or identifier-like values copied from the responses;
- the selectors for identity and history, a coverage flag, and fixed limitation
  labels.

Object keys that look like identifiers, and maps keyed by identifiers, collapse
to `{key}`. The count of transactions is not kept. **These rules for names and
tokens are heuristic.** A field name or a status-like token that is itself
personal could be retained, which is why `preview` exists and why the owner
should read its output before contributing.

Reviewed campaigns keep the earlier, stricter artifact: only schema field names
allowlisted in the measured policy, types, and templated endpoint relationships.

Accepted records are signed inside the enclave, written to the enclave host's
disk, and mirrored to a private, versioned S3 bucket in Peer's AWS account that
Peer engineers read; see [transcript archive](transcript-archive.md). Rejected
jobs leave no transcript with Peer, although the chosen model provider may
already have received the notes and transcript.

Account deduplication uses purpose-scoped keyed identifiers derived from live
bank account evidence, kept only in encrypted enclave state. For open campaigns
that evidence is the value at the contributor's `identity` selector. Never
publish those identifiers or ordinary hashes of guessable banking values.

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
review was required before restarting that RAM-only campaign. Those historical
results do not establish durable storage; the current release has separate evidence below.

## Approved durable-state release

The v3 release uses AES-GCM snapshots containing authoritative job,
deduplication, durable receipt keys and payout state. Attested KMS Recipient
decryption binds approved PCR0 and host-role PCR3; an immutable Lambda/DynamoDB
revision and writer-generation authority rejects stale writes. Bank sessions,
inference keys, raw bank reads and submission envelopes are never persisted.
Snapshots bind exact policy/campaigns/wallet/namespace/authority; absent, mismatched
or stale state must stop admission. Restore starts paused for signed operator
resume and chain reconciliation. The [live evidence](../transcripts/durable-pilot-evidence.json)
records hardware bootstrap and restart, preserved paid receipts and chain state,
and a fresh client recovering the same payment without resubmission. These checks
cover the capped Wise release, not every bank or arbitrary infrastructure failure.

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
