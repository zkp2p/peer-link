# bKash — experimental

## Scope

Scope: bKash (mobile app receipt and statement view) **outgoing domestic BDT transfers** (Send Money). Input is the response envelope or receipt payload loaded by the client, plus an explicit transaction ID (bKash TrxID). The pure function `interpretBkash` is in `transformer.js` (checked by TypeScript JSDoc). `matchPayment` compares its output against exact payer, payee, amount and currency claims.

## Semantics

- **Payer**: Full Bangladeshi mobile number (`01...`, 11 digits, or `+8801...`) or bKash wallet identifier (`bkash-account-id`). Masked values (`017••••••01` or `*`) fail closed.
- **Payee**: Full destination Bangladeshi mobile number. Masked values fail closed.
- **Amount**: BDT decimal string converted to integer minor units (poisha, exponent 2: 1 BDT = 100 poisha) using `BigInt` fixed-point arithmetic without floating-point math. Rejects excessive precision (> 2 decimal places), negative, or zero amounts.
- **Currency**: `BDT` only. Missing or conflicting currency fails closed.
- **Status**: Only explicit final bank-reported completed statuses (`COMPLETED`, `SUCCESS`, `SUCCESSFUL`). Pending (`PENDING`, `PROCESSING`, `IN_PROGRESS`) or failed statuses fail closed.
- **Time**: Explicit UTC ISO-8601 string ending with `Z` (`bookedAt` / `timestamp`). Must pass strict calendar date sanity checks.
- **ID**: Selected bKash transaction ID (TrxID). Memos and display text are untrusted.

Unsupported: Cash Out, Merchant Payments, Mobile Recharge, Pay Bill, Add Money, Remittance, Savings & Loans, incoming transfers (credits), and cash deposits. Missing or ambiguous facts return `insufficient_evidence`.

## Local acquisition

1. The account owner signs in normally (including PIN and SMS OTP / device binding) into the bKash mobile app.
2. Navigate to Statement / Transactions or Receipt View and locate an existing outgoing Send Money transfer. Do not create new payments.
3. Using authorized network inspection or developer tools, inspect the read-only transaction receipt or statement response JSON. Do not copy authorization tokens, session cookies, or full HARs.
4. Run the parser locally: `npm run try:bank -- bd/bkash <file>.json <transactionId>` and verify that output matches the bank receipt.
5. Publish only sanitized/synthetic fixtures and a revision-bound report. Never publish real banking credentials, unredacted personal names, or live account balances.

## Validation

Synthetic fixtures cover:
- Completed Send Money outgoing transfers (`completed.synthetic.json`)
- Pending transfers (`pending.synthetic.json`)
- Direct receipt objects and transactions array envelopes
- Positive matches against `matchPayment` claims
- Negative tests for wrong payer, wrong payee, wrong currency, wrong amount, duplicate selection, non-UTC timestamps, invalid calendar dates, masked mobile numbers, and prompt injection in memos.
