# Chase

## Scope

Scope: Chase (Chase Online / Mobile Banking) outgoing domestic USD ACH transfers. Input is the JSON response envelope or transaction detail payload containing transaction details, plus an explicit transaction ID. The pure function `interpretChase` is in `transformer.js` (typechecked via TypeScript JSDoc). `matchPayment` compares its output against exact payer, payee, amount and currency claims.

## Semantics

1. Payer: Full Chase account number (`chase-account-number`) or account identifier. Masked values fail closed.
2. Payee: Full destination US routing number (9 digits) and account number (4 to 17 digits) under scheme `us-routing-account`. Masked values fail closed.
3. Amount: USD decimal string or number converted to integer minor units (cents, exponent 2: 1 USD = 100 cents) using `BigInt` fixed-point arithmetic without floating-point math. Rejects excessive precision (> 2 decimal places), negative, or zero amounts.
4. Currency: `USD` only. Missing or conflicting currency fails closed.
5. Status: Only explicit final bank-reported completed statuses (`POSTED`, `COMPLETED`, `PAID`). Pending (`PENDING`, `PROCESSING`, `SCHEDULED`) or failed statuses fail closed.
6. Time: Explicit UTC ISO-8601 string ending with `Z` (`postedAt` or `timestamp`). Must pass strict calendar date sanity checks.
7. ID: Selected Chase transaction or payment reference ID. Memos and display text are untrusted.

Unsupported: Zelle transfers, wire transfers, debit card purchases, bill payments, incoming ACH credits, and check deposits. Missing or ambiguous facts return `insufficient_evidence`.

## Local acquisition

1. The account owner signs in normally into Chase Online Banking.
2. Navigate to Account Activity and locate an existing outgoing domestic ACH transfer. Do not initiate new payments.
3. Using authorized browser developer tools, save the transaction activity response payload to `.local/chase-activity.json`.
4. Run the parser locally: `npm run try:bank -- us/chase .local/chase-activity.json <transactionId>` and verify that output matches the bank record.
