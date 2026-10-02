# BBVA Mexico — experimental

## Scope

- Bank surface: BBVA Mexico web banking movements (`web-movimientos`).
- Payment type: Outgoing domestic MXN SPEI transfers (`domesticTransfer`, `speiTransfer`, `transferencia_spei`, `spei`, `p2p_transfer`).
- Target currency: Mexican Peso (`MXN`, ISO 4217, exponent 2: 1 MXN = 100 centavos).
- Envelope: JSON payload containing an `account` object and a `transactions` array.
- Selection: Explicit transaction `id` string passed alongside the payload.

## Semantics

- **Payer**: `account.clabe`, `account.accountNumber`, `account.phone`, or `account.id`. 18-digit CLABEs are typed as `mx-clabe`; 16-digit cards are typed as `mx-card`; 10-digit mobile numbers are typed as `mx-phone-number`. Masked values containing `*` or `•` are rejected.
- **Payee**: `counterparty.clabe`, `counterparty.accountNumber`, `counterparty.card`, `counterparty.phone`, or `counterparty.id`. 18-digit CLABEs are typed as `mx-clabe`; 16-digit cards are typed as `mx-card`; 10-digit mobile numbers are typed as `mx-phone-number`. Masked values are rejected.
- **Amount**: Decimal string in major MXN units (e.g. `"850.50"`), parsed losslessly with `BigInt` scaling to minor units (centavos, `85050`).
- **Currency**: Must strictly equal `"MXN"`.
- **Status**: Allowed terminal completion statuses: `"completed"`, `"EXITOSA"`, `"LIQUIDADA"`, `"APROBADA"`, `"EJECUTADA"`, `"SUCCESS"`. All pending (`"pending"`, `"PENDIENTE"`, `"EN_PROCESO"`, `"EN_TRAMITE"`) or failed statuses abstain (`insufficient_evidence`).
- **Time**: `bookedAt` must be an explicit UTC ISO 8601 string ending in `Z` (e.g. `"2026-07-22T17:30:00Z"`).
- **ID**: Transaction identifier local to BBVA Mexico records. Untrusted description and memo strings are ignored.

### Unsupported Transactions & Out-of-Scope
- Banxico CEP lookup (Comprobante Electrónico de Pago is a separate Banxico clearing surface).
- Service and utility bill payments (*Pago de Servicios*).
- Credit card bill payments and credit advances.
- Merchant payments and QR code purchases.
- Cash withdrawals and ATM transactions.
- Foreign currency operations (USD transactions or currency conversions).
- Incoming credits and deposits.
- Recipient-credit confirmation and cryptographic source authentication.

## Local Acquisition

1. The authorized BBVA Mexico account owner signs in normally on `bbva.mx`.
2. Navigate to **Consultas** > **Movimientos** or **Transferencias SPEI**. Locate an existing outgoing domestic SPEI transfer. Do not initiate new payments.
3. Open browser Developer Tools (**Network** tab, filter by Fetch/XHR), refresh or inspect the movement list response.
4. Save the response envelope locally under `.local/bbva-movement.json`.
5. Run:
   ```bash
   npm run try:bank -- mx/bbva-mexico .local/bbva-movement.json <transactionId>
   ```
   Compare the redacted summary against the BBVA Mexico web interface. Publish only the verification report, never raw credentials or unredacted personal account numbers.

## Validation

- Tested with synthetic completed fixture (`banks/mx/bbva-mexico/fixtures/completed.synthetic.json`) and pending fixture (`banks/mx/bbva-mexico/fixtures/pending.synthetic.json`).
- Exhaustive negative tests in `transformer.test.ts` covering:
  * Amount precision (>2 decimals), negative amounts, zero amounts, and non-numeric values.
  * Currency mismatch and missing currency.
  * Status variations (completed variants, pending variants, rejected/failed).
  * Utility bill payment, credit card, and merchant QR exclusion and abstention.
  * Missing or masked payer and recipient accounts.
  * Non-debit and non-SPEI operations.
  * Invalid UTC timestamps and date formatting anomalies.
  * Integration testing against `matchPayment`.
