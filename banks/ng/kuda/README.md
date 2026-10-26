# Kuda Bank — experimental

Scope: Kuda Bank web and mobile transaction detail surface for **outgoing domestic NGN bank transfers**. Input is a JSON transaction envelope containing `account` and `transactions` records, plus an explicit transaction ID. The pure function `interpretKuda` in `transformer.js` converts successful transactions into schema version 2 `PaymentObservation` records.

## Semantics

- Payer: `account.accountNumber` identifies the sender's 10-digit NUBAN account number. This is a bank account reference, not a verified legal person identity. Display names are ignored.
- Payee: `transaction.recipient` contains the counterparty 10-digit NUBAN account number and 3-to-6-digit CBN destination bank code (formatted as `<bankCode>:<accountNumber>`). Masked or partial account numbers fail closed.
- Amount: outgoing transfer amount represented as a non-negative decimal string in NGN major units; converted directly to integer minor units (Kobo, 1 NGN = 100 Kobo) without floating-point arithmetic.
- Currency: NGN (Nigerian Naira) with minor unit exponent 2. Non-NGN currencies abstain.
- Status: only `completed`, `successful`, or `sent` statuses are accepted as proof of sender-bank completion. Pending, failed, or reversed states abstain (`insufficient_evidence`).
- Time: explicit ISO 8601 UTC timestamp (`postedAt`) ending in `Z`. Local or ambiguous timestamps are rejected.
- ID: `transactionId` matches the selected transaction's unique ID on the Kuda ledger. Memos, reference strings, and notes are untrusted and do not alter parsed outcomes.

Unsupported: card payments, cash deposits/withdrawals, remittances, bill payments, airtime purchases, and incoming transfers are rejected as `unsupported`. Missing or ambiguous facts return `insufficient_evidence`.

## Local acquisition

1. Sign into your Kuda Bank account through the authorized web or mobile portal using your credentials and multi-factor authentication.
2. Navigate to Transaction History and locate an existing outgoing domestic bank transfer.
3. Inspect the transaction detail response envelope loaded by the application. Save the JSON payload locally under `.local/`.
4. Run the deterministic test harness against your local capture:
   `npm run try:bank -- ng/kuda .local/<capture>.json <transactionId>`
   Compare the resulting redacted summary with the details shown in the bank application.
5. Publish only sanitized or synthetic fixtures with invented values. Never commit or transmit raw tokens, cookies, or real customer data.

## Validation

Synthetic baseline tests in `transformer.test.ts` and `banks/adapter-contract.test.ts` verify:
- Successful interpretation of valid domestic NGN transfers into schema v2 observations.
- Strict rejection of invalid or malformed envelope payloads and duplicate IDs.
- Deterministic BigInt minor unit (Kobo) conversion without floating-point rounding errors.
- Strict validation of 10-digit NUBAN payer/payee accounts and CBN destination bank codes.
- Fail-closed handling for pending, processing, and failed statuses.
- Rejection of unsupported payment categories (cards, incoming credits, cash deposits).
- Resistance to prompt injection and malicious instructions in free-form memo fields.
