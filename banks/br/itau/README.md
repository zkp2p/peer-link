# Itau Brazil — experimental

Scope: Itaú Brazil mobile-app completed outgoing BRL Pix receipt data. The caller supplies a captured response and explicitly selects one receipt by its Pix end-to-end (E2E) ID when present, otherwise by its receipt-local ID. `interpretItauBrazil` is a pure observation parser; `matchPayment` performs exact claim matching.

## Semantics

- Payer: `receipt.payer.accountId` is the full Itaú sending-account reference. It is emitted with that provenance and is not inferred from a name. Empty or masked values are insufficient.
- Payee: `receipt.recipient.pixKey.value`, paired with the declared `PHONE`, `EMAIL`, `CPF`, `CNPJ`, or `RANDOM` key type. The name is display-only and ignored. Empty, masked, or malformed keys are insufficient.
- Amount: `receipt.amount` is a positive pt-BR display string in BRL major units. Dots group thousands and a comma introduces one or two decimal digits. Conversion uses integer arithmetic to BRL minor units (centavos, exponent 2), so `R$ 1.299,9` becomes `129990` without floating-point rounding.
- Currency: `receipt.currency` must explicitly be `BRL`; a missing or conflicting value abstains.
- Status: only the exact bank-reported value `CONCLUIDA` is accepted. Processing, scheduled, failed, reversed, cancelled, and unknown values abstain. This is sender-bank status, not proof of recipient credit or irreversible settlement.
- Time: `receipt.completedAt` records completion in ISO form with the explicit `-03:00` offset used by this scoped `America/Sao_Paulo` surface. It is validated and emitted as the equivalent UTC instant. Evidence with a missing offset or another offset abstains; future daylight-saving behavior would require a versioned adapter update.
- ID: when `receipt.endToEndId` is present, it is the selected and emitted transaction ID. When Itaú omits it, the explicitly selected `receipt.id` is emitted and the limitation says the E2E ID was absent. No identifier is invented. Selection is capture-local and duplicates abstain.

Only the mobile-app receipt shape and completed outgoing Pix are supported. Extrato rows without full receipt identity, incoming or scheduled Pix, other transfer types, authenticated-source claims, and recipient-credit claims are unsupported. Missing or ambiguous facts return `insufficient_evidence`. Memo and display-name text is untrusted and never affects interpretation.

## Local acquisition

1. The authorized account owner signs into the Itaú mobile app normally and completes MFA themselves.
2. Open an existing completed outgoing Pix and its receipt/detail view. Do not create, resend, edit, or cancel a payment.
3. Using the owner's local inspection workflow, save only the response body that populated that receipt under `.local/itau-response.json`. Never save or publish cookies, headers, credentials, screenshots, a HAR, or unrelated transactions.
4. First inspect structure without values with `npm run try:bank -- --shape .local/itau-response.json`. Then run `npm run try:bank -- br/itau .local/itau-response.json <transactionId>` using the E2E ID, or the local receipt ID only if the receipt omits E2E.
5. Compare the redacted output with the UI. Delete the local capture after producing a privacy-safe report bound to the exact adapter and harness commits. A live report must be supplied by an authorized account owner and is intentionally not fabricated here.

## Validation

The synthetic fixtures independently derive expected centavos, UTC timestamps, identifiers, provenance, status, and E2E/local-ID behavior from invented records. Tests cover determinism, all five Pix key types, exact pt-BR precision, wrong-party and claim mismatches, amount/currency mismatch, nonfinal and unknown statuses, absent identifiers, malformed input, duplicate selection, and hostile memo/display text. Fixtures and tests are not live evidence and do not establish input authenticity.
