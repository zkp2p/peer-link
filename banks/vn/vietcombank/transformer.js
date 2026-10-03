/**
 * Pure, read-only Vietcombank interpretation. No login, network, clock, randomness or logging.
 * Interprets VCB Digibank statement history and transaction advice exports.
 * @param {unknown} input The response envelope the bank page loaded.
 * @param {string} transactionId The explicitly selected transaction.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretVietcombank(input, transactionId) {
  const CURRENCY = "VND";
  const EXPONENT = 0; // Vietnamese Dong has no fractional minor units in circulation

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

  const rows = root.transactions.filter((item) => {
    const obj = object(item);
    if (!obj) return false;
    return (
      obj.id === transactionId || obj.refNo === transactionId || obj.transactionId === transactionId
    );
  });

  if (rows.length !== 1) {
    return fail("Selected transaction must occur exactly once");
  }

  const row = /** @type {Record<string, unknown>} */ (rows[0]);

  const rawType = typeof row.type === "string" ? row.type : "";
  const rawDescription = typeof row.description === "string" ? row.description : "";
  const typeLower = rawType.toLowerCase();
  const descLower = rawDescription.toLowerCase();

  // Out-of-scope payment rail exclusions
  if (
    typeLower.includes("atm") ||
    /\batm\b/i.test(descLower) ||
    descLower.includes("rút tiền") ||
    descLower.includes("rut tien") ||
    typeLower.includes("cash")
  ) {
    return {
      outcome: "unsupported",
      reason: "Cash withdrawals and ATM operations are outside scope",
    };
  }

  if (
    typeLower.includes("qr") ||
    descLower.includes("vnpay") ||
    descLower.includes("qr-code") ||
    descLower.includes("thanh toan qr") ||
    descLower.includes("thanh toán qr")
  ) {
    return {
      outcome: "unsupported",
      reason: "Merchant QR code purchases are outside scope",
    };
  }

  if (
    typeLower.includes("bill") ||
    typeLower.includes("utility") ||
    descLower.includes("tiền điện") ||
    descLower.includes("tien dien") ||
    descLower.includes("tiền nước") ||
    descLower.includes("tien nuoc") ||
    descLower.includes("tiền mạng") ||
    descLower.includes("cước") ||
    descLower.includes("cuoc") ||
    descLower.includes("nạp tiền") ||
    descLower.includes("nap tien")
  ) {
    return {
      outcome: "unsupported",
      reason: "Utility bills and mobile top-ups are outside scope",
    };
  }

  if (
    typeLower.includes("pos") ||
    typeLower.includes("card") ||
    typeLower.includes("merchant") ||
    /\bpos\b/i.test(descLower) ||
    descLower.includes("thanh toán thẻ") ||
    descLower.includes("thanh toan the")
  ) {
    return {
      outcome: "unsupported",
      reason: "Card purchases and POS debits are outside scope",
    };
  }

  // Active authorization hold check
  if (row.hold === true) {
    return fail("Transaction has an active hold and is not settled");
  }

  // Direction filter: only outgoing debits
  const isCredit =
    row.direction === "credit" ||
    (typeof row.amount === "number" && row.amount > 0 && row.direction !== "debit");
  if (isCredit) {
    return { outcome: "unsupported", reason: "Only outgoing debit movements are supported" };
  }

  // Currency validation
  const isVndCurrency =
    row.currency === CURRENCY || row.currencyCode === 704 || row.currencyCode === "704";
  if (!isVndCurrency) {
    return fail("Missing or conflicting currency");
  }

  // Status check
  if (typeof row.status === "string") {
    const finalStatuses = new Set([
      "completed",
      "settled",
      "success",
      "thành công",
      "thanh cong",
      "thanh_cong",
    ]);
    if (!finalStatuses.has(row.status.toLowerCase())) {
      return fail("Transaction is not bank-reported completed");
    }
  }

  // Amount parsing (whole VND, exponent 0)
  let minor = 0n;
  if (typeof row.amount === "number" && Number.isFinite(row.amount)) {
    const intAmount = Math.round(row.amount);
    if (intAmount >= 0 && row.direction !== "debit") {
      return fail("Amount must be negative or debit");
    }
    const absMinor = Math.abs(intAmount);
    if (absMinor === 0) {
      return fail("Amount must be positive");
    }
    minor = BigInt(absMinor);
  } else if (typeof row.amount === "string") {
    const amountMatch = /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount);
    const fraction = amountMatch?.[2] ?? "";
    if (!amountMatch || (fraction.length > 0 && !/^0+$/.test(fraction))) {
      return fail("Amount must be a whole currency string without fractional units for VND");
    }
    minor = BigInt(amountMatch[1]);
    if (minor <= 0n) {
      return fail("Amount must be positive");
    }
  } else {
    return fail("Invalid amount format");
  }

  // Timestamp parsing
  let isoTimestamp = "";
  const rawTimestamp =
    typeof row.timeIso === "string"
      ? row.timeIso
      : typeof row.bookedAt === "string"
        ? row.bookedAt
        : typeof row.transactionDate === "string"
          ? row.transactionDate
          : null;

  if (rawTimestamp !== null) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(rawTimestamp)) {
      return fail("Expected an explicit UTC timestamp");
    }
    const timeMs = Date.parse(rawTimestamp);
    if (
      !Number.isFinite(timeMs) ||
      new Date(timeMs).toISOString().slice(0, 19) !== rawTimestamp.slice(0, 19)
    ) {
      return fail("Invalid timestamp");
    }
    isoTimestamp = rawTimestamp;
  } else if (typeof row.time === "number" && Number.isFinite(row.time) && row.time > 0) {
    const timeMs = Math.round(row.time) * 1000;
    isoTimestamp = new Date(timeMs).toISOString();
  } else {
    return fail("Missing or invalid transaction timestamp");
  }

  // Payer account identification
  const payerAccountRaw =
    typeof account.accountNo === "string"
      ? account.accountNo
      : typeof account.accountNumber === "string"
        ? account.accountNumber
        : typeof account.id === "string"
          ? account.id
          : null;

  if (payerAccountRaw === null || !text(payerAccountRaw)) {
    return fail("Payer account identifier is missing");
  }

  const cleanPayer = /^\d[\d\s-]*\d$/.test(payerAccountRaw)
    ? payerAccountRaw.replace(/[-\s]/g, "")
    : payerAccountRaw.trim();
  if (cleanPayer.includes("*") || cleanPayer.includes("•")) {
    return fail("Masked payer account identifier is insufficient");
  }

  const payerId = cleanPayer;
  const payerScheme = /^\d{10,14}$/.test(cleanPayer)
    ? "vn-vietcombank-account"
    : "vn-account-number";
  const payerProvenance =
    typeof account.accountNo === "string"
      ? "account.accountNo"
      : typeof account.accountNumber === "string"
        ? "account.accountNumber"
        : "account.id";

  // Payee counterparty identification
  const counterparty = object(row.counterparty) || object(row.beneficiary);
  const payeeAccountRaw =
    typeof counterparty?.accountNumber === "string"
      ? counterparty.accountNumber
      : typeof counterparty?.accountNo === "string"
        ? counterparty.accountNo
        : typeof counterparty?.id === "string"
          ? counterparty.id
          : null;

  if (payeeAccountRaw === null || !text(payeeAccountRaw)) {
    return fail("Full recipient account identifier is required");
  }

  const cleanPayee = /^\d[\d\s-]*\d$/.test(payeeAccountRaw)
    ? payeeAccountRaw.replace(/[-\s]/g, "")
    : payeeAccountRaw.trim();
  if (cleanPayee.includes("*") || cleanPayee.includes("•")) {
    return fail("Masked recipient account identifier is insufficient");
  }

  const payeeId = cleanPayee;
  const payeeScheme = /^\d{6,24}$/.test(cleanPayee) ? "vn-account-number" : "counterparty-id";
  const payeeProvenance =
    typeof counterparty?.accountNumber === "string"
      ? "transaction.counterparty.accountNumber"
      : typeof counterparty?.accountNo === "string"
        ? "transaction.beneficiary.accountNo"
        : "transaction.counterparty.id";

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "vn/vietcombank",
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
      timestamp: isoTimestamp,
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
