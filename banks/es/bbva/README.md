# BBVA Spain (experimental)

## Scope

BBVA Spain web banking or mobile application receipt for completed outgoing domestic EUR SEPA transfers (Transferencias SEPA ordinarias o inmediatas). Input is the JSON transaction payload loaded by the client or account movement detail view, along with an explicit transaction identifier. The pure function interpretBbva resides in transformer.js.

## Semantics

1. Payer: Full Spanish International Bank Account Number (IBAN) formatted as 24 alphanumeric characters starting with ES (for example ES0000000000000000000001). Scheme is iban. Masked values fail closed.
2. Payee: Full recipient SEPA International Bank Account Number (IBAN) formatted as 15 to 34 alphanumeric characters starting with a valid two letter country code. Scheme is iban. Masked values fail closed.
3. Amount: Euro decimal string or numeric value converted to integer minor units (Cents, exponent 2: 1 EUR equals 100 Cents) using BigInt arithmetic without floating point math. Supports period or comma decimal separators. Zero or negative amounts fail closed.
4. Currency: EUR only. Missing or conflicting currency fails closed.
5. Status: Only explicit completed bank reported statuses (COMPLETED, EJECUTADA, REALIZADA, SUCCESS). Pending, processing, or scheduled statuses fail closed.
6. Time: Explicit UTC ISO 8601 string ending with Z. Calendar date validity is enforced.
7. ID: Transaction reference identifier scoped to BBVA Spain. Display names and memos are untrusted data.

Unsupported: Bizum mobile transfers, international SWIFT transfers outside SEPA, card debits, direct debits, currency exchanges, and incoming credits. Missing or ambiguous facts return insufficient_evidence.

## Local acquisition

1. The account owner signs in normally with multi-factor authentication into the official BBVA Spain web banking portal or mobile application.
2. Navigate to Posicion Global, select the euro current account, open Movimientos, and locate an existing completed outgoing SEPA transfer. Do not initiate payments.
3. Inspect the read-only network response or transaction detail JSON payload using browser developer tools.
4. Save the response body to .local/es-bbva-response.json without modifying headers or credentials.
5. Execute npm run try:bank es/bbva .local/es-bbva-response.json <transactionId> to inspect the redacted observation summary.

## Validation

Synthetic fixtures cover completed transfers, pending transfers, failed transfers, and European comma decimal formatting. Unit tests verify exact minor unit conversion, calendar date validation, IBAN normalization, masked identifier rejection, and untrusted memo handling.
