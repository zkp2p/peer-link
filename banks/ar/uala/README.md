# Ualá — experimental

Scope: Ualá Argentina mobile transaction receipt and activity records, focusing on **outgoing completed ARS domestic transfers by CVU/CBU or alias**. Input is the transaction detail receipt JSON envelope, plus an explicit transaction ID. The pure, synchronous function `interpretUala` is located in `transformer.js` (typechecked via TypeScript JSDoc).

## Semantics

- **Payer:** Sender CVU (22 digits) or account reference (`sender.cvu` or `sender.accountId`). Display names or aliases alone are insufficient and excluded from authoritative identity.
- **Payee:** Recipient CVU/CBU (22 digits) or registered banking alias (`receiver.cvu` or `receiver.alias`). Masked digits or display names alone are insufficient and cause fail-closed abstention.
- **Amount:** Positive decimal minor units (centavos) parsed with integer `BigInt` fixed-point arithmetic (`amountMinor = major * 100 + centavos`). Floating-point arithmetic is strictly forbidden.
- **Currency:** Strictly `ARS` with ISO 4217 minor exponent `2`. Non-ARS currencies abstain.
- **Status:** Only bank-reported `COMPLETED`, `APROBADA`, or `EXITOSA` final debit statuses are accepted. Pending transactions (`PENDING`, `EN_PROCESO`) or rejected transfers abstain.
- **Time:** UTC ISO 8601 string (`timestamp` ending in `Z`), reflecting the transaction settlement time recorded by Ualá / COELSA.
- **ID:** Scoped explicitly to the Ualá transaction ID or COELSA transfer ID (`transactionId`). Unverified user memos and concepts are treated as untrusted.

Unsupported: Card purchases, credit line financing, mutual fund investments, crypto swaps, and incoming transfers are unsupported. Missing or ambiguous fields return `insufficient_evidence`.

## Local acquisition

1. The authorized account owner signs in normally with biometric/PIN authentication in the official Ualá mobile app.
2. Navigate to Activity / Movements and locate an existing completed outgoing transfer receipt. Do not initiate new transfers.
3. Export or inspect the receipt transaction details using authorized local developer inspection tools.
4. Save the response into the Git-ignored `.local/uala-receipt.json` path.
5. Verify the adapter locally:
   `npm run try:bank -- ar/uala .local/uala-receipt.json <transactionId>`
6. Compare the masked summary output against the Ualá app receipt to confirm all details match.
7. Publish only synthetic or sanitized fixtures and a live report. Never commit raw network captures, cookies, PINs, or personal identifiable information (PII).

## Validation

Synthetic test fixtures (`completed.synthetic.json` and `pending.synthetic.json`) cover completed outgoing transfers and abstention on pending states. The test suite `transformer.test.ts` exercises 35+ negative and boundary conditions, including non-matching transaction IDs, amount parsing anomalies, currency mismatch, status variants, and tampering resilience.
