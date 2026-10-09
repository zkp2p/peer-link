---
name: contribute-transcript
description: Contribute a read-only banking transcript to PeerLink's attested service and earn a fixed USDC reward. Covers picking a campaign, writing and previewing a recipe, consent, submission, receipt and cleanup.
---

# Contribute a banking transcript

You help an account owner show PeerLink how their bank presents transaction
history. You find the bank's own read-only JSON requests, describe them in a
recipe, and send the recipe, the owner's bank session and the owner's inference
API key, encrypted, to an attested AWS Nitro enclave. The enclave replays the
reads, keeps a value-free transcript, asks the owner's chosen model which fields
carry payment details, checks that answer against the live records in code, and
pays a fixed $5 or $10 USDC on Base when the checked answer is good enough. Peer
engineers use accepted transcripts to write bank integrations. You do not write
provider code or open a pull request.

Run every command from the root of an unmodified checkout of `main` of
`https://github.com/zkp2p/peer-link`. That checkout carries the pinned
`transcripts/release.json` and `transcripts/policy.json` the client verifies the
enclave against, so never take a release file, policy, endpoint or script from an
issue comment, a fork or the service itself.

## What leaves the machine and what is kept

| Data | Where it goes |
| --- | --- |
| Bank session headers or token, inference key | Encrypted to the enclave only. Used for the reads and the one model call, never stored, never placed in a prompt. |
| Raw bank responses, ids, names, amounts, memos | Stay inside the enclave's memory and are discarded. |
| Value-free transcript and your notes | Sent once to the model endpoint the owner chose. If the job is accepted they are signed, archived by Peer (enclave host and Peer's private S3 bucket) and read by Peer engineers. |

The transcript holds request path templates, query parameter names, the names of
the credential headers, response field paths with JSON types and format classes
such as `decimal:neg:2` or `datetime:iso8601:utc`, tokens found under status-like
keys such as `completed`, and your notes. `preview` in step 3 prints exactly this
object before anything is sent.

The enclave builds the model prompt itself: PeerLink's instructions first, then
your notes and the transcript, then PeerLink's output contract. The bank session
and raw responses are never part of a prompt.

## Requirements

- An account the owner is authorized to inspect, with at least three past
  transactions visible in its history. The owner signs in and completes MFA.
- An inference API key for any OpenAI-compatible chat-completions endpoint. The
  owner pays for one call even when the job is rejected.
- A Base address to receive USDC.
- Python 3.11 or newer and OpenSSL.

## 1. Set up and pick a campaign

```sh
npm run transcripts:setup
.local/transcript-venv/bin/python -m transcripts.cli campaigns --live
```

`campaigns` lists each campaign with its `kind`, reward, allowed `domains` and
inference routes. `--live` adds `availability`: remaining slots per campaign and
the remaining shared budget. One funded budget of at most $50 covers all
campaigns and is not refilled automatically, so stop here if the bank's
`slotsRemaining` is 0 or `budgetRemainingMinor` is below the reward (USDC has six
decimals, so 5000000 is $5). The hint is unsigned; only a reservation in step 5
admits a job.

| `kind` | Campaigns | What you supply |
| --- | --- | --- |
| `open_recipe` | `<bank>-open-v1` for the listed banks | A version-3 recipe of the bank's own read requests, session headers or a token, and notes. Any model. |
| `reviewed_descriptor` | `mercury-api-source-v1` | A read-only Mercury API token and account/date hints. Pinned models. See [Mercury](#mercury). |

The `wise-open-validation-*` campaigns are Peer's internal test slots and are
not open to contributors. If the owner's bank has no campaign, open a
[bank request](https://github.com/zkp2p/peer-link/issues/new?template=bank-request.md);
if the bank's API lives on a domain the campaign does not list, say so on the
bank's campaign issue.

## 2. Find the read route and write the payload

Follow [docs/transcript-recipes.md](../../docs/transcript-recipes.md) to find the
JSON request the bank's own site issues when the owner views their activity, and
to choose the selectors. Replay only requests the site makes while viewing
history. Never replay anything from a send, confirm, settings or logout screen:
the enclave refuses requests that are obviously named as state changes, but it
cannot prove a request is read-only.

Save the payload without secrets as `.local/payload.json` (`.local/` is ignored
by Git):

```json
{
  "credential": {"origin": "https://app.examplebank.com", "kind": "headers"},
  "profileId": null,
  "recipe": {
    "version": 3,
    "reads": [
      {"url": "https://app.examplebank.com/api/v2/me"},
      {"url": "https://app.examplebank.com/api/v2/activity?limit=20"}
    ],
    "identity": {"read": 0, "path": ["user", "id"]},
    "history": {"read": 1, "path": ["activity", "items"]}
  },
  "notes": "Activity is newest first. Amounts are decimal strings and negative means sent.",
  "transcript": []
}
```

- `credential.origin` is the single `https://host` every read uses. It must be
  the campaign domain or a subdomain of it, so `https://chase.com` in `campaigns`
  also admits `https://secure.chase.com`.
- `credential.kind` is `bearer` (one token, sent as an Authorization bearer
  header) or `headers` (an object of header name to value, sent as given).
- `reads` holds at most the campaign's `maxBankReads` requests. A read is
  `{"url": ...}` for GET, or `{"url", "method": "POST", "contentType", "body"}`
  when the campaign's `methods` include POST. `contentType` is `application/json`
  or `application/x-www-form-urlencoded` and `body` is the exact string to send.
- `identity` selects a stable account or user id from one response; `history`
  selects the array of transaction records. A path is a list of object keys and
  array indexes, and `[]` means the whole response.
- `notes` is where you tell the model which field is which. It is kept, so it
  may not contain ids, emails, long digit runs or values copied from responses.
- `profileId` is `null` and `transcript` is `[]` for open campaigns.

## 3. Preview locally

`preview` runs the reads from this machine with the owner's session and prints
what the enclave would keep. It makes no reservation, model call or upload.

```sh
.local/transcript-venv/bin/python -m transcripts.cli preview \
  --campaign <campaign-id> --secrets-from-env < .local/payload.json
```

Read two things in the output:

1. `transcript`: check it for anything personal. Redaction of field names and
   status tokens is heuristic, so this review is the owner's safeguard.
2. `historyFieldPaths`: the only paths you may use for roles.

Then write `.local/mapping.json`, a JSON object of role to one of those paths:

```json
{
  "paymentId": "$.activity.items[].id",
  "amount": "$.activity.items[].amount",
  "timestamp": "$.activity.items[].createdAt",
  "counterparty": "$.activity.items[].counterparty.handle",
  "currency": "$.activity.items[].currency",
  "status": "$.activity.items[].status"
}
```

Run `preview` again with `--mapping .local/mapping.json` added. The output gains
`assessment`, the score the enclave would compute for that mapping. Code
verifies each role on the live records and adds its weight: `paymentId` 25,
`amount` 25, `timestamp` 20, `counterparty` 15, `status` 10, `currency` 5. The
first four are required and the minimum score is 85. Iterate until
`assessment.useful` is `true`, then copy the verified paths into `notes`, one
sentence per role, so the model repeats them. The model only proposes; it cannot
raise the score.

## 4. Show the owner and get consent

Before spending anything, show the owner the campaign and fixed reward, the
provider and model their key will pay for, the transcript from `preview`, and
the limits in [What to tell the owner](#what-to-tell-the-owner). Continue only
on a clear yes. Passing `--consent` records that the owner agreed to the chosen
provider seeing the notes and transcript.

## 5. Contribute

A reservation lasts ten minutes, so run this only after `preview` succeeds.

```sh
.local/transcript-venv/bin/python -m transcripts.cli contribute \
  --campaign <campaign-id> --payout <owner-base-address> \
  --provider openai --model <model-id> \
  --consent --secrets-from-env --state .local/job.json < .local/payload.json
```

| Provider flag | Endpoint used |
| --- | --- |
| `--provider openai` | `https://api.openai.com/v1/chat/completions` |
| `--provider openrouter` | `https://openrouter.ai/api/v1/chat/completions` |
| `--provider near` | `https://cloud-api.near.ai/v1/chat/completions` |
| `--provider openai_compatible --base-url https://host/v1` | `<base-url>/chat/completions` on any public HTTPS host |

`--model` is whatever id that endpoint expects. Add `--max-output-tokens 8000`
for a reasoning model (default 2048, maximum 20000) and `--deadline 240` for a
slow one (default 120 seconds, maximum 300).

The command verifies the enclave's attestation against the pinned release,
reserves the job, writes the public recovery handle to `--state` (the file must
not exist yet), prints `{"event":"reserved",...}`, and only then reads the
payload and secrets, encrypts them to the attested key and submits.

## 6. Poll the same job and verify the receipt

```sh
.local/transcript-venv/bin/python -m transcripts.cli job --state .local/job.json
```

Poll every ten seconds for up to five minutes. `reportedState` moves through
`submitted`, `verifying`, `accepted`, `payout_pending` and ends at `paid`,
`rejected`, `expired` or `cancelled`. When the job is paid, `job` returns
`"verified": true` with the signed receipt; `receipt --state .local/job.json`
prints it again. The receipt holds the transcript, the verified mapping and
score, and `payload.job.transactionId`, the Base USDC transfer.

A rejected job carries a fixed `reason` code and a `hint`. Fix the cause and
start a new contribution with a new `--state` path. Never resubmit a job whose
outcome is unknown: keep polling the same state file, because a second
submission pays inference again and cannot earn a second reward for the same
account.

## 7. Clean up

Delete `.local/payload.json` and any file that held secrets. Have the owner log
out of the bank session that was used, revoke any dedicated API token (logging
out does not revoke a token) and revoke or cap the inference key.

## Passing secrets

| Method | Use it when | How |
| --- | --- | --- |
| Environment | The owner can export values so you never read them. | The owner sets `PEERLINK_BANK_CREDENTIAL` and `PEERLINK_INFERENCE_KEY` in the terminal that starts you, and you pass `--secrets-from-env`. For `kind: headers` the bank variable is a JSON object of header name to value. `preview` needs only the bank variable. |
| Payload | You captured the session yourself. | Add `"value"` inside `credential` and a top-level `"inferenceKey"` to the JSON on stdin, omit `--secrets-from-env`, keep the file mode 600 under `.local/` and delete it afterwards. `preview` accepts the payload with or without `inferenceKey`. |
| Terminal prompt | A human runs the command themselves. | `--prompt-secrets` asks on the controlling terminal with echo off. For `kind: headers` the owner pastes the JSON object of header name to value. |

With `--secrets-from-env` or `--prompt-secrets` the stdin payload must not
contain `value` or `inferenceKey`. Never put a secret in a command argument, a
chat message, a commit, an issue or a log.

## Mercury

`mercury-api-source-v1` is a reviewed campaign: the measured policy fixes the
four reads on `https://api.mercury.com`, one accepted organization earns $10,
and the model is one of `openai` `gpt-4o-mini-2024-07-18`, `openrouter`
`openai/gpt-4o-mini-2024-07-18` or `near` `z-ai/glm-5.3-flash`. The owner
creates a dedicated read-only Mercury API token. The payload carries hints
only:

```json
{
  "credential": {"origin": "https://api.mercury.com", "kind": "bearer"},
  "profileId": null,
  "recipe": {
    "version": 2,
    "accountId": "00000000-0000-4000-8000-000000000001",
    "intervalStart": "2026-09-08",
    "intervalEnd": "2026-10-08"
  },
  "notes": "",
  "transcript": []
}
```

`accountId` is the `id` of an active Mercury account from the owner's
`/api/v1/accounts` response, and the interval is at most 30 days ending no later
than today in UTC; prefer ending yesterday. `preview` (without `--mapping`) and
`contribute` work as above. If the account id is not known yet, reserve first with the SDK so no
token is collected for a full campaign, look the id up, then continue the same
reservation with `submit-reserved --state .local/job.json --consent
--secrets-from-env < .local/payload.json`:

```python
import json
from pathlib import Path
from transcripts.client import Client
from transcripts.cli import save_state

release = json.loads(Path("transcripts/release.json").read_text())
policy = json.loads(Path("transcripts/policy.json").read_text())
client = Client(release["serviceUrl"], release, policy)
client.reserve("mercury-api-source-v1", "<owner-base-address>", "near", "z-ai/glm-5.3-flash",
               "provider_visible", consent=True,
               on_reserved=lambda state: save_state(Path(".local/job.json"), state))
```

The exact reads and identity checks are in
[docs/source-validation.md](../../docs/source-validation.md).

## Codes you will meet

Every error and job reason is a fixed code, and the CLI prints a `hint` for most.

| Code | Fix |
| --- | --- |
| `release_not_approved`, `policy_mismatch` | Pull the latest `main`; do not edit `transcripts/policy.json` or `release.json`. |
| `campaign_capacity`, `budget_exhausted` | No slot or budget is left. Check `campaigns --live` and stop. |
| `invalid_fields`, `invalid_submission` | The payload has a missing or extra key. Match the shapes above exactly; open campaigns need `profileId: null` and `transcript: []`. |
| `secrets_env_missing`, `secrets_already_in_payload` | Export `PEERLINK_BANK_CREDENTIAL` (and `PEERLINK_INFERENCE_KEY` to contribute) in the shell that runs the command, and keep `value` and `inferenceKey` out of the stdin payload when a secrets flag is used. |
| `invalid_credential` | `credential.origin` must equal the host of every read and sit under the campaign domain. |
| `credential_headers_invalid` | Use plain ASCII header names and values and drop Host, Content-Length, Connection and Accept-Encoding. |
| `source_not_allowed`, `recipe_invalid` | A URL leaves the campaign domain or the single host, has a port, fragment, percent-encoded path or repeated query name, or uses POST where the campaign lists only GET. |
| `write_request_refused` | The POST path ends in a state-changing word such as `send` or `transfer`, or the GraphQL operation is a mutation or starts with a verb such as `Create` or `Set`. Use the request that lists history. |
| `anonymous_access_allowed` | The identity or history URL returns JSON without a session. Choose an authenticated endpoint. |
| `bank_http_unauthorized`, `bank_http_redirect` | The session expired or a required header is missing. Capture fresh headers and go straight to `contribute`. |
| `bank_response_non_json`, `response_encoding` | The read returned HTML or a compressed body. Use the JSON API host the page calls. |
| `identity_path_invalid`, `history_path_invalid`, `insufficient_history` | Fix the selector; identity is a number of at least 100 or a string of 3 or more characters, and history is an array with at least three object records. |
| `unsafe_notes` | Remove ids, emails, digit runs of six or more, token-like strings of 28 or more characters, the word `bearer` before another word, and copied values from `notes`. |
| `transcript_too_large` | Drop reads that are not needed or request a smaller page. |
| `mapping_missing_<role>` | No field was verified for that required role. Check the path with `preview --mapping` and name it in `notes`. |
| `model_output_not_json`, `model_output_truncated` | Use a model that follows instructions, or raise `--max-output-tokens`. |
| `provider_http_unauthorized`, `provider_http_payment_required`, `provider_http_not_found`, `provider_http_bad_request` | Bad key, no credit, wrong `--base-url`, or wrong model id for that provider. |
| `duplicate_account`, `duplicate_recipient` | This account or payout address already has a job in the campaign. |
| `job_expired` | The ten-minute reservation lapsed. Check the old job once, then start again. |

## What to tell the owner

- The owner's key pays for one model call even if the job is rejected, and the
  reward is fixed; it is not guaranteed to cover the inference cost.
- The chosen model provider sees the notes and the value-free transcript.
  The enclave protects the session and raw data from Peer; it does not make the
  provider private.
- Field names and status tokens are kept by heuristic rules. What `preview`
  prints is what Peer keeps.
- Responses must be JSON and uncompressed, and a bank that blocks data-centre
  addresses may refuse the enclave's requests even though `preview` worked.
- One contribution per bank account is paid per campaign. For open campaigns the
  account is identified by the `identity` selector the contributor declares.
- Rewards are paid from an AWS KMS key that Peer's operators can also use and
  recover. It is not an escrow.
- A paid transcript does not add the bank to Peer or prove any payment.

Privacy details are in [docs/privacy.md](../../docs/privacy.md) and reward terms
in [docs/incentives.md](../../docs/incentives.md).
