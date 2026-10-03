# Vietcombank (VN) — Peer Link Adapter

## Scope

- **Bank:** Vietcombank — Ngân hàng TMCP Ngoại Thương Việt Nam
- **Surface:** VCB Digibank mobile app, transaction detail screen
- **Payment type:** Outgoing intra-bank VND transfer (Vietcombank → Vietcombank)
- **Currency:** VND (ISO 4217, exponent 0 — no minor unit in common use)
- **Direction:** Outgoing only

## Semantics

| Fact | Source field | Notes |
|------|-------------|-------|
| Payer (A) | `senderAccount` | Full account number, 6–20 digits |
| Payee (B) | `recipient.accountNumber` | Full account number |
| Amount | `amount` | Integer VND (whole đồng, no decimals) |
| Currency | Implicit (VND) | Optional `currency` field checked for conflicts |
| Status | `status` | `"success"` or `"thành công"` = completed |
| Time | `timestamp` | VCB Digibank format or ISO-8601; Vietnamese timestamps assumed ICT (UTC+7) |
| ID | `transactionId` | 9–15 digit numeric string (mã giao dịch) |

## Local Acquisition

Sign in to VCB Digibank mobile app → open a completed intra-bank transfer → capture the transaction detail. The raw API response or the screen's structured data is saved locally (never committed). The adapter expects a normalized JSON object with the fields listed above.

## Validation

Run from the repo root:

```sh
npx vitest run banks/vn/vietcombank/transformer.test.ts
```

Covers: valid transfer, missing/mismatched transaction ID, non-object input, non-success status, unsupported transfer type (NAPAS), zero/negative amounts, non-integer VND, currency conflicts, invalid timestamps, missing recipient, deterministic output.

## Limitations

- Only intra-bank (Vietcombank → Vietcombank) transfers
- No NAPAS 24/7 interbank support
- No incoming transfers
- Parser output does not constitute cryptographic proof of payment
- VND has no minor unit; all amounts are whole đồng
