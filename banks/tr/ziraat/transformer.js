/**
 * Pure, read-only Ziraat Bank interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope or receipt the bank page/app loaded.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretZiraat(input, transactionId) {
  const CURRENCY = "TRY";
  const EXPONENT = 2;

  const fail = (/** @type {string} */ reason) =>
    /** @type {const} */ ({ outcome: "insufficient_evidence", reason });
  const object = (/** @type {unknown} */ v) =>
    v !== null && typeof v === "object" && !Array.isArray(v)
      ? /** @type {Record<string, unknown>} */ (v)
      : null;
  const text = (/** @type {unknown} */ v) => typeof v === "string" && v.trim().length > 0;

  if (!text(transactionId)) return fail("A transaction ID is required");

  const root = object(input);
  const account = object(root?.account);

  let txList = null;
  if (Array.isArray(input)) {
    txList = input;
  } else if (Array.isArray(root?.transactions)) {
    txList = root.transactions;
  } else if (Array.isArray(root?.data)) {
    txList = root.data;
  } else if (root?.id === transactionId) {
    txList = [root];
  } else {
    const wrapped = object(root?.receipt) ?? object(root?.data);
    if (wrapped?.id === transactionId) {
      txList = [wrapped];
    }
  }

  if (!txList) {
    return fail("Expected account and transactions");
  }

  const rows = txList.filter((r) => object(r)?.id === transactionId);
  if (rows.length !== 1) {
    return fail("Selected transaction must occur exactly once");
  }

  const row = object(rows[0]);
  if (!row) return fail("Invalid transaction");

  if (row.type !== "domesticTransfer") {
    return { outcome: "unsupported", reason: "Only domestic transfers are supported" };
  }
  if (row.direction !== "debit") {
    return { outcome: "unsupported", reason: "Only outgoing debit transfers are supported" };
  }

  if (
    row.status === "BEKLEMEDE" ||
    row.status === "pending" ||
    row.status === "PROCESSING" ||
    row.status === "İNCELENİYOR"
  ) {
    return fail("Transaction is still pending bank execution");
  }
  const completedStatuses = [
    "COMPLETED",
    "SUCCESS",
    "BAŞARILI",
    "GERÇEKLEŞTİ",
    "TAMAMLANDI",
    "ONAYLANDI",
  ];
  if (typeof row.status !== "string" || !completedStatuses.includes(row.status)) {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency: only TRY is supported");
  }

  // Parse amount: support Turkish formatting (period thousands, comma decimals), US formatting, or number
  let rawAmount = "";
  if (typeof row.amount === "number") {
    if (!Number.isFinite(row.amount) || row.amount <= 0) {
      return fail("Amount must be a positive number");
    }
    rawAmount = row.amount.toString();
  } else if (typeof row.amount === "string") {
    rawAmount = row.amount.trim();
  } else {
    return fail("Amount must be a decimal string within currency precision");
  }

  // Strip currency tokens: TL, ₺, TRY
  rawAmount = rawAmount
    .replace(/^(?:TRY|TL|₺)\s*/i, "")
    .replace(/\s*(?:TRY|TL|₺)$/i, "")
    .trim();

  let whole = "";
  let fraction = "";

  if (rawAmount.includes(".") && rawAmount.includes(",")) {
    const dotIdx = rawAmount.indexOf(".");
    const commaIdx = rawAmount.indexOf(",");
    if (dotIdx < commaIdx) {
      // Turkish format: 1.250,75
      whole = rawAmount.slice(0, commaIdx).replaceAll(".", "");
      fraction = rawAmount.slice(commaIdx + 1);
    } else {
      // US format: 1,250.75
      whole = rawAmount.slice(0, dotIdx).replaceAll(",", "");
      fraction = rawAmount.slice(dotIdx + 1);
    }
  } else if (rawAmount.includes(",")) {
    // Comma decimal: 1250,75
    const parts = rawAmount.split(",");
    if (parts.length !== 2) {
      return fail("Amount must be a decimal string within currency precision");
    }
    whole = parts[0];
    fraction = parts[1];
  } else if (rawAmount.includes(".")) {
    const parts = rawAmount.split(".");
    if (parts.length === 2 && parts[1].length <= EXPONENT) {
      whole = parts[0];
      fraction = parts[1];
    } else {
      return fail("Amount must be a decimal string within currency precision");
    }
  } else {
    whole = rawAmount;
    fraction = "";
  }

  if (!/^(0|[1-9]\d{0,14})$/.test(whole) || !/^\d*$/.test(fraction) || fraction.length > EXPONENT) {
    return fail("Amount must be a decimal string within currency precision");
  }

  const minor = BigInt(whole) * 100n + BigInt(fraction.padEnd(EXPONENT, "0") || "0");
  if (minor <= 0n) return fail("Amount must be positive");

  if (
    typeof row.bookedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.bookedAt)
  ) {
    return fail("Expected an explicit UTC ISO 8601 timestamp ending with Z");
  }
  const timeMs = Date.parse(row.bookedAt);
  if (
    !Number.isFinite(timeMs) ||
    new Date(timeMs).toISOString().slice(0, 19) !== row.bookedAt.slice(0, 19)
  ) {
    return fail("Invalid timestamp calendar date");
  }

  const payer = object(row.payer) ?? account;
  const rawPayerId =
    typeof payer?.iban === "string" ? payer.iban : typeof payer?.id === "string" ? payer.id : "";
  if (!text(rawPayerId) || /[*•?]/.test(rawPayerId)) {
    return fail("Unmasked payer IBAN or account identifier is required");
  }
  const payerId = rawPayerId.replace(/[\s-]/g, "");
  const isPayerTrIban = /^TR\d{24}$/.test(payerId);

  const payee = object(row.payee);
  const rawPayeeId =
    typeof payee?.iban === "string"
      ? payee.iban
      : typeof payee?.accountNumber === "string"
        ? payee.accountNumber
        : typeof payee?.id === "string"
          ? payee.id
          : "";
  if (!text(rawPayeeId) || /[*•?]/.test(rawPayeeId)) {
    return fail("Unmasked counterparty IBAN or identifier is required");
  }
  const payeeId = rawPayeeId.replace(/[\s-]/g, "");
  const isPayeeTrIban = /^TR\d{24}$/.test(payeeId);

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "tr/ziraat",
      transactionId,
      payer: {
        id: isPayerTrIban ? payerId : rawPayerId.trim(),
        scheme: isPayerTrIban ? "tr-iban" : "ziraat-account-id",
        provenance: "account.id",
      },
      payee: {
        id: isPayeeTrIban ? payeeId : rawPayeeId.trim(),
        scheme: isPayeeTrIban ? "tr-iban" : "tr-recipient-id",
        provenance: "transaction.payee",
      },
      amountMinor: minor.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: row.status,
      timestamp: row.bookedAt,
      timestampMeaning: "bookedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "Completed is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a bank account/IBAN reference, not a verified legal person.",
        "Transaction ID is local to Ziraat Bank; no cross-bank deduplication is claimed.",
        "FAST and EFT settlement rails depend on Central Bank of the Republic of Turkey (TCMB) operational hours and rules.",
      ],
    },
  };
}
