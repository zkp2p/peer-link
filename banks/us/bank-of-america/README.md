# Bank of America — experimental

Scope: Bank of America web **outgoing USD Zelle payments**, using the activity detail response. Input is the response envelope with `data.activities` and optional `data.accounts`, plus an explicit transaction ID. The pure function `interpretBankOfAmerica` is in `transformer.js` (checked by TypeScript). `matchPayment` compares its output against exact payer, payee, amount and currency claims.

## Semantics

- Payer: `sender.accountId` identifies the debiting account. If `data.accounts` is present in the envelope, the ID must resolve to exactly one account. This is a Bank of America account reference, not a verified legal identity. Never use a display name to fill the gap.
- Payee: `recipient.token` must be a valid email address or E.164 telephone number registered with Zelle. Untrusted contact names and memo fields do not establish identity.
- Amount: negative debit in major USD units; converted to positive minor units (cents) without rounding. Reject excessive precision and unsupported range. USD follows the domestic Zelle surface; explicit conflicting currency fails.
- Status: only `COMPLETED` or `DELIVERED`, with no active holds or dispute state. These observed values do not prove recipient credit or legal irreversibility.
- Time: UTC `postedAt`, not scheduled date or estimated arrival.
- ID: the selected Bank of America activity ID, not a cross-bank canonical payment ID. Memos and confirmation codes are untrusted and do not establish uniqueness or identity.

ACH, domestic/international wires, debit cards, checks, incoming Zelle transfers, pending/scheduled transfers, and recipient credit confirmation are unsupported. Missing or ambiguous facts return insufficient evidence.

## Local acquisition

1. Sign into your authorized Bank of America account in Chrome using standard authentication and MFA.
2. Navigate to Account Activity or Send Money with Zelle > Activity and locate an existing outgoing Zelle payment. Opening transaction details is read-only. Do not initiate or resend payments.
3. Using your browser developer tools or authorized network inspection capability, view the read-only JSON response for the selected activity item or activity feed. Do not copy session cookies, CSRF tokens, or full HAR recordings into fixtures.
4. Run the pure parser locally against the response and selected transaction ID.
5. Publish only synthetic or sanitized fixtures and a revision-specific report following the repository's privacy and contribution rules.

## Validation

Synthetic baseline tests cover status, debit precision, recipient token schemes (email and E.164 phone), holds, disputes, timestamps, unsupported methods, duplicates, and instruction-like memos.
