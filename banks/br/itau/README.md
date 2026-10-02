# Itau Brazil — experimental

## Scope

Interprets completed outgoing domestic Pix transfers denominated in Brazilian Reais (BRL) from the Itaú Brazil online banking extrato surface (`web-extrato-pix`).

The adapter receives a structured JSON document representing the authenticated statement movements and an explicit `transactionId`. It selects exactly that transaction and produces an attestation candidate.

### Explicitly Unsupported
- TED (Transferência Eletrônica Disponível) and DOC transfers.
- Boleto bancário and concessionária utility bill payments (`boleto` / `convenio`).
- Debit and credit card transactions (`compra com cartao`).
- ATM cash withdrawals and counter operations (`saque`).
- Incoming Pix credits, refunds, and third-party deposits.
- Scheduled, pending, in-analysis, or canceled Pix transfers.

## Semantics

- **Payer**: Identified by the authenticated Itaú account's agency and account numbers (`account.agency` + `account.accountNumber`) with scheme `br-itau-agency-account`, or CPF (`account.cpf`) with scheme `br-cpf`, falling back to `account.id`. Masked identifiers containing `*` or `•` are rejected.
- **Payee**: Identified by the counterparty's Pix key (`counterparty.pixKey`) with scheme `pix-key` (or typed as `br-pix-phone`, `br-pix-email`, `br-pix-cpf`, `br-pix-random`), or agency and account (`counterparty.agency` + `counterparty.accountNumber`) with scheme `br-agency-account`, or `counterparty.id`. Masked values are rejected.
- **Amount**: Parsed from a decimal string (`row.amount`) into BigInt minor units (centavos, exponent 2). Floating-point arithmetic is never used. Negative numbers, zero, or amounts with more than 2 decimal digits fail closed.
- **Currency**: Must be explicitly `BRL` (ISO 4217, minor units exponent 2). Any missing or differing currency is rejected.
- **Status**: Accepts bank-reported final statuses (`completed`, `LIQUIDADA`, `EFETIVADA`, `SUCCESS`, `CONCLUIDA`, `REALIZADA`). Non-final statuses (`PENDENTE`, `EM_ANALISE`, `EM_PROCESSAMENTO`, `PROCESSING`, `AGENDADA`) fail closed to `insufficient_evidence`.
- **Time**: Parsed from `row.bookedAt` in UTC ISO-8601 format (`YYYY-MM-DDTHH:mm:ssZ` or with microseconds). Calendar day validity is strictly verified against real UTC dates.
- **Transaction ID**: Scoped to `row.id` (or Banco Central standard end-to-end ID `row.endToEndId` when present) within the `transactions` array. Must match exactly one row in the input envelope. Memos and free-form narrative text are untrusted.

## Local acquisition

1. Sign into your authorized Itaú Brazil online banking account (`itau.com.br`) in a modern browser with standard login/iToken authentication.
2. Navigate to "Extrato" -> "Extrato de Lançamentos" and locate an existing completed outgoing Pix transfer. Do not initiate new payments.
3. Open browser developer tools (Network tab) or use an authorized browser inspection tool to view the JSON extrato response.
4. Extract the JSON payload containing `account` and `transactions` into local memory. Do not copy cookies, session tokens, or authorization headers into fixtures or commits.
5. Execute the adapter locally against the captured transaction ID using `npm run try:bank` or unit tests.
6. Submit only synthetic or sanitized fixtures and a privacy-safe live report adhering to repository privacy rules.
