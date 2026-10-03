# BBVA Spain — experimental

## Scope

Interprets completed outgoing domestic and SEPA credit transfers denominated in Euros (EUR) from the BBVA Spain online banking movements surface (`web-movimientos`).

The adapter receives a structured JSON document representing the authenticated movements history and an explicit `transactionId`. It selects exactly that transaction and produces an attestation candidate.

### Explicitly Unsupported
- Bizum payments (`bizum` / `pago_bizum`), which represent a distinct instant mobile rail with phone-based routing.
- Incoming credits, transfers received, and payroll deposits.
- Debit and credit card transactions, POS purchases, and contactless debits (`tarjeta` / `compra_tarjeta`).
- ATM cash withdrawals and branch counter operations (`cajero` / `retiro_cajero`).
- Direct debits, recurring utility bills, and municipal tax levies (`recibo` / `impuestos` / `adeudo_sepa`).
- Pending, scheduled, in-process, or canceled movements.

## Semantics

- **Payer**: Identified by the authenticated account's Spanish IBAN (`account.iban`) with scheme `es-iban`, falling back to internal account number (`account.accountNumber`) with scheme `es-account-number` or `account.id`. Masked identifiers containing `*` or `•` are rejected.
- **Payee**: Identified by the recipient's IBAN (`counterparty.iban`) with scheme `iban`, or account number (`counterparty.accountNumber`). Masked values are rejected.
- **Amount**: Parsed from a decimal string (`row.amount`) into BigInt minor units (euro cents, exponent 2). Floating-point arithmetic is never used. Negative numbers, zero, or amounts with more than 2 decimal digits fail closed.
- **Currency**: Must be explicitly `EUR` (ISO 4217, minor units exponent 2). Any missing or differing currency is rejected.
- **Status**: Accepts bank-reported final statuses (`completed`, `LIQUIDADA`, `EJECUTADA`, `SUCCESS`, `REALIZADA`, `EMITIDA`). Non-final statuses (`PENDIENTE`, `EN_CURSO`, `EN_TRAMITE`, `PROCESSING`, `PROGRAMADA`) fail closed to `insufficient_evidence`.
- **Time**: Parsed from `row.bookedAt` in UTC ISO-8601 format (`YYYY-MM-DDTHH:mm:ssZ` or with microseconds). Calendar day validity is strictly verified against real UTC dates.
- **Transaction ID**: Scoped to `row.id` within the `transactions` array. Must match exactly one row in the input envelope. Memos, concepts, and descriptive narrative text are treated as untrusted and excluded from identifier derivation.

## Local acquisition

1. Sign into your authorized BBVA Spain online banking portal (`bbva.es`) in a modern browser with standard credentials/MFA.
2. Navigate to "Cuentas" -> "Movimientos" and locate an existing completed outgoing domestic or SEPA transfer. Do not initiate new payments.
3. Open the browser developer tools (Network tab) or use an authorized browser inspection tool to view the JSON movement payload.
4. Extract the JSON movements envelope containing `account` and `transactions` fields into local memory. Do not copy cookies, session tokens, or authorization headers into fixtures or commits.
5. Execute the adapter locally against the captured transaction ID using `npm run try:bank` or unit tests.
6. Submit only synthetic or sanitized fixtures and a privacy-safe live report adhering to repository privacy rules.
