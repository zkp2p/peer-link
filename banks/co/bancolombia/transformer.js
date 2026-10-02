/**
 * Pure, read-only Bancolombia interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope loaded from Bancolombia web movements or activity records.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretBancolombia(input, transactionId) {
  const CURRENCY = "COP";
  const EXPONENT = 0;

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

  // Explicitly abstain on utility payments, credit card bills, merchant QR, and cash withdrawals
  const isExcluded =
    row.type === "pago_facturas" ||
    row.type === "credit_card_payment" ||
    row.type === "merchant_qr" ||
    (typeof row.category === "string" &&
      /facturas|servicios|credit[_\s-]?card|tarjeta|qr|comercio|cajero/i.test(row.category)) ||
    (typeof row.description === "string" &&
      /pago de facturas|pago de servicios|tarjeta de credito|compra qr|cajero/i.test(
        row.description,
      ));
  if (isExcluded) {
    return {
      outcome: "unsupported",
      reason: "Service payments, credit card payments, and merchant transactions are out of scope",
    };
  }

  // Accept only supported outgoing domestic transfer types (Bancolombia-to-Bancolombia or Transfiya)
  const supportedTypes = [
    "domesticTransfer",
    "transferencia_bancolombia",
    "transfiya",
    "transferencia_fondos",
    "p2p_transfer",
  ];
  if (!supportedTypes.includes(/** @type {string} */ (row.type)) || row.direction !== "debit") {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic transfers are supported",
    };
  }

  // Final bank-reported completion statuses
  const completedStatuses = ["completed", "EXITOSA", "APROBADA", "EJECUTADA", "SUCCESS"];
  if (!completedStatuses.includes(/** @type {string} */ (row.status))) {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency");
  }

  // Parse money from decimal or integer string using BigInt scaling (COP exponent 0: whole Pesos)
  const amountMatch =
    typeof row.amount === "string" ? /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount) : null;
  if (!amountMatch) {
    return fail("Amount must be a valid integer string within currency precision");
  }

  const fraction = amountMatch[2] ?? "";
  if (fraction.length > 0 && !/^0+$/.test(fraction)) {
    return fail("Amount must be a whole currency string without fractional decimals");
  }

  const minor = BigInt(amountMatch[1]);
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

  // Payer account / phone identification
  const isPayerAccount = typeof account.accountNumber === "string";
  const isPayerPhone = typeof account.phone === "string";
  const payerRaw = isPayerAccount
    ? account.accountNumber
    : isPayerPhone
      ? account.phone
      : account.id;

  if (!text(payerRaw)) {
    return fail("Payer account identifier is missing");
  }
  const payerStr = /** @type {string} */ (payerRaw).trim();
  if (payerStr.includes("*") || payerStr.includes("•")) {
    return fail("Masked payer account identifier is insufficient");
  }

  const payerClean = payerStr.replace(/[-\s]/g, "");
  const isPayerCoAccount = /^\d{10,11}$/.test(payerClean);
  const isPayerCoPhone = /^(?:\+?57)?3\d{9}$/.test(payerClean);
  const payerId = isPayerCoAccount || isPayerCoPhone ? payerClean : payerStr;
  const payerScheme = isPayerCoAccount
    ? "co-bancolombia-account"
    : isPayerCoPhone
      ? "co-phone-number"
      : "bancolombia-account-id";
  const payerProvenance = isPayerAccount
    ? "account.accountNumber"
    : isPayerPhone
      ? "account.phone"
      : "account.id";

  // Payee counterparty identification
  const counterparty = object(row.counterparty);
  const isPayeeAccount = typeof counterparty?.accountNumber === "string";
  const isPayeePhone = typeof counterparty?.phone === "string";
  const payeeRaw = isPayeeAccount
    ? counterparty.accountNumber
    : isPayeePhone
      ? counterparty.phone
      : counterparty?.id;

  if (!text(payeeRaw)) {
    return fail("Full recipient account or phone identifier is required");
  }
  const payeeStr = /** @type {string} */ (payeeRaw).trim();
  if (payeeStr.includes("*") || payeeStr.includes("•")) {
    return fail("Masked recipient identifier is insufficient");
  }

  const payeeClean = payeeStr.replace(/[-\s]/g, "");
  const isPayeeCoAccount = /^\d{10,11}$/.test(payeeClean);
  const isPayeeCoPhone = /^(?:\+?57)?3\d{9}$/.test(payeeClean);
  const payeeId = isPayeeCoAccount || isPayeeCoPhone ? payeeClean : payeeStr;
  const payeeScheme = isPayeeCoAccount
    ? "co-bancolombia-account"
    : isPayeeCoPhone
      ? "co-phone-number"
      : "co-recipient-id";
  const payeeProvenance = isPayeeAccount
    ? "transaction.counterparty.accountNumber"
    : isPayeePhone
      ? "transaction.counterparty.phone"
      : "transaction.counterparty.id";

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "co/bancolombia",
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
        "Input authenticity is not established by this parser.",
        "Completed is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a bank account reference, not a verified legal person.",
        "Transaction ID is local to Bancolombia records; no cross-bank deduplication is claimed.",
      ],
    },
  };
}
