# Easypaisa — experimental

Scope: Easypaisa Pakistan transaction receipt and statement records, focusing on **outgoing completed PKR domestic money transfers** (Easypaisa-to-Easypaisa and Raast IBFT). Input is the transaction detail receipt JSON envelope, plus an explicit transaction ID. The pure, synchronous function `interpretEasypaisa` is located in `transformer.js` (typechecked via TypeScript JSDoc).

## Semantics

- **Payer:** Sender mobile account number or account identifier (`sender.accountNumber` or `sender.mobileNumber`). Display names or nicknames alone are ignored to avoid spoofing.
- **Payee:** Recipient mobile account number, CNIC, or Raast identifier (`receiver.accountNumber` or `receiver.mobileNumber`). Masked digits or display names alone are insufficient and cause fail-closed abstention.
- **Amount:** Positive decimal minor units (paisa) parsed with integer `BigInt` fixed-point arithmetic (`amountMinor = major * 100 + paisa`). Floating-point arithmetic is strictly forbidden.
- **Currency:** Strictly `PKR` with ISO 4217 minor exponent `2`. Non-PKR currencies abstain.
- **Status:** Only bank-reported `COMPLETED`, `SUCCESS`, or `PAID` final debit statuses are accepted. Pending transactions (`PENDING`), processing (`IN_PROGRESS`), or failed transfers abstain.
- **Time:** UTC ISO 8601 string (`timestamp` ending in `Z`), reflecting the transaction execution time recorded by Easypaisa.
- **ID:** Scoped explicitly to the Easypaisa transaction ID (`transactionId`). Unverified user memos and remarks are treated as untrusted and excluded from identity logic.

Unsupported: Mobile airtime top-ups (easyload), utility bill payments, ATM cash withdrawals, merchant QR payments, and incoming transfers are unsupported. Missing or ambiguous fields return `insufficient_evidence`.

## Local acquisition

1. The authorized account owner signs in normally with biometric/PIN authentication in the official Easypaisa mobile app.
2. Navigate to Transaction History and locate an existing completed outgoing money transfer receipt. Do not initiate new transfers.
3. Export or inspect the receipt transaction details using authorized local developer inspection tools.
4. Save the response into the Git-ignored `.local/easypaisa-receipt.json` path.
5. Verify the adapter locally:
   `npm run try:bank -- pk/easypaisa .local/easypaisa-receipt.json <transactionId>`
6. Compare the masked summary output against the Easypaisa app receipt to confirm all details match.
7. Publish only synthetic or sanitized fixtures and a live report. Never commit raw network captures, cookies, PINs, or personal identifiable information (PII).

## Validation

Synthetic test fixtures (`completed.synthetic.json` and `pending.synthetic.json`) cover completed outgoing transfers and abstention on pending states. The test suite `transformer.test.ts` exercises 40+ negative and boundary conditions, including non-matching transaction IDs, amount parsing anomalies, currency mismatch, status variants, and tampering resilience.
