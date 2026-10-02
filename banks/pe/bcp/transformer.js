/**
 * Pure, read-only Banco de Crédito del Perú (BCP) interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope loaded from BCP web banking movements.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretBcp(input, transactionId) {
  const CURRENCY = "PEN";
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

  // Explicitly abstain on Yape payments per issue scope
  const isYape =
    row.type === "yape" ||
    (typeof row.productType === "string" && row.productType.toLowerCase().includes("yape")) ||
    (typeof row.description === "string" && row.description.toLowerCase().includes("yape"));
  if (isYape) {
    return { outcome: "unsupported", reason: "Yape transfers are out of scope" };
  }

  // Accept only supported outgoing domestic transfer types
  const supportedTypes = [
    "domesticTransfer",
    "transferencia_terceros",
    "transferencia_bcp",
    "transferencia_interbancaria",
  ];
  if (!supportedTypes.includes(/** @type {string} */ (row.type)) || row.direction !== "debit") {
    return { outcome: "unsupported", reason: "Only outgoing domestic transfers are supported" };
  }

  // Final bank-reported completion statuses
  const completedStatuses = ["completed", "EJECUTADA", "TRANSFERIDO", "EXITOSO", "SUCCESS"];
  if (!completedStatuses.includes(/** @type {string} */ (row.status))) {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency");
  }

  // Parse money from decimal string using BigInt scaling (1 PEN = 100 céntimos)
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

  // UTC ISO 8601 booked timestamp validation
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
  const isPayerAccountNumber = typeof account.accountNumber === "string";
  const payerRaw = isPayerAccountNumber ? account.accountNumber : account.id;
  if (!text(payerRaw)) {
    return fail("Payer account identifier is missing");
  }
  const payerStr = /** @type {string} */ (payerRaw).trim();
  if (payerStr.includes("*") || payerStr.includes("•")) {
    return fail("Masked payer account identifier is insufficient");
  }

  const payerClean = isPayerAccountNumber ? payerStr.replace(/[-\s]/g, "") : payerStr;
  const isPayerBcp = /^\d{13,14}$/.test(payerClean);
  const payerScheme = isPayerBcp ? "pe-bcp-account" : "bcp-account-id";
  const payerProvenance = isPayerAccountNumber ? "account.accountNumber" : "account.id";

  // Payee counterparty identification
  const counterparty = object(row.counterparty);
  const payeeRaw =
    typeof counterparty?.accountNumber === "string"
      ? counterparty.accountNumber
      : typeof counterparty?.cci === "string"
        ? counterparty.cci
        : counterparty?.id;

  if (!text(payeeRaw)) {
    return fail("Full recipient account identifier is required");
  }
  const payeeStr = /** @type {string} */ (payeeRaw).trim();
  if (payeeStr.includes("*") || payeeStr.includes("•")) {
    return fail("Masked recipient identifier is insufficient");
  }

  const payeeClean = payeeStr.replace(/[-\s]/g, "");
  let payeeScheme = "pe-account-number";
  if (/^\d{20}$/.test(payeeClean)) {
    payeeScheme = "pe-cci";
  } else if (/^\d{13,14}$/.test(payeeClean)) {
    payeeScheme = "pe-bcp-account";
  } else if (!/^[A-Za-z0-9]{6,34}$/.test(payeeClean)) {
    return fail("Full recipient account identifier is required");
  }

  const payeeProvenance =
    typeof counterparty?.accountNumber === "string"
      ? "transaction.counterparty.accountNumber"
      : typeof counterparty?.cci === "string"
        ? "transaction.counterparty.cci"
        : "transaction.counterparty.id";

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "pe/bcp",
      transactionId,
      payer: {
        id: payerClean,
        scheme: payerScheme,
        provenance: payerProvenance,
      },
      payee: {
        id: payeeClean,
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
        "Input authenticity is not established by this parser.",
        "Completed is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a bank account reference, not a verified legal person.",
        "Transaction ID is local to this bank; no cross-bank deduplication is claimed.",
      ],
    },
  };
}
