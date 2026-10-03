# Vietcombank — experimental

## Scope

Vietcombank Digibank (`VCB Digibank`) online banking history and transaction movement detail payloads.
The adapter covers exactly one payment type: **completed outgoing domestic VND transfers** (including internal Vietcombank transfers and NAPAS 24/7 fast interbank transfers to domestic commercial banks).

The adapter takes a JSON statement envelope containing the payer's account metadata and a list of transaction movements, together with the explicit transaction reference (`refNo` / `transactionId`).

## Semantics

- **Payer**: Identified by `account.accountNo` or `account.accountNumber` (10-13 digits, scheme `vn-vietcombank-account`). Masked identifiers containing `*` or `•` are rejected.
- **Payee**: Identified by `counterparty.accountNumber` or `beneficiary.accountNo` (domestic bank account or NAPAS card number, scheme `vn-account-number`). Must be fully unmasked.
- **Amount**: Vietnamese Dong (VND), ISO 4217 exponent `0`. As VND has no minor unit in circulation, `amountMinor` equals the whole VND integer amount (e.g. `500000` VND is recorded as `500000`). Debit movements are indicated by negative amounts or `direction: "debit"`.
- **Currency**: Must be `VND` (or numeric code `704`). Non-VND movements (e.g. USD, EUR) are rejected with `insufficient_evidence`.
- **Status**: Terminal settlement statuses accepted: `completed`, `Thành công`, `SUCCESS`, `settled`. Pending, processing, or failed movements fail closed.
- **Time**: Formatted as an explicit ISO 8601 UTC timestamp (`timeIso` or UTC converted from bank booking timestamp).
- **ID**: Selected transaction identifier matching `row.id` or `row.refNo`. Description memos and customer notes are untrusted and cannot alter payment semantics.

Unsupported operations:
- Incoming payments and deposits (`tiền vào` / `credit`)
- Merchant QR code purchases and VNPAY-QR payments
- Utility bills, telecommunications, and public service payments
- Cash withdrawals and ATM operations
- Credit card purchases and POS debits
- Pending authorizations and unsettled movements
- Non-VND foreign exchange transfers

## Local acquisition

1. The account owner signs in normally (including MFA/Smart OTP) to Vietcombank VCB Digibank (`https://vcbdigibank.vietcombank.com.vn/`) in their own browser.
2. Navigate to Account Details > Transaction History (`Thông tin tài khoản > Lịch sử giao dịch`) and select an existing completed outgoing domestic transfer. Do not initiate new payments.
3. In browser Developer Tools (Network tab), locate the statement query response (e.g. `getHistTransactions`) and copy the JSON response. Save it locally under `.local/vietcombank-statement.json`.
4. Run `npm run try:bank -- vn/vietcombank .local/vietcombank-statement.json <transactionId>` and compare the redacted summary with the official transaction receipt. Never commit raw bank files to Git.

## Validation

- Tested with synthetic completed and pending fixtures reflecting Vietcombank Digibank payload structures.
- Negative test coverage verifies rejection of amount discrepancies, non-VND currencies, unsupported rails (ATM, QR, utility bills, card payments, incoming credits), masked identifiers, duplicate transaction entries, and prompt injection attempts in memos.
