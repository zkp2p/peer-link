# Chase — experimental

Scope: Chase online web account activity, focusing on **outgoing completed domestic ACH debit transfers**. Input is the account activity JSON envelope containing account identification and transaction items, plus an explicit transaction ID. The pure, synchronous function `interpretChase` is located in `transformer.js` (typechecked via TypeScript JSDoc).

## Semantics

- **Payer:** `account.accountId` (or `account.id`) identifies the sender's account within the Chase platform. This is a bank account reference, not a verified legal person. Caller display names are ignored to prevent spoofing.
- **Payee:** Extracted from counterparty routing and account identifiers (`counterparty.routingNumber` and `counterparty.accountNumber`). Masked values, incomplete numbers, or display names alone are insufficient and cause abstention.
- **Amount:** Positive decimal minor units (cents) parsed with integer `BigInt` fixed-point arithmetic (`amountMinor = major * 100 + cents`). Floating-point operations are strictly forbidden to eliminate rounding errors.
- **Currency:** Strictly `USD` with ISO 4217 minor exponent `2`. Conflicting or non-USD currencies abstain.
- **Status:** Only bank-reported `POSTED` or `COMPLETED` final debit statuses are accepted. Pending transactions (`PENDING`), holds, or scheduled payments abstain.
- **Time:** UTC ISO 8601 string (`timestamp` ending in `Z`), reflecting the posted settlement time recorded by Chase.
- **ID:** Scoped explicitly to the Chase transaction ID (`transactionId`). Unverified user memos and memo text are treated as untrusted and excluded from identity logic.

Unsupported: Zelle, domestic/international wires, debit/credit cards, ATM withdrawals, check deposits, and incoming transfers are unsupported. Missing or ambiguous fields return `insufficient_evidence`.

## Local acquisition

1. The authorized account owner signs in normally with multi-factor authentication (MFA) on the official Chase web portal.
2. Navigate to Account Activity / Transactions history and locate an existing completed outgoing domestic ACH transfer. Do not initiate new transfers.
3. Using browser developer tools (Network tab), locate the read-only JSON response for transaction activity.
4. Save the response into the Git-ignored `.local/chase-activity.json` path.
5. Verify the adapter locally:
   `npm run try:bank -- us/chase .local/chase-activity.json <transactionId>`
6. Compare the masked summary output against the Chase banking UI to confirm all details match.
7. Publish only synthetic or sanitized fixtures and a live report. Never commit raw network captures, cookies, session tokens, or personal identifiable information (PII).

## Validation

Synthetic test fixtures (`completed.synthetic.json` and `pending.synthetic.json`) cover completed outgoing ACH transfers and abstention on pending states. The test suite `transformer.test.ts` exercises 50+ negative and boundary conditions, including non-matching transaction IDs, amount parsing anomalies, currency mismatch, status variants, and tampering resilience.
