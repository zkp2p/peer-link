# Bank of America — experimental

## Scope

Bank of America online banking account activity and transaction detail payloads (`web-activity-detail`).
The adapter covers exactly one payment type: **completed outgoing domestic USD ACH transfers**.

The adapter takes a JSON envelope containing the sender's account metadata and transaction records, along with the unique transaction reference code (`referenceNumber`, `confirmationNumber`, `transactionId`, or `id`).

## Semantics

- **Payer**: Identified by `account.accountNumber` or `account.id` (10-12 digit checking or savings account number, scheme `us-account-number` or `us-ach`). Masked accounts containing `*` or `•` are rejected.
- **Payee**: Identified by `counterparty.routingNumber` + `:` + `counterparty.accountNumber` (scheme `us-ach`), or `counterparty.accountNumber` (scheme `us-account-number`). Must be fully unmasked.
- **Amount**: US Dollar (USD), ISO 4217 exponent `2` (cents). Negative numbers indicate debit movements. `amountMinor` is recorded in integer cents (e.g. `$150.00` is recorded as `15000`).
- **Currency**: Must be `USD` (or numeric code `840`). Other currencies fail closed.
- **Status**: Terminal settlement statuses accepted: `completed`, `Posted`, `posted`, `settled`, `SUCCESS`. Pending, scheduled, processing, or failed transactions fail closed.
- **Time**: Formatted as an explicit ISO 8601 UTC timestamp (`timeIso` or UTC converted timestamp).
- **ID**: Selected transaction identifier matching `row.id`, `row.referenceNumber`, `row.confirmationNumber`, or `row.transactionId`. Memos and customer notes are untrusted.

Unsupported operations:
- Incoming deposits and credits
- Wire transfers and international remittances
- Check deposits, check payments, and draft checks
- Debit card purchases, POS transactions, and ATM cash withdrawals
- Credit card payments and account adjustments
- Pending, scheduled, or processing transactions
- Non-USD foreign currency transactions

## Local acquisition

1. The account owner signs in normally to Bank of America online banking (`https://www.bankofamerica.com/`) in their own browser.
2. Navigate to Accounts > Activity > Transaction Details and select an existing completed outgoing domestic ACH transfer. Do not initiate new payments.
3. In browser Developer Tools (Network tab), locate the account activity JSON response and save it locally under `.local/bofa-activity.json`.
4. Run `npm run try:bank -- us/bank-of-america .local/bofa-activity.json <transactionId>` and compare the redacted summary with the official transaction detail. Never commit raw bank files to Git.

## Validation

- Tested with synthetic completed and pending fixtures reflecting Bank of America activity detail structures.
- Negative test coverage verifies rejection of amount discrepancies, non-USD currencies, unsupported rails (wire, checks, cards, ATM, pending/scheduled items, incoming credits), masked identifiers, duplicate transaction entries, and prompt injection attempts in memos.
