# Ziraat Bank — experimental

## Scope

Scope: Ziraat Bank (Ziraat Mobil / Internet Banking) **outgoing domestic TRY transfers** (FAST / EFT / Havale). Input is the JSON response envelope or transaction receipt payload containing transaction details, plus an explicit transaction ID. The pure function `interpretZiraat` is in `transformer.js` (typechecked via TypeScript JSDoc). `matchPayment` compares its output against exact payer, payee, amount and currency claims.

## Semantics

- **Payer**: Full Turkish IBAN (`TR...`, 26 characters) or Ziraat account number (`ziraat-account-id`). Masked values (`*`) fail closed.
- **Payee**: Full destination Turkish IBAN (`TR...`) or account number or FAST Easy Address (Kolay Adres: phone/tax-ID). Masked values fail closed.
- **Amount**: TRY decimal string converted to integer minor units (kuruş, exponent 2: 1 TRY = 100 kuruş) using `BigInt` fixed-point arithmetic without floating-point math. Rejects excessive precision (> 2 decimal places), negative, or zero amounts.
- **Currency**: `TRY` only. Missing or conflicting currency fails closed.
- **Status**: Only explicit final bank-reported completed statuses (`COMPLETED`, `SUCCESS`, `BASARILI`, `GERCEKLESTI`). Pending (`BEKLEMEDE`, `ISLEMDE`, `PENDING`) or failed statuses fail closed.
- **Time**: Explicit UTC ISO-8601 string ending with `Z` (`bookedAt` / `timestamp`). Must pass strict calendar date sanity checks.
- **ID**: Selected Ziraat transaction/referans ID. Memos and display text are untrusted.

Unsupported: Card transactions, utility/bill payments, tax payments, currency exchange (döviz), international SWIFT wires, incoming transfers (credits), and cash deposits. Missing or ambiguous facts return `insufficient_evidence`.

## Local acquisition

1. The account owner signs in normally (including MFA/SMS verification) into Ziraat Mobil or Ziraat Internet Banking.
2. Navigate to Hesap Hareketleri (Account Activity) or Dekont Görüntüleme (Receipt View) and locate an existing outgoing domestic transfer. Do not create new payments.
3. Using authorized network inspection or developer tools, inspect the read-only transaction receipt or history response JSON. Do not copy authorization tokens, session cookies, or full HARs.
4. Run the parser locally: `npm run try:bank -- tr/ziraat <file>.json <transactionId>` and verify that output matches the bank receipt.
5. Publish only sanitized/synthetic fixtures and a revision-bound report. Never publish real banking credentials, unredacted personal names, or live account balances.

## Validation

Synthetic fixtures cover:
- Completed FAST / EFT / Havale outgoing transfers (`completed.synthetic.json`)
- Pending transfers (`pending.synthetic.json`)
- Direct receipt objects and transactions array envelopes
- Positive matches against `matchPayment` claims
- Negative tests for wrong payer, wrong payee, wrong currency, wrong amount, duplicate selection, non-UTC timestamps, invalid calendar dates, masked IBANs, and prompt injection in memos.
