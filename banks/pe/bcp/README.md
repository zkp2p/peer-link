# Banco de Crédito del Perú (BCP) — experimental

## Scope

- Bank surface: BCP web banking movements (`web-movimientos`).
- Payment type: Outgoing domestic PEN transfers (`domesticTransfer`, `transferencia_terceros`, `transferencia_bcp`, `transferencia_interbancaria`).
- Target currency: Peruvian Sol (`PEN`, ISO 4217, exponent 2: 1 PEN = 100 céntimos).
- Envelope: JSON payload containing an `account` object and a `transactions` array.
- Selection: Explicit transaction `id` string passed alongside the payload.

## Semantics

- **Payer**: `account.accountNumber` or `account.id`. Dash-separated formatting (`191-XXXXXXXX-X-XX`) is normalized to digits (`pe-bcp-account` or `bcp-account-id`). Masked values containing `*` or `•` are rejected.
- **Payee**: `counterparty.accountNumber`, `counterparty.cci`, or `counterparty.id`. 20-digit CCIs are typed as `pe-cci`; 13-14 digit BCP accounts are typed as `pe-bcp-account`. Masked values are rejected.
- **Amount**: Decimal string in major PEN units (e.g. `"250.75"`), parsed losslessly with `BigInt` scaling to minor units (céntimos, `25075`).
- **Currency**: Must strictly equal `"PEN"`.
- **Status**: Allowed terminal completion statuses: `"completed"`, `"EJECUTADA"`, `"TRANSFERIDO"`, `"EXITOSO"`, `"SUCCESS"`. All pending (`"pending"`, `"EN_PROCESO"`, `"PENDIENTE"`, `"EN_REVISION"`) or failed statuses abstain (`insufficient_evidence`).
- **Time**: `bookedAt` must be an explicit UTC ISO 8601 string ending in `Z` (e.g. `"2026-03-15T14:30:00Z"`).
- **ID**: Transaction identifier local to BCP statement records. Untrusted description and memo strings are ignored.

### Unsupported Transactions & Out-of-Scope
- Yape transfers (`yape` type or descriptions referring to Yape) are explicitly excluded per issue #17 scope.
- Service and utility bill payments (*Pago de Servicios*).
- Credit card bill payments and installment operations.
- Merchant payments and POS card transactions.
- Cash withdrawals and ATM transactions.
- Foreign currency operations (USD transactions or currency conversions).
- Incoming credits and deposits.
- Recipient-credit confirmation and cryptographic source authentication.

## Local Acquisition

1. The authorized BCP account owner signs in normally (with Credimás card number, internet password, and token MFA) on `viabcp.com`.
2. Navigate to **Consultas** > **Movimientos** or **Transferencias**. Locate an existing outgoing domestic transfer. Do not initiate new payments.
3. Open browser Developer Tools (**Network** tab, filter by Fetch/XHR), refresh or inspect the movement list response.
4. Save the response envelope locally under `.local/bcp-movement.json`.
5. Run:
   ```bash
   npm run try:bank -- pe/bcp .local/bcp-movement.json <transactionId>
   ```
   Compare the redacted summary against the BCP web interface. Publish only the verification report, never raw credentials or unredacted personal bank statements.

## Validation

- Tested with synthetic completed fixture (`banks/pe/bcp/fixtures/completed.synthetic.json`) and pending fixture (`banks/pe/bcp/fixtures/pending.synthetic.json`).
- Exhaustive negative tests in `transformer.test.ts` covering:
  * Amount precision (>2 decimals), negative amounts, zero amounts, and non-numeric values.
  * Currency mismatch and missing currency.
  * Status variations (completed variants, pending variants, rejected/failed).
  * Yape transfer explicit exclusion and abstention.
  * Missing or masked payer and recipient accounts.
  * Non-debit and non-domestic operations.
  * Invalid UTC timestamps and date formatting anomalies.
  * Integration testing against `matchPayment`.
