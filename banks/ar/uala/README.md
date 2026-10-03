# Uala Argentina

## Scope

1. Single supported bank surface: Uala Argentina mobile application activity and transfer receipt view.
2. Single supported payment type: outgoing domestic ARS transfer via CVU or alias.
3. Every supported record includes an explicit CVU or alias counterparty identifier and terminal transfer execution status.

## Semantics

1. Payer: sending account CVU (22 digits) or alias identifier. Scheme is ar-cvu when 22 digits, ar-alias when alias format, or uala-account-id. Display names are ignored.
2. Payee: destination account CVU (22 digits), CBU (22 digits), or alias identifier. Scheme is ar-cvu, ar-cbu, or ar-alias. Masked values are rejected.
3. Amount: parsed from decimal string or numeric value into minor integer units in centavos with exponent 2. Floating point multiplication is avoided.
4. Currency: ARS ISO 4217 currency with minor exponent 2. Any differing or missing currency causes rejection.
5. Status: bank reported terminal completed status: COMPLETED, APROBADA, EXITOSA, or REALIZADA. Pending, processing, failed, and reversed states abstain.
6. Time: explicit UTC ISO 8601 timestamp ending in Z.
7. Tracking reference: COELSA reference or operation ID is validated when present and included in limitations.
8. Unsupported scopes: incoming credits, card purchases, utility payments, crypto trades, and cash operations.

## Local acquisition

1. The account owner signs in to the authorized Uala Argentina mobile banking session.
2. Navigate to account activity and open the transfer receipt for an existing completed transfer.
3. Inspect the JSON payload or receipt detail via developer inspection proxy and save to .local/uala-response.json.
4. Run npm run try:bank ar/uala .local/uala-response.json <transactionId> to view the redacted summary.
5. Verify that the output matches the mobile receipt and write a live report. Never commit the raw response payload.

## Validation

1. Synthetic fixtures cover completed transfer, pending state, failed state, and unsupported card purchase type.
2. Unit tests verify full branch and line coverage across all error paths and property boundaries.
