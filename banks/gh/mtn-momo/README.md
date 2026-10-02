# MTN MoMo Ghana — experimental

## Scope

- Service surface: MTN MoMo mobile application and statement records (`mobile-app-statement`).
- Payment type: Outgoing domestic MoMo-to-MoMo peer transfers (`domesticTransfer`, `momoTransfer`, `momo_to_momo`, `p2p_transfer`).
- Target currency: Ghanaian Cedi (`GHS`, ISO 4217, exponent 2: 1 GHS = 100 pesewas).
- Envelope: JSON payload containing an `account` object and a `transactions` array.
- Selection: Explicit transaction `id` string passed alongside the payload.

## Semantics

- **Payer**: `account.phone`, `account.accountNumber`, or `account.id`. Ghanaian phone numbers (`+233...`, `233...`, `0...`) are typed as `gh-phone-number`; other wallet references are typed as `momo-wallet-id`. Masked values containing `*` or `•` are rejected.
- **Payee**: `counterparty.phone`, `counterparty.accountNumber`, or `counterparty.id`. Ghanaian phone numbers are typed as `gh-phone-number`; fallback identifiers are typed as `gh-recipient-id`. Masked values are rejected.
- **Amount**: Decimal string in major GHS units (e.g. `"150.50"`), parsed losslessly with `BigInt` scaling to minor units (pesewas, `15050`).
- **Currency**: Must strictly equal `"GHS"`.
- **Status**: Allowed terminal completion statuses: `"completed"`, `"SUCCESS"`, `"SUCCESSFUL"`, `"DELIVERED"`. All pending (`"pending"`, `"PENDING"`, `"IN_PROGRESS"`, `"PROCESSING"`) or failed statuses abstain (`insufficient_evidence`).
- **Time**: `bookedAt` must be an explicit UTC ISO 8601 string ending in `Z` (e.g. `"2026-04-10T11:20:00Z"`).
- **ID**: Transaction identifier local to MTN MoMo records. Untrusted description and memo strings are ignored.

### Unsupported Transactions & Out-of-Scope
- Merchant payments and "Buy Goods" / "Pay Merchant" transactions.
- Cash-out and agent withdrawal operations.
- Airtime and data bundle top-ups.
- Utility and bill payments.
- Bank transfers (Bank to Wallet / Wallet to Bank).
- Incoming credits and deposits.
- Unauthenticated SMS parsing (SMS messages by themselves lack origin cryptographic authenticity).
- Recipient-credit confirmation and cryptographic source authentication.

## Local Acquisition

1. The authorized MTN MoMo account owner signs in normally on the MTN MoMo app or web portal.
2. Navigate to **Transaction History** or **Statements**. Locate an existing outgoing MoMo-to-MoMo peer transfer. Do not initiate new payments.
3. Export or inspect the transaction statement payload and save it locally under `.local/mtn-momo-statement.json`.
4. Run:
   ```bash
   npm run try:bank -- gh/mtn-momo .local/mtn-momo-statement.json <transactionId>
   ```
   Compare the redacted summary against the MTN MoMo application record. Publish only the verification report, never raw credentials or unredacted personal account numbers.

## Validation

- Tested with synthetic completed fixture (`banks/gh/mtn-momo/fixtures/completed.synthetic.json`) and pending fixture (`banks/gh/mtn-momo/fixtures/pending.synthetic.json`).
- Exhaustive negative tests in `transformer.test.ts` covering:
  * Amount precision (>2 decimals), negative amounts, zero amounts, and non-numeric values.
  * Currency mismatch and missing currency.
  * Status variations (completed variants, pending variants, rejected/failed).
  * Merchant payment, cash-out, airtime, and utility payment exclusion and abstention.
  * Missing or masked payer and recipient phone numbers.
  * Non-debit and non-peer-transfer operations.
  * Invalid UTC timestamps and date formatting anomalies.
  * Integration testing against `matchPayment`.
