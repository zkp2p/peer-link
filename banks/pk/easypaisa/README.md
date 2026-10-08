# Easypaisa — experimental

Scope: Easypaisa app **transaction history**, one payment type only: a completed
outgoing **Easypaisa-to-Easypaisa wallet transfer** (PKR debit). This choice —
wallet transfer rather than IBFT/Raast — is documented in issue #86's scope:
the native mobile-money rail has the simplest finality semantics, while
IBFT/Raast involve interbank settlement with different status lifecycles and
are explicitly unsupported here. Input is the response envelope the bank page
loaded (`account` plus `transactions`), plus an explicit transaction ID. The
pure function `interpretEasypaisa` is in transformer.js (checked by
TypeScript). `matchPayment` compares its output against exact payer, payee,
amount and currency claims.

## Semantics

- Payer: `account.id` must be a non-empty string. This is an Easypaisa account
  reference, not a verified legal identity. Never use a display name or
  caller-supplied legal name to fill the gap.
- Payee: `counterparty.msisdn` must be a **full** Pakistani mobile number:
  `03XX-XXXXXXX` or `+923XX-XXXXXXX`. Masked numbers (`0300****001`) and
  display names alone are not unique payee identifiers and fail closed, per
  issue #86. The MSISDN is a routing identifier, not proof the wallet exists
  or belongs to the named party.
- Amount: decimal string in major PKR units (for example `"125.50"`),
  converted to integer paisa (minor units) without rounding or floating-point
  math. More than two decimals, zero, negative or non-string amounts fail.
- Currency: must be exactly `PKR`. PKR uses ISO 4217 exponent 2 (paisa). A
  missing or conflicting currency fails.
- Status: only the exact bank-reported value `SUCCESS`. Pending, failed,
  reversed, cancelled and unknown statuses return insufficient evidence.
  These observed values do not prove recipient credit or legal irreversibility.
- Time: `completedAt` as an explicit UTC timestamp ending in `Z` (for example
  `2026-10-06T09:30:00Z`), validated with a date round-trip. The Easypaisa
  surface operates in Asia/Karachi (UTC+5, no daylight saving); local
  wall-clock times are converted to UTC during acquisition and the conversion
  is recorded in the acquisition notes.
- ID: the selected transaction `id`, unique within the response page — not a
  cross-bank canonical payment ID. Memos are untrusted and do not establish
  uniqueness or identity.

IBFT, Raast, bill payments, mobile top-ups, incoming transfers, arbitrary
status variants and recipient credit are unsupported. Missing or ambiguous
facts return insufficient evidence. Selection is page-local: if the
transaction is absent, navigate to the correct page. This does not claim to
have searched complete history.

**Response-shape assumption.** The envelope shape above is a documented
assumption based on the public Easypaisa surface; it has not yet been
confirmed against a live authorized session. The account-owner live check
must confirm (or correct) the field names for the transaction list, status
values, timestamp format and counterparty identifier before this adapter is
submitted. If the real shape differs, the adapter, fixtures and tests are
updated to match — never the other way round.

## Local acquisition

1. The account owner signs into their own Easypaisa account in their own
   browser (including any MFA). The contributor never handles credentials.
2. Open transaction history and find an existing completed
   Easypaisa-to-Easypaisa transfer. Opening transaction details is read-only.
   Do not create or resend payments.
3. With the owner's authorized network-inspection capability or browser
   developer tools, inspect the response of the transaction-history request
   the app/web UI itself makes. Save only the response body under
   `.local/easypaisa-response.json`. Never export a HAR or copy request
   cookies, authorization headers or tokens.
4. Convert any Asia/Karachi local timestamps to UTC (`Z`) when shaping the
   documented input; record the conversion in the live report notes.
5. Run `npm run try:bank -- pk/easypaisa .local/easypaisa-response.json <transactionId>`
   and compare every redacted field with the bank's own UI. The code does not
   supply credentials or replay requests.
6. Publish only a synthetic/sanitized fixture and a revision-specific report,
   following the contribution skill. Do not upload the raw response to the
   landing page or a public issue. Delete the local response afterwards.

## Validation

Synthetic fixtures cover: a completed wallet transfer (supported), pending
and failed statuses (abstentions), and an IBFT transfer (unsupported).
Negative tests cover malformed envelopes, absent/duplicate selection, every
non-final status, unsupported payment types and directions, invalid amounts
(zero, negative, over-precision, non-string, out-of-range), missing or
conflicting currency, ambiguous/invalid timestamps (including `+05:00`
offsets, which must be converted at acquisition), missing or masked payee
MSISDNs, missing payer identifiers, instruction-like memos and display
names, and unrelated malformed feed rows. No live observations exist yet;
the live report template (`LIVE_REPORT_TEMPLATE.md` in the bounty working
directory, kept out of this repo) describes exactly what the account owner
must provide. A synthetic fixture alone is not live validation.
