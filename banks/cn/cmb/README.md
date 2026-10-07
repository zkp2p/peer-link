# China Merchants Bank — experimental

## Scope

China Merchants Bank personal internet banking web transaction history and transfer detail (`web-internet-banking-transfer-detail`), covering completed outgoing domestic CNY transfers. The adapter receives the JSON transaction record returned by the web banking application and an explicit ledger transaction ID.

## Semantics

- Payer: `account.id` identifies the authenticated sender's account with scheme `cmb-account-id`.
- Payee: `transaction.counterparty.accountNumber` identifies the recipient's bank card / account number with scheme `cn-account-number`. Masked values abstain.
- Amount: `transaction.amount` as a decimal string in whole yuan with up to two decimal places, converted exactly to fen (1 CNY = 100 minor units) without floating-point math.
- Currency: `transaction.currency` strictly `CNY` (ISO 4217 minor-unit exponent 2).
- Status: strictly `completed`; pending, processing, failed or cancelled transactions abstain.
- Time: `transaction.bookedAt` explicit UTC ISO-8601 timestamp ending in `Z`.
- ID: `transaction.id` unique transaction identifier within the response. Display names and memos are untrusted data.

Unsupported: cross-border remittances, foreign currency transfers, credit card payments, pending/scheduled transfers, and incoming payments. Missing or ambiguous facts return `insufficient_evidence`.

## Local acquisition

1. The account owner signs in normally (including SMS/USB-key MFA) in personal internet banking.
2. Navigate to Transaction History / Transfer Records and select an existing completed domestic transfer.
3. Inspect network traffic in DevTools (Fetch/XHR) to obtain the transaction detail response, saving the JSON body locally under `.local/cmb-response.json`.
4. Run `npm run try:bank -- cn/cmb .local/cmb-response.json <transactionId>` to verify output against the banking UI. Never commit banking records or credentials.

## Validation

Covered by hermetic synthetic fixtures (`completed.synthetic.json`, `pending.synthetic.json`) and comprehensive negative tests in `transformer.test.ts` verifying malformed envelopes, unconfirmed statuses, invalid currencies, timestamp bounds, masked counterparty handling, and prompt-injection memo immunity.
