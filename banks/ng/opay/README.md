# OPay — experimental

## Scope

OPay mobile application transaction detail and receipt export payloads.
The adapter covers exactly one payment type: **completed outgoing domestic NGN transfers** (including OPay-to-OPay wallet transfers and OPay-to-bank NIBSS Instant Payment / NIP transfers).

The adapter accepts a JSON envelope containing the sender's account/wallet metadata and transaction movement records, along with the unique transaction reference code (`orderNo`, `reference`, `sessionId`, or `transactionId`).

## Semantics

- **Payer**: Identified by `account.accountNo`, `account.walletNumber`, or `account.id` (10-digit NUBAN or Nigerian phone number, scheme `ng-opay-account` or `ng-nuban`). Masked numbers containing `*` or `•` are rejected.
- **Payee**: Identified by `counterparty.accountNumber` or `beneficiary.accountNo` (10-digit NUBAN account or OPay wallet, scheme `ng-nuban` or `ng-opay-account`). Must be fully unmasked.
- **Amount**: Nigerian Naira (NGN), ISO 4217 exponent `2` (kobo). Negative numbers indicate debit movements. `amountMinor` is recorded in integer kobo (e.g. `5000.00` NGN = `500000` kobo).
- **Currency**: Must be `NGN` (or numeric code `566`). Other currencies fail closed.
- **Status**: Terminal settlement statuses accepted: `completed`, `SUCCESS`, `Successful`, `settled`. Pending, processing, or failed transactions fail closed.
- **Time**: Formatted as an explicit ISO 8601 UTC timestamp (`timeIso` or UTC converted timestamp).
- **ID**: Selected transaction identifier matching `row.id`, `row.orderNo`, `row.reference`, or `row.sessionId`. Memos and customer notes are untrusted.

Unsupported operations:
- Incoming payments and wallet top-ups (`credit`)
- Airtime and mobile data recharges
- Utility bills, TV subscriptions, and government levies
- Betting, gaming, and lottery wallet fundings
- POS card debit purchases and ATM cash-out
- Pending authorizations and unconfirmed movements
- Non-NGN foreign currency operations

## Local acquisition

1. The account owner signs in normally to the OPay mobile app on their own device.
2. Navigate to Transaction History > Details (`Transaction Details / Share Receipt`) and select an existing completed outgoing transfer. Do not initiate new payments.
3. Export the transaction receipt or view details in local browser / proxy inspection, saving the JSON locally under `.local/opay-transaction.json`.
4. Run `npm run try:bank -- ng/opay .local/opay-transaction.json <transactionId>` and compare the redacted summary with the official transaction receipt. Never commit raw bank files to Git.

## Validation

- Tested with synthetic completed and pending fixtures reflecting OPay transfer receipts and transaction detail envelopes.
- Negative test coverage verifies rejection of amount discrepancies, non-NGN currencies, unsupported rails (airtime, betting, utility bills, card payments, ATM cash-out, incoming credits), masked identifiers, duplicate transaction entries, and prompt injection attempts in memos.
