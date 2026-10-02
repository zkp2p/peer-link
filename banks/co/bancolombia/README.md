# Bancolombia — experimental

## Scope

- Bank surface: Bancolombia web banking movements (`web-movimientos`).
- Payment type: Outgoing domestic COP transfers (`domesticTransfer`, `transferencia_bancolombia`, `transfiya`, `transferencia_fondos`, `p2p_transfer`).
- Target currency: Colombian Peso (`COP`, ISO 4217, exponent 0: whole Pesos as reported without minor units).
- Envelope: JSON payload containing an `account` object and a `transactions` array.
- Selection: Explicit transaction `id` string passed alongside the payload.

## Semantics

- **Payer**: `account.accountNumber`, `account.phone`, or `account.id`. 10-11 digit bank accounts are typed as `co-bancolombia-account`; 10-digit mobile numbers (`3...`) are typed as `co-phone-number`. Masked values containing `*` or `•` are rejected.
- **Payee**: `counterparty.accountNumber`, `counterparty.phone`, or `counterparty.id`. 10-11 digit bank accounts are typed as `co-bancolombia-account`; 10-digit mobile numbers are typed as `co-phone-number`. Masked values are rejected.
- **Amount**: Integer string in major COP units (e.g. `"150000"` or `"150000.00"`), parsed losslessly with `BigInt` scaling to whole Pesos (`150000`, `currencyExponent: 0`). Fractional cents (>0) are rejected.
- **Currency**: Must strictly equal `"COP"`.
- **Status**: Allowed terminal completion statuses: `"completed"`, `"EXITOSA"`, `"APROBADA"`, `"EJECUTADA"`, `"SUCCESS"`. All pending (`"pending"`, `"PENDIENTE"`, `"EN_PROCESO"`, `"EN_TRAMITE"`) or failed statuses abstain (`insufficient_evidence`).
- **Time**: `bookedAt` must be an explicit UTC ISO 8601 string ending in `Z` (e.g. `"2026-06-18T15:45:00Z"`).
- **ID**: Transaction identifier local to Bancolombia records. Untrusted description and memo strings are ignored.

### Unsupported Transactions & Out-of-Scope
- Service and utility bill payments (*Pago de Facturas y Servicios*).
- Credit card bill payments and credit advances.
- Merchant payments and QR code purchases.
- Cash withdrawals and ATM transactions.
- Foreign currency operations (USD transactions or currency conversions).
- Incoming credits and deposits.
- Recipient-credit confirmation and cryptographic source authentication.

## Local Acquisition

1. The authorized Bancolombia account owner signs in normally on Sucursal Virtual Personas (`bancolombia.com`).
2. Navigate to **Movimientos** or **Transferencias**. Locate an existing outgoing domestic transfer. Do not initiate new payments.
3. Open browser Developer Tools (**Network** tab, filter by Fetch/XHR), refresh or inspect the movement list response.
4. Save the response envelope locally under `.local/bancolombia-movement.json`.
5. Run:
   ```bash
   npm run try:bank -- co/bancolombia .local/bancolombia-movement.json <transactionId>
   ```
   Compare the redacted summary against the Bancolombia web interface. Publish only the verification report, never raw credentials or unredacted personal account numbers.

## Validation

- Tested with synthetic completed fixture (`banks/co/bancolombia/fixtures/completed.synthetic.json`) and pending fixture (`banks/co/bancolombia/fixtures/pending.synthetic.json`).
- Exhaustive negative tests in `transformer.test.ts` covering:
  * Non-zero fractional amounts, negative amounts, zero amounts, and non-numeric values.
  * Currency mismatch and missing currency.
  * Status variations (completed variants, pending variants, rejected/failed).
  * Utility bill payment, credit card, and merchant QR exclusion and abstention.
  * Missing or masked payer and recipient accounts.
  * Non-debit and non-domestic operations.
  * Invalid UTC timestamps and date formatting anomalies.
  * Integration testing against `matchPayment`.
