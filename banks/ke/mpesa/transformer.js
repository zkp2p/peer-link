/**
 * Pure, read-only Safaricom M-Pesa interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope loaded from Safaricom M-Pesa statement or activity records.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretMpesa(input, transactionId) {
  const CURRENCY = "KES";
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

  // Explicitly abstain on Paybill, Lipa na M-Pesa (Buy Goods/Till), Fuliza, and agent withdrawals
  const isExcluded =
    row.type === "paybill" ||
    row.type === "buy_goods" ||
    row.type === "agent_withdrawal" ||
    row.type === "fuliza" ||
    (typeof row.category === "string" &&
      /paybill|buy[_\s-]?goods|till|fuliza|agent|airtime/i.test(row.category)) ||
    (typeof row.description === "string" &&
      /paybill|buy goods|till|fuliza|agent withdrawal|airtime/i.test(row.description));
  if (isExcluded) {
    return {
      outcome: "unsupported",
      reason: "Paybill, Buy Goods, Fuliza, and agent withdrawals are out of scope",
    };
  }

  // Accept only supported outgoing Send Money person-to-person transfer types
  const supportedTypes = ["domesticTransfer", "sendMoney", "send_money", "p2p_transfer"];
  if (!supportedTypes.includes(/** @type {string} */ (row.type)) || row.direction !== "debit") {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic Send Money transfers are supported",
    };
  }

  // Final wallet-reported completion statuses
  const completedStatuses = ["completed", "SUCCESS", "SUCCESSFUL", "COMPLETED"];
  if (!completedStatuses.includes(/** @type {string} */ (row.status))) {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency");
  }

  // Parse money from decimal string using BigInt scaling (1 KES = 100 cents)
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

  // Payer wallet / phone identification
  const isPayerPhone = typeof account.phone === "string";
  const payerRaw = isPayerPhone
    ? account.phone
    : typeof account.accountNumber === "string"
      ? account.accountNumber
      : account.id;

  if (!text(payerRaw)) {
    return fail("Payer wallet identifier is missing");
  }
  const payerStr = /** @type {string} */ (payerRaw).trim();
  if (payerStr.includes("*") || payerStr.includes("•")) {
    return fail("Masked payer wallet identifier is insufficient");
  }

  const payerPhoneCandidate = payerStr.replace(/[-\s]/g, "");
  const isKePayerPhone = /^(?:\+?254|0)[17]\d{8}$/.test(payerPhoneCandidate);
  const payerId = isKePayerPhone ? payerPhoneCandidate : payerStr;
  const payerScheme = isKePayerPhone ? "ke-phone-number" : "mpesa-wallet-id";
  const payerProvenance = isPayerPhone
    ? "account.phone"
    : typeof account.accountNumber === "string"
      ? "account.accountNumber"
      : "account.id";

  // Payee counterparty identification
  const counterparty = object(row.counterparty);
  const isPayeePhone = typeof counterparty?.phone === "string";
  const payeeRaw = isPayeePhone
    ? counterparty.phone
    : typeof counterparty?.accountNumber === "string"
      ? counterparty.accountNumber
      : counterparty?.id;

  if (!text(payeeRaw)) {
    return fail("Full recipient wallet or phone identifier is required");
  }
  const payeeStr = /** @type {string} */ (payeeRaw).trim();
  if (payeeStr.includes("*") || payeeStr.includes("•")) {
    return fail("Masked recipient identifier is insufficient");
  }

  const payeePhoneCandidate = payeeStr.replace(/[-\s]/g, "");
  const isKePayeePhone = /^(?:\+?254|0)[17]\d{8}$/.test(payeePhoneCandidate);
  const payeeId = isKePayeePhone ? payeePhoneCandidate : payeeStr;
  const payeeScheme = isKePayeePhone ? "ke-phone-number" : "ke-recipient-id";
  const payeeProvenance = isPayeePhone
    ? "transaction.counterparty.phone"
    : typeof counterparty?.accountNumber === "string"
      ? "transaction.counterparty.accountNumber"
      : "transaction.counterparty.id";

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "ke/mpesa",
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
        "Completed is the sender-wallet status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a mobile wallet reference, not a verified legal person.",
        "Transaction ID is local to M-Pesa records; no cross-network deduplication is claimed.",
      ],
    },
  };
}
