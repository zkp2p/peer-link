# Monobank — experimental

## Scope

Interprets completed outgoing domestic transfers denominated in Ukrainian Hryvnia (UAH) from the Monobank personal API statement surface (`personal-api-statement`).

The adapter receives a structured JSON document representing the authenticated statement and an explicit `transactionId`. It selects exactly that transaction and produces an attestation candidate.

### Explicitly Unsupported
- Incoming payments, peer credits, and top-ups (`amount > 0`).
- Merchant purchases and POS card transactions (`mcc != 4829` or retail purchases).
- ATM cash withdrawals and cash-point operations.
- Utility bill payments, mobile top-ups, and charitable contributions.
- Active authorization holds (`hold === true`) or pending transactions.
- Non-UAH international or cross-currency transfers.

## Semantics

- **Payer**: Identified by the authenticated account's Ukrainian IBAN (`account.iban`) with scheme `ua-iban`, or internal account ID (`account.id`) with scheme `monobank-account-id`. Masked identifiers containing `*` or `•` are rejected.
- **Payee**: Identified by the recipient's IBAN (`counterparty.iban`) with scheme `ua-iban` or `iban`, or account number (`counterparty.accountNumber`). Masked card suffixes (e.g. `*1234`) and display names alone are insufficient for unique counterparty identification.
- **Amount**: Monobank's official personal API reports transaction amounts as integer minor units (kopiyky, where -10000 = -100.00 UAH) or positive decimal strings. Outgoing debits are negative in the API or marked as debit. Parsed into BigInt minor units (exponent 2).
- **Currency**: Must be explicitly `UAH` or ISO 4217 numeric code `980`. Any conflicting currency is rejected.
- **Status**: Completed transactions are settled with no active hold (`hold === false` or `status === "completed"`). Active holds or non-final states fail closed to `insufficient_evidence`.
- **Time**: Parsed from `row.timeIso` in UTC ISO-8601 format (`YYYY-MM-DDTHH:mm:ssZ`) or converted from Unix epoch timestamp `row.time`.
- **Transaction ID**: Scoped to `row.id` within the `transactions` array. Must match exactly one row in the input envelope. Memos and free-form comment text are untrusted.

## Local acquisition

1. Retrieve a personal API token from your authorized Monobank developer portal (`api.monobank.ua`).
2. Make a read-only GET request to `/personal/statement/{account}/{from}/{to}` locally. Never post the token or raw responses to GitHub.
3. Save the JSON statement payload containing `account` and `transactions` into local memory.
4. Execute the adapter locally against the captured transaction ID using `npm run try:bank` or unit tests.
5. Submit only synthetic or sanitized fixtures and a privacy-safe live report adhering to repository privacy rules.
