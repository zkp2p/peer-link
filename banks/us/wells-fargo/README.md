# Wells Fargo — experimental

## Scope

This adapter covers Wells Fargo web account activity and transaction detail records for outgoing domestic USD ACH transfers (`outgoingDomesticTransfer`).
It parses the clean JSON activity response payload loaded by the account activity view and interprets an explicit transaction ID.

## Semantics

- **Payer (A)**: Identified by `account.id` (Wells Fargo internal account identifier, scheme `wells-fargo-account-id`).
- **Payee (B)**: Identified by `transaction.counterparty.routingNumber` and `transaction.counterparty.accountNumber` (scheme `us-routing-account`). Masked or partial values fail closed with `insufficient_evidence`.
- **Amount**: Reported in USD as a decimal string (`amount`) representing a debit transaction. Scaled to integer minor units (cents) via BigInt arithmetic to eliminate IEEE-754 precision errors.
- **Currency**: Explicitly verified as `USD` with ISO 4217 exponent `2`. Missing or conflicting currencies abstain.
- **Status**: Only the bank-final status `"completed"` is recognized as a supported completed payment. Pending, scheduled, cancelled, or disputed transfers fail closed.
- **Time**: Sourced from `postedAt`, an ISO 8601 UTC timestamp recording the bank ledger posting date.
- **ID**: Sourced from `transaction.id`, representing the unique Wells Fargo ledger transaction identifier.

### Unsupported

- Wire transfers, check deposits, card point-of-sale debits, and incoming transfers are unsupported.
- Recipient-credit confirmation is not guaranteed; "completed" represents the sending bank's ledger settlement.
- Ambiguous or malformed counterparty information returns `insufficient_evidence`.

## Local acquisition

1. The account owner signs into Wells Fargo online banking through their standard browser session with MFA.
2. Navigate to Account Activity for the checking account and select an existing completed outgoing domestic ACH transfer.
3. In Developer Tools (Network tab), capture the account activity JSON response for that transaction.
4. Save the raw capture locally under `.local/` (never commit raw banking data to Git).
5. Verify interpretation locally using `npm run try:bank -- us/wells-fargo .local/<file>.json <transactionId>`.
