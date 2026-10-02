# BCA — experimental

## Scope

Scope: Bank Central Asia (myBCA / KlikBCA) **outgoing domestic IDR transfers** (BCA Transfer / BI-FAST). Input is the JSON response envelope or transaction mutation detail receipt loaded by the client, plus an explicit transaction ID. The pure function `interpretBca` is in `transformer.js` (checked by TypeScript JSDoc). `matchPayment` compares its output against exact payer, payee, amount and currency claims.

## Semantics

- **Payer**: Full BCA account number (10 digits) or BCA customer ID (`bca-account-id`). Masked values (`0123••••89` or `*`) fail closed.
- **Payee**: Full destination account number (BCA or other domestic Indonesian bank via BI-FAST) or proxy address. Masked values fail closed.
- **Amount**: Whole IDR decimal or integer string converted to integer minor units (exponent 0: 1 IDR = 1 minor unit) using `BigInt` fixed-point arithmetic without floating-point math. Rejects negative or zero amounts.
- **Currency**: `IDR` only. Missing or conflicting currency fails closed.
- **Status**: Only explicit final bank-reported completed statuses (`BERHASIL`, `SUCCESS`, `COMPLETED`). Pending (`DIPROSES`, `PENDING`, `IN_PROGRESS`) or failed statuses fail closed.
- **Time**: Explicit UTC ISO-8601 string ending with `Z` (`bookedAt` / `timestamp`). Must pass strict calendar date sanity checks.
- **ID**: Selected BCA transaction/mutation reference number. Memos and display text are untrusted.

Unsupported: QRIS merchant payments, BCA Virtual Account bill payments, tax payments, auto-debit, currency exchange, incoming transfers (credits), and cash deposits. Missing or ambiguous facts return `insufficient_evidence`.

## Local acquisition

1. The account owner signs in normally (including User ID, PIN, and KeyBCA / SMS OTP) into myBCA or KlikBCA.
2. Navigate to Mutasi Rekening (Account Mutation) or Bukti Transaksi (Transaction Receipt) and locate an existing outgoing domestic transfer. Do not create new payments.
3. Using authorized network inspection or developer tools, inspect the read-only transaction receipt or mutation detail JSON. Do not copy authorization tokens, session cookies, or full HARs.
4. Run the parser locally: `npm run try:bank -- id/bca <file>.json <transactionId>` and verify that output matches the bank receipt.
5. Publish only sanitized/synthetic fixtures and a revision-bound report. Never publish real banking credentials, unredacted personal names, or live account balances.

## Validation

Synthetic fixtures cover:
- Completed BCA Transfer / BI-FAST outgoing transfers (`completed.synthetic.json`)
- Pending transfers (`pending.synthetic.json`)
- Positive matches against `matchPayment` claims
- Negative tests for wrong payer, wrong payee, wrong currency, wrong amount, duplicate selection, non-UTC timestamps, invalid calendar dates, masked account numbers, and prompt injection in memos.
