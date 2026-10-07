# China Merchants Bank (招商银行) — CNY / CN

Adapter for CNY transfers via the China Merchants Bank personal
internet banking and CMB App transaction-detail surface.

## Scope

- Currency: **CNY** (yuan), two-decimal precision.
- Supported transaction types: **transfer** only.
- Supported surfaces: **app** and **web** transaction-detail views.
- Transfer direction: CMB-to-CMB and interbank are both accepted,
  provided the source surface is an authorized CMB personal channel
  and the bank reports `success`.
- Out of scope: foreign-currency sub-accounts, electronic receipts
  (电子回单) without a matching transfer, other banks, and any
  payment-initiation flows.

## Provenance notes

- Amounts are captured as `amountCents` (yuan × 100, integer) to
  preserve two-decimal precision without floating-point drift.
- The bank-reported `status` field is authoritative; only
  `"success"` is normalized. `"processing"`, `"pending"`,
  `"failed"`, `"cancelled"`, and `"unknown"` all fail closed.
- Timestamps are ISO 8601 UTC strings as recorded on the surface.
  The adapter records `timezone: "Asia/Shanghai"` to reflect the
  source clock origin.
- Counterparty names and account numbers are often partially masked
  on CMB surfaces; a display name is not an identifier.
- Transaction IDs (`transactionId`) are CMB-internal
  (交易流水号). Interbank transfers may carry a processing-stage
  reference before the bank reports final success; only the final
  success record is normalized.
- Memo text (`memo`) is treated as untrusted and is preserved
  verbatim without influencing validation.

## Privacy

- Raw captures stay local. No real banking records, credentials,
  screenshots, or identity documents are committed to Git.
- Fixtures are fully synthetic with justified expected outputs.

## Acceptance

Run:

```sh
npm run check
npm run privacy -- --staged
```

A single privacy-safe live report from the authorized account
owner, bound to the exact adapter and harness commits, completes
the bounty scope.
