# GCash — experimental

## Scope

Scope: GCash (mobile app receipt and transaction history) **outgoing domestic PHP transfers** (Send Money / InstaPay). Input is the response envelope or receipt payload loaded by the client, plus an explicit transaction reference ID. The pure function `interpretGcash` is in `transformer.js` (checked by TypeScript JSDoc). `matchPayment` compares its output against exact payer, payee, amount and currency claims.

## Semantics

- **Payer**: Full Philippine mobile number (`09...`, 11 digits, or `+639...`) or GCash account reference identifier (`gcash-account-id`). Masked values (`09•••••••01` or `*`) fail closed.
- **Payee**: Full destination Philippine mobile number or recipient account/InstaPay identifier. Masked values fail closed.
- **Amount**: PHP decimal string converted to integer minor units (centavos, exponent 2: 1 PHP = 100 centavos) using `BigInt` fixed-point arithmetic without floating-point math. Rejects excessive precision (> 2 decimal places), negative, or zero amounts.
- **Currency**: `PHP` only. Missing or conflicting currency fails closed.
- **Status**: Only explicit final bank-reported completed statuses (`COMPLETED`, `SUCCESS`, `PAID`). Pending (`PENDING`, `PROCESSING`, `IN_PROGRESS`) or failed statuses fail closed.
- **Time**: Explicit UTC ISO-8601 string ending with `Z` (`bookedAt` / `timestamp`). Must pass strict calendar date sanity checks.
- **ID**: Selected GCash transaction/reference number. Memos and display text are untrusted.

Unsupported: Cash-In, Cash-Out, Pay Bills, Buy Load, GSave, GLone, GInvest, GGives, merchant QR payments, incoming transfers (credits), and cash deposits. Missing or ambiguous facts return `insufficient_evidence`.

## Local acquisition

1. The account owner signs in normally (including MPIN and biometric/OTP authentication) into the GCash mobile app.
2. Navigate to Activity / Transaction History or Receipt View and locate an existing outgoing Send Money transfer. Do not create new payments.
3. Using authorized network inspection or developer tools, inspect the read-only transaction receipt or history response JSON. Do not copy authorization tokens, session cookies, or full HARs.
4. Run the parser locally: `npm run try:bank -- ph/gcash <file>.json <transactionId>` and verify that output matches the bank receipt.
5. Publish only sanitized/synthetic fixtures and a revision-bound report. Never publish real banking credentials, unredacted personal names, or live account balances.

## Validation

Synthetic fixtures cover:
- Completed Send Money outgoing transfers (`completed.synthetic.json`)
- Pending transfers (`pending.synthetic.json`)
- Direct receipt objects and transactions array envelopes
- Positive matches against `matchPayment` claims
- Negative tests for wrong payer, wrong payee, wrong currency, wrong amount, duplicate selection, non-UTC timestamps, invalid calendar dates, masked mobile numbers, and prompt injection in memos.
