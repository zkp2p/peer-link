# Kaspi Bank — experimental

## Scope

Scope: Kaspi Bank (Kaspi.kz mobile app receipt and transaction history) **outgoing domestic KZT transfers** (Kaspi-to-Kaspi / Kaspi Перевод). Input is the response envelope or receipt payload loaded by the client, plus an explicit transaction ID. The pure function `interpretKaspi` is in `transformer.js` (checked by TypeScript JSDoc). `matchPayment` compares its output against exact payer, payee, amount and currency claims.

## Semantics

- **Payer**: Full Kazakh mobile phone number (`+77...` / `87...`, 11 digits) or Kazakh IBAN (`KZ...`) or Kaspi account ID (`kaspi-account-id`). Masked values (`+7 7•• ••• •• 01` or `*`) fail closed.
- **Payee**: Full destination Kazakh phone number, IBAN or card-linked account identifier. Partial display names (e.g. `Алексей С.`) fail closed when an account or phone identifier is absent or masked.
- **Amount**: KZT decimal string converted to integer minor units (tiyn, exponent 2: 1 KZT = 100 tiyn) using `BigInt` fixed-point arithmetic without floating-point math. Rejects excessive precision (> 2 decimal places), negative, or zero amounts.
- **Currency**: `KZT` only. Missing or conflicting currency fails closed.
- **Status**: Only explicit final bank-reported completed statuses (`COMPLETED`, `SUCCESS`, `ВЫПОЛНЕН`, `ОПЛАЧЕН`). Pending (`PENDING`, `В ОБРАБОТКЕ`, `PROCESSING`) or failed statuses fail closed.
- **Time**: Explicit UTC ISO-8601 string ending with `Z` (`bookedAt` / `timestamp`). Must pass strict calendar date sanity checks.
- **ID**: Selected Kaspi transaction ID. Memos and display text are untrusted.

Unsupported: Kaspi Red installments, Kaspi Kredit, Kaspi Pay merchant QR, utility payments, mobile balance top-up, government payments, incoming transfers (credits), and cash deposits. Missing or ambiguous facts return `insufficient_evidence`.

## Local acquisition

1. The account owner signs in normally (including biometric / SMS OTP verification) into the Kaspi.kz mobile app.
2. Navigate to Сообщения / Переводы (Transfers Activity) or Детали платежа (Receipt View) and locate an existing outgoing Kaspi transfer. Do not create new payments.
3. Using authorized network inspection or developer tools, inspect the read-only transaction receipt or statement response JSON. Do not copy authorization tokens, session cookies, or full HARs.
4. Run the parser locally: `npm run try:bank -- kz/kaspi <file>.json <transactionId>` and verify that output matches the bank receipt.
5. Publish only sanitized/synthetic fixtures and a revision-bound report. Never publish real banking credentials, unredacted personal names, or live account balances.

## Validation

Synthetic fixtures cover:
- Completed Kaspi-to-Kaspi outgoing transfers (`completed.synthetic.json`)
- Pending transfers (`pending.synthetic.json`)
- Positive matches against `matchPayment` claims
- Negative tests for wrong payer, wrong payee, wrong currency, wrong amount, duplicate selection, non-UTC timestamps, invalid calendar dates, masked phone numbers, and prompt injection in memos.
