# Chase (US) USD Zelle Adapter

Scope: One completed USD Zelle transfer from an authorized Chase account activity/detail surface.

## Semantics

- **Payer (A)**: Identified by the account identifier / user profile or sending account details.
- **Payee (B)**: Identified by the recipient name/handle and destination details.
- **Amount**: Decimal string / minor units, representing positive debits/credits for transfers.
- **Currency**: USD.
- **Status**: Completed / sent statuses indicate finality; pending or failed statuses return `insufficient_evidence`.
- **Time**: ISO 8601 UTC timestamp of the completed transaction.
- **ID**: Unique transaction identifier.

## Local Acquisition

Save the JSON response from the authorized web history or transaction details page into `.local/chase-response.json`.

## Validation

Run `npm test` and `npm run validate`.
