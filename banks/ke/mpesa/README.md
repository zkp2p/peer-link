# Safaricom M-Pesa — experimental

## Scope

- Service surface: Safaricom M-Pesa mobile application statement and activity records (`mobile-app-statement`).
- Payment type: Outgoing domestic Send Money person-to-person transfers (`domesticTransfer`, `sendMoney`, `send_money`, `p2p_transfer`).
- Target currency: Kenyan Shilling (`KES`, ISO 4217, exponent 2: 1 KES = 100 cents).
- Envelope: JSON payload containing an `account` object and a `transactions` array.
- Selection: Explicit transaction `id` string passed alongside the payload.

## Semantics

- **Payer**: `account.phone`, `account.accountNumber`, or `account.id`. Kenyan mobile numbers (`+254...`, `254...`, `07...`, `01...`) are typed as `ke-phone-number`; other wallet references are typed as `mpesa-wallet-id`. Masked values containing `*` or `•` are rejected.
- **Payee**: `counterparty.phone`, `counterparty.accountNumber`, or `counterparty.id`. Kenyan mobile numbers are typed as `ke-phone-number`; fallback identifiers are typed as `ke-recipient-id`. Masked values are rejected.
- **Amount**: Decimal string in major KES units (e.g. `"1250.00"`), parsed losslessly with `BigInt` scaling to minor units (cents, `125000`).
- **Currency**: Must strictly equal `"KES"`.
- **Status**: Allowed terminal completion statuses: `"completed"`, `"SUCCESS"`, `"SUCCESSFUL"`, `"COMPLETED"`. All pending (`"pending"`, `"PENDING"`, `"IN_PROGRESS"`, `"PROCESSING"`) or failed statuses abstain (`insufficient_evidence`).
- **Time**: `bookedAt` must be an explicit UTC ISO 8601 string ending in `Z` (e.g. `"2026-05-12T09:15:00Z"`).
- **ID**: Transaction identifier local to Safaricom M-Pesa records. Untrusted description and memo strings are ignored.

### Unsupported Transactions & Out-of-Scope
- Lipa na M-Pesa transactions (Buy Goods / Till numbers).
- Paybill merchant number payments.
- Fuliza overdraft facilities and credit advances.
- Agent cash-out and ATM withdrawals.
- Airtime and mobile data bundle top-ups.
- Bank transfers (Bank to M-Pesa / M-Pesa to Bank).
- Incoming credits and deposits.
- Unauthenticated SMS parsing (raw SMS text messages lack tamper-proof digital signatures).
- Recipient-credit confirmation and cryptographic source authentication.

## Local Acquisition

1. The authorized Safaricom M-Pesa account owner signs in normally on the M-Pesa mobile app or mySafaricom portal.
2. Navigate to **M-Pesa Statement** or **Transaction History**. Locate an existing outgoing Send Money peer-to-person transfer. Do not initiate new payments.
3. Export or inspect the statement JSON payload and save it locally under `.local/mpesa-statement.json`.
4. Run:
   ```bash
   npm run try:bank -- ke/mpesa .local/mpesa-statement.json <transactionId>
   ```
   Compare the redacted summary against the M-Pesa application record. Publish only the verification report, never raw credentials or unredacted personal phone numbers.

## Validation

- Tested with synthetic completed fixture (`banks/ke/mpesa/fixtures/completed.synthetic.json`) and pending fixture (`banks/ke/mpesa/fixtures/pending.synthetic.json`).
- Exhaustive negative tests in `transformer.test.ts` covering:
  * Amount precision (>2 decimals), negative amounts, zero amounts, and non-numeric values.
  * Currency mismatch and missing currency.
  * Status variations (completed variants, pending variants, rejected/failed).
  * Paybill, Buy Goods / Till, Fuliza, and agent withdrawal exclusion and abstention.
  * Missing or masked payer and recipient phone numbers.
  * Non-debit and non-Send-Money operations.
  * Invalid UTC timestamps and date formatting anomalies.
  * Integration testing against `matchPayment`.
