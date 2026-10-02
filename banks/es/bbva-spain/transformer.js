/**
 * Pure, read-only BBVA Spain transaction interpretation. No login, network, clock, randomness or logging.
 * Interprets outgoing domestic and SEPA EUR credit transfers from BBVA Spain online movements.
 * @param {unknown} input The response envelope from BBVA Spain online movements.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretBBVASpain(input, transactionId) {
  const CURRENCY = "EUR";
  const EXPONENT = 2;

  const fail = (/** @type {string} */ reason) =>
    /** @type {const} */ ({ outcome: "insufficient_evidence", reason });

  const object = (/** @type {unknown} */ v) =>
    v !== null && typeof v === "object" && !Array.isArray(v)
      ? /** @type {Record<string, unknown>} */ (v)
      : null;

  const text = (/** @type {unknown} */ v) => typeof v === "string" && v.trim().length > 0;

  const root = object(input);
  const account = object(root?.account);
  if (!root || !account || !Array.isArray(root.transactions)) {
    return fail("Expected account and transactions");
  }

  if (!text(transactionId)) {
    return fail("A transaction ID is required");
  }

  const rows = root.transactions.filter((row) => object(row)?.id === transactionId);
  if (rows.length !== 1) {
    return fail("Selected transaction must occur exactly once");
  }

  const row = /** @type {Record<string, unknown>} */ (rows[0]);

  // Explicit abstention for Bizum, card purchases, ATM withdrawals, and direct debits
  const rawType = typeof row.type === "string" ? row.type : "";
  const rawDescription = typeof row.description === "string" ? row.description : "";
  const typeLower = rawType.toLowerCase();
  const descLower = rawDescription.toLowerCase();

  if (typeLower.includes("bizum") || descLower.includes("bizum")) {
    return { outcome: "unsupported", reason: "Bizum transfers are outside this adapter scope" };
  }

  if (
    typeLower.includes("tarjeta") ||
    descLower.includes("tarjeta") ||
    typeLower.includes("card") ||
    descLower.includes("card") ||
    typeLower.includes("pos") ||
    descLower.includes("pos")
  ) {
    return { outcome: "unsupported", reason: "Card purchases and POS debits are outside scope" };
  }

  if (
    typeLower.includes("cajero") ||
    descLower.includes("cajero") ||
    typeLower.includes("atm") ||
    descLower.includes("atm")
  ) {
    return { outcome: "unsupported", reason: "ATM cash withdrawals are outside scope" };
  }

  if (
    typeLower.includes("recibo") ||
    descLower.includes("recibo") ||
    typeLower.includes("adeudo") ||
    descLower.includes("adeudo") ||
    typeLower.includes("impuesto") ||
    descLower.includes("impuesto")
  ) {
    return { outcome: "unsupported", reason: "Direct debits and bill payments are outside scope" };
  }

  // Direction filter: only outgoing debit transactions
  if (row.direction !== "debit") {
    return { outcome: "unsupported", reason: "Only outgoing debit movements are supported" };
  }

  // Supported transaction types
  const supportedTypes = new Set([
    "domesticTransfer",
    "sepaTransfer",
    "sepaCreditTransfer",
    "transferencia_sepa",
    "transferencia_ordinaria",
    "transferencia_inmediata",
    "sepa_instant",
    "sepa_standard",
    "transfer",
  ]);

  if (!supportedTypes.has(rawType)) {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic and SEPA transfers are supported",
    };
  }

  // Terminal completed status verification
  const finalStatuses = new Set([
    "completed",
    "LIQUIDADA",
    "EJECUTADA",
    "SUCCESS",
    "REALIZADA",
    "EMITIDA",
  ]);

  const rawStatus = typeof row.status === "string" ? row.status : "";
  if (!finalStatuses.has(rawStatus)) {
    return fail("Transaction is not bank-reported completed");
  }

  // Currency validation
  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency");
  }

  // Amount parsing
  const amountMatch =
    typeof row.amount === "string" ? /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount) : null;
  const fraction = amountMatch?.[2] ?? "";
  if (!amountMatch || fraction.length > EXPONENT) {
    return fail("Amount must be a decimal string within currency precision");
  }

  const minor =
    BigInt(amountMatch[1]) * 10n ** BigInt(EXPONENT) +
    BigInt(fraction.padEnd(EXPONENT, "0") || "0");
  if (minor <= 0n) {
    return fail("Amount must be positive");
  }

  // Booked timestamp validation
  if (
    typeof row.bookedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.bookedAt)
  ) {
    return fail("Expected an explicit UTC timestamp");
  }

  const timeMs = Date.parse(row.bookedAt);
  if (
    !Number.isFinite(timeMs) ||
    new Date(timeMs).toISOString().slice(0, 19) !== row.bookedAt.slice(0, 19)
  ) {
    return fail("Invalid timestamp");
  }

  // Payer account identification
  const isPayerIban = typeof account.iban === "string";
  const isPayerAccount = typeof account.accountNumber === "string";
  const payerRaw = isPayerIban ? account.iban : isPayerAccount ? account.accountNumber : account.id;

  if (!text(payerRaw)) {
    return fail("Payer account identifier is missing");
  }

  const payerStr = /** @type {string} */ (payerRaw).trim();
  if (payerStr.includes("*") || payerStr.includes("•")) {
    return fail("Masked payer account identifier is insufficient");
  }

  const payerClean = payerStr.replace(/[-\s]/g, "");
  const isPayerEsIban = /^ES\d{22}$/i.test(payerClean);
  const isPayerGenericIban = /^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/i.test(payerClean);
  const isPayerAccountNumber = /^\d{10,20}$/.test(payerClean);

  const payerId =
    isPayerEsIban || isPayerGenericIban || isPayerAccountNumber ? payerClean : payerStr;
  const payerScheme = isPayerEsIban
    ? "es-iban"
    : isPayerGenericIban
      ? "iban"
      : isPayerAccountNumber
        ? "es-account-number"
        : "bbva-account-id";

  const payerProvenance = isPayerIban
    ? "account.iban"
    : isPayerAccount
      ? "account.accountNumber"
      : "account.id";

  // Payee counterparty identification
  const counterparty = object(row.counterparty);
  const isPayeeIban = typeof counterparty?.iban === "string";
  const isPayeeAccount = typeof counterparty?.accountNumber === "string";
  const payeeRaw = isPayeeIban
    ? counterparty.iban
    : isPayeeAccount
      ? counterparty.accountNumber
      : counterparty?.id;

  if (!text(payeeRaw)) {
    return fail("Full recipient account or IBAN identifier is required");
  }

  const payeeStr = /** @type {string} */ (payeeRaw).trim();
  if (payeeStr.includes("*") || payeeStr.includes("•")) {
    return fail("Masked recipient account identifier is insufficient");
  }

  const payeeClean = payeeStr.replace(/[-\s]/g, "");
  const isPayeeEsIban = /^ES\d{22}$/i.test(payeeClean);
  const isPayeeGenericIban = /^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/i.test(payeeClean);
  const isPayeeAccountNumber = /^\d{10,20}$/.test(payeeClean);

  const payeeId =
    isPayeeEsIban || isPayeeGenericIban || isPayeeAccountNumber ? payeeClean : payeeStr;
  const payeeScheme = isPayeeEsIban
    ? "es-iban"
    : isPayeeGenericIban
      ? "iban"
      : isPayeeAccountNumber
        ? "es-account-number"
        : "counterparty-id";

  const payeeProvenance = isPayeeIban
    ? "transaction.counterparty.iban"
    : isPayeeAccount
      ? "transaction.counterparty.accountNumber"
      : "transaction.counterparty.id";

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "es/bbva-spain",
      transactionId,
      payer: {
        id: payerId,
        scheme: payerScheme,
        provenance: payerProvenance,
      },
      payee: {
        id: payeeId,
        scheme: payeeScheme,
        provenance: payeeProvenance,
      },
      amountMinor: minor.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: "completed",
      timestamp: row.bookedAt,
      timestampMeaning: "bookedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not cryptographically proven by this parser.",
        "Bank-reported completed status does not guarantee irreversible recipient settlement.",
        "Payer and payee identities are bank and IBAN references, not verified legal persons.",
        "Bizum transfers, card debits, ATM withdrawals and direct debits are excluded.",
        "Transaction ID is scoped to this movements statement.",
      ],
    },
  };
}
