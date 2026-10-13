# HDFC encrypted transcript support

The approved release includes `hdfc-open-v1`: a fixed $10 USDC reward for each
accepted transcript, up to five distinct accounts, subject to the shared budget
and a successful reservation. One owner-authorized contribution completed enclave
acquisition, NEAR grading and payment on October 13, 2026. This is transcript
acquisition support, not a completed Peer payment integration.

## Observed read

The HDFC retail site's Recent Transactions page issues one read:

```text
POST https://api-now.hdfc.bank.in/api/dis-transaction-service/client-api/v1/recent-transactions
Content-Type: application/json
```

Its logical body is an object containing only `accountNo`, a string of digits.
The wire body and response use base64 of a 16-byte IV, AES-GCM ciphertext and
16-byte authentication tag, with no additional authenticated data. TLS remains
required. The application session key is separate from the bank session headers.
This describes the observed bank web client, not a documented public API contract.

`transcripts/hdfc_session.py` implements this framing with a fresh random IV for
each request. It accepts only this exact origin/path, one POST and the fixed
selectors below. It rejects redirects through the existing HTTP transport,
plaintext authenticated responses, invalid tags, oversized responses and records
whose `arrangementId` differs from the requested account. There is no general
encrypted request or payment endpoint facility.

The anonymous probe removes secret headers and performs the same encrypted read.
If a successful response exposes identity or history, including plaintext history,
the contribution is rejected. An unreadable encrypted success also fails closed.

## Campaign opt-in

The measured HDFC campaign uses `bankId: in/hdfc`, `country: IN` and these exact
source descriptors:

```json
{
  "sources": [{
    "origin": "https://hdfc.bank.in",
    "paths": ["/"],
    "methods": ["GET", "POST"],
    "parameterNames": [],
    "headerNames": []
  }],
  "openSource": {
    "version": 2,
    "kind": "open-json-read-v1",
    "maxReads": 1,
    "transport": "hdfc-aes-gcm-v1"
  }
}
```

These are only the source-related fields, not a complete policy. Existing
version-1 open campaigns continue to accept their ordinary header/token
credentials and cannot opt into this transport accidentally.

The measured Dockerfile includes the new module. Code and policy changes require
a new signed enclave build, measured PCRs, state namespace and release metadata;
follow [transcript operations](transcript-operations.md). Local success does not
establish that HDFC accepts the enclave host's network address.

## Private contributor inputs after release

Use the ordinary [contribution skill](../skills/contribute-transcript/SKILL.md)
for owner sign-in, status/limitations, consent, inference choice, submission,
receipt and cleanup. For this transport, the credential kind is `hdfc_session`.
`PEERLINK_BANK_CREDENTIAL` is a JSON object with exactly `headers` and `aesKey`:

```json
{
  "headers": {"X-Session-Header": "<matching current request value>"},
  "aesKey": "<base64 of the matching 16- or 32-byte application session key>"
}
```

This is a shape illustration, not working authentication. Capture the headers
and key from the same owner-authorized history request. A login refresh can
invalidate both. Do not substitute headers from a keepalive or another endpoint,
change transaction headers to request plaintext, or disable encryption. If the
current web client cannot export the matching key, stop rather than changing its
security settings. Never paste the key or headers into chat, logs or notes.

Keep account identifiers and any temporary session capture in ignored `.local/`
files with mode 600. Prefer owner-exported environment credentials and
`--secrets-from-env`. Use this recipe shape, replacing the placeholder privately:

```json
{
  "credential": {"origin": "https://api-now.hdfc.bank.in", "kind": "hdfc_session"},
  "profileId": null,
  "recipe": {
    "version": 3,
    "reads": [{
      "url": "https://api-now.hdfc.bank.in/api/dis-transaction-service/client-api/v1/recent-transactions",
      "method": "POST",
      "contentType": "application/json",
      "body": "{\"accountNo\":\"<selected account number>\"}"
    }],
    "identity": {"read": 0, "path": [0, "arrangementId"]},
    "history": {"read": 0, "path": []}
  },
  "notes": "History uses application encryption over TLS. The account number in the body matches arrangementId in every row. The description is free text, not a verified payee identifier. Completion semantics are not established.",
  "transcript": []
}
```

The body above is logical JSON, not captured ciphertext. The key is used only by
the transport and never becomes an HTTP header or transcript field. The existing
version-2 transcript describes the logical request body and decrypted response
shapes; it is not a record of the wire encryption. Include the encryption
requirement in notes. `lookup` is intentionally unavailable: the single history
read already supplies identity. Use `preview` with at least three history rows.

The observed mapping, suitable for a local `--mapping` file, is:

```json
{
  "paymentId": "$[].id",
  "amount": "$[].transactionAmountCurrency.amount",
  "timestamp": "$[].bookingDate",
  "counterparty": "$[].description",
  "currency": "$[].transactionAmountCurrency.currencyCode",
  "status": "$[].billingStatus"
}
```

Description is narration, not a verified VPA/account identifier. Booking date
does not establish settlement time; billing status does not establish payment
finality. A mapping score measures the current rubric's field coverage, not
readiness for payment verification. Stable ids across reads, payee parsing,
amount/direction semantics, finality and pagination still need validation before
building a Peer payment integration. No completed-status token is asserted here.

## Evidence from October 13, 2026

An owner-authorized local CLI preview, using a private draft campaign against
the bank's live endpoint, passed encrypted acquisition, anonymous gating,
account matching and redaction. The manually proposed mapping scored 100/100
with no unverified roles. This was run from the implementation worktree based on
upstream `9cee092`; it was not an enclave submission. The earlier stale session
failed with an authorization error and succeeded after the owner signed in again.

Synthetic tests separately cover transport dispatch through the runtime,
value-free model input and archive, duplicate rejection, fixed failures, exact
read scope, wrong keys, tampered ciphertext, plaintext rejection, account
mismatch, size/history limits and secret cleanup references. Synthetic payout
coordination is not a real reward payment.

The subsequent operator-owned release validation used measured source
`4cba61e76773af05cbc24dedaff451f05e060865`, independently matching both CI
builders and the signed host image. Fresh Nitro attestation preceded an encrypted
submission. The enclave acquired authenticated HDFC history, passed its anonymous
and account-matching gates, and sent only the value-free transcript and notes to
NEAR `z-ai/glm-5.3-flash`. Code verified the model mapping at 100/100; the model
asserted no completed-status token. Reported usage was 1,020 input tokens and
67 output tokens.

The contribution received an automatic [10 USDC payout on
Base](https://basescan.org/tx/0xc49955122186ec668d6c432388ed8ae7f0b85558d69d23e68bbdf0f3976f03ba).
The transfer and recipient balance increase were independently verified. Accepted,
payout-pending and paid signed records reached the private archive. A controlled
same-image restart preserved the identical paid receipt, epoch, remaining budget
and payout nonce, with a fresh ingress key and no new submission or payment.
See [scoped release evidence](../transcripts/hdfc-release-evidence.json).

The existing 120 USDC was refunded and reused for this epoch; after this payment,
110 USDC remained. That observation is not a current capacity promise. Temporary
browser hooks were restored and private bank capture files deleted. Contributors
must sign out after their job and delete temporary bank inputs. An explicitly
retained inference key should remain capped and outside Git.

To validate code locally:

```sh
npm run transcripts:test
npm run check:bank
npm run build
```

Future measured changes still require the full diff and privacy scans, independent
builds, release gates and owner-authorized live validation. Contributors use the
unmodified published `main` release; the internal validation above used the
operator's independently verified candidate pin before publication.
