/**
 * Pure, read-only BBVA Mexico interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope loaded from BBVA Mexico web movements or activity records.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretBbvaMexico(input, transactionId) {
  const CURRENCY = "MXN";
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

  // Explicitly abstain on utility payments, credit card bills, merchant QR, and cash withdrawals
  const isExcluded =
    row.type === "pago_servicios" ||
    row.type === "credit_card_payment" ||
    row.type === "merchant_qr" ||
    (typeof row.category === "string" &&
      /servicios|credit[_\s-]?card|tarjeta|qr|comercio|cajero/i.test(row.category)) ||
    (typeof row.description === "string" &&
      /pago de servicios|tarjeta de credito|compra qr|cajero/i.test(row.description));
  if (isExcluded) {
    return {
      outcome: "unsupported",
      reason: "Service payments, credit card payments, and merchant transactions are out of scope",
    };
  }

  // Accept only supported outgoing domestic SPEI transfer types
  const supportedTypes = [
    "domesticTransfer",
    "speiTransfer",
    "transferencia_spei",
    "spei",
    "p2p_transfer",
  ];
  if (!supportedTypes.includes(/** @type {string} */ (row.type)) || row.direction !== "debit") {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic SPEI transfers are supported",
    };
  }

  // Final bank-reported completion statuses
  const completedStatuses = [
    "completed",
    "EXITOSA",
    "LIQUIDADA",
    "APROBADA",
    "EJECUTADA",
    "SUCCESS",
  ];
  if (!completedStatuses.includes(/** @type {string} */ (row.status))) {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency");
  }

  // Parse money from decimal string using BigInt scaling (1 MXN = 100 centavos)
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

  // Payer account / CLABE / phone identification
  const isPayerClabe = typeof account.clabe === "string";
  const isPayerAccount = typeof account.accountNumber === "string";
  const isPayerPhone = typeof account.phone === "string";
  const payerRaw = isPayerClabe
    ? account.clabe
    : isPayerAccount
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
  const isPayerClabeDigits = /^\d{18}$/.test(payerClean);
  const isPayerCardDigits = /^\d{16}$/.test(payerClean);
  const isPayerPhoneDigits = /^(?:\+?52)?\d{10}$/.test(payerClean);
  const isPayerStructured = isPayerClabeDigits || isPayerCardDigits || isPayerPhoneDigits;
  const payerId = isPayerStructured ? payerClean : payerStr;
  const payerScheme = isPayerClabeDigits
    ? "mx-clabe"
    : isPayerCardDigits
      ? "mx-card"
      : isPayerPhoneDigits
        ? "mx-phone-number"
        : "bbva-account-id";
  const payerProvenance = isPayerClabe
    ? "account.clabe"
    : isPayerAccount
      ? "account.accountNumber"
      : isPayerPhone
        ? "account.phone"
        : "account.id";

  // Payee counterparty identification
  const counterparty = object(row.counterparty);
  const isPayeeClabe = typeof counterparty?.clabe === "string";
  const isPayeeAccount = typeof counterparty?.accountNumber === "string";
  const isPayeeCard = typeof counterparty?.card === "string";
  const isPayeePhone = typeof counterparty?.phone === "string";
  const payeeRaw = isPayeeClabe
    ? counterparty.clabe
    : isPayeeAccount
      ? counterparty.accountNumber
      : isPayeeCard
        ? counterparty.card
        : isPayeePhone
          ? counterparty.phone
          : counterparty?.id;

  if (!text(payeeRaw)) {
    return fail("Full recipient account or CLABE identifier is required");
  }
  const payeeStr = /** @type {string} */ (payeeRaw).trim();
  if (payeeStr.includes("*") || payeeStr.includes("•")) {
    return fail("Masked recipient identifier is insufficient");
  }

  const payeeClean = payeeStr.replace(/[-\s]/g, "");
  const isPayeeClabeDigits = /^\d{18}$/.test(payeeClean);
  const isPayeeCardDigits = /^\d{16}$/.test(payeeClean);
  const isPayeePhoneDigits = /^(?:\+?52)?\d{10}$/.test(payeeClean);
  const isPayeeStructured = isPayeeClabeDigits || isPayeeCardDigits || isPayeePhoneDigits;
  const payeeId = isPayeeStructured ? payeeClean : payeeStr;
  const payeeScheme = isPayeeClabeDigits
    ? "mx-clabe"
    : isPayeeCardDigits
      ? "mx-card"
      : isPayeePhoneDigits
        ? "mx-phone-number"
        : "mx-recipient-id";
  const payeeProvenance = isPayeeClabe
    ? "transaction.counterparty.clabe"
    : isPayeeAccount
      ? "transaction.counterparty.accountNumber"
      : isPayeeCard
        ? "transaction.counterparty.card"
        : isPayeePhone
          ? "transaction.counterparty.phone"
          : "transaction.counterparty.id";

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "mx/bbva-mexico",
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
        "Transaction ID is local to BBVA Mexico records; no cross-bank deduplication is claimed.",
      ],
    },
  };
}
