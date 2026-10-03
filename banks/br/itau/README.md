# Itau Brazil — experimental

## Scope

Itaú Brazil mobile application completed outgoing BRL Pix receipt records.
The caller supplies captured receipt data and explicitly selects one transaction by its Central Bank Pix end-to-end ID (E2E ID) when present, or by its receipt-local transaction ID.

## Semantics

- **Payer (A)**: Identified by `receipt.payer.accountId` (Itaú branch and account identifier, scheme `itau-account-id`). Masked values fail closed.
- **Payee (B)**: Sourced from `receipt.recipient.pixKey.value` with its explicit type (`receipt.recipient.pixKey.type`), forming scheme `pix-phone`, `pix-email`, `pix-cpf`, `pix-cnpj`, or `pix-random`. Full unmasked keys are required.
- **Amount**: Represented as a formatted Brazilian Real currency string (`R$ 150,00`) or standard decimal string in BRL. Converted into integer minor units (centavos, exponent 2).
- **Currency**: Verified as `BRL`. ISO 4217 minor unit exponent is 2.
- **Status**: Bank-reported completed status (`CONCLUIDA`). Pending (`EM_PROCESSAMENTO`), scheduled (`AGENDADA`), failed, or reversed states return `insufficient_evidence`.
- **Time**: Sourced from `completedAt` as an ISO-8601 string with explicit offset (e.g. `-03:00` America/Sao_Paulo or UTC `Z`) and normalized to an explicit UTC ISO-8601 timestamp ending in `Z`.
- **ID**: Selected transaction identifier matching the Pix end-to-end ID (`endToEndId`) or receipt-local identifier (`id`).
- **Unsupported**: Incoming Pix transfers, scheduled Pix, credit cards, boleto bancário, TED/DOC wire transfers, and non-BRL currencies remain unsupported. Any ambiguous record fails closed.

## Local acquisition

1. The authorized account owner signs into the Itaú mobile app or web portal in their own authorized session.
2. Navigate to Pix transaction history / comprovante de transferência for an existing completed outgoing Pix.
3. Capture the receipt JSON payload loaded by the application and store it under `.local/itau-response.json` (strictly local, never committed).
4. Run `npm run try:bank -- br/itau .local/itau-response.json <transactionId>` and verify that the redacted summary matches the official Itaú comprovante.

## Validation

Covered by synthetic fixtures with independently derived expected outputs:
- `fixtures/receipt-phone.synthetic.json`: Outgoing Pix completed to a phone key.
- `fixtures/receipt-email.synthetic.json`: Outgoing Pix completed to an email key.
- `fixtures/pending.synthetic.json`: Pending Pix transfer abstaining with insufficient evidence.

Tested via `transformer.test.ts` across positive cases, negative cases (masked identifiers, invalid Pix keys, status variations, currency mismatches, malformed inputs, duplicate selection, prompt injection memos), and attestation candidate conversion.
