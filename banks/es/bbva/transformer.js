/**
 * Pure, read-only BBVA Spain interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope or receipt the bank page or app loaded.
 * @param {string} transactionId The explicitly selected transaction identifier.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretBbva(input, transactionId) {
  const CURRENCY = "EUR";
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

  const row = /** @type {Record<string, unknown>} */ (rows[0]);

  if (row.type !== "domesticTransfer" && row.type !== "sepaTransfer") {
    return { outcome: "unsupported", reason: "Only domestic transfers are supported" };
  }
  if (row.direction !== "debit") {
    return { outcome: "unsupported", reason: "Only outgoing debit transfers are supported" };
  }

  if (
    row.status === "PENDING" ||
    row.status === "pending" ||
    row.status === "EN_TRAMITACION" ||
    row.status === "PROGRAMADA" ||
    row.status === "EN_CURSO"
  ) {
    return fail("Transaction is still pending bank execution");
  }
  const completedStatuses = ["COMPLETED", "completed", "EJECUTADA", "REALIZADA", "SUCCESS"];
  if (typeof row.status !== "string" || !completedStatuses.includes(row.status)) {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency: only EUR is supported");
  }

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

  rawAmount = rawAmount
    .replace(/^(?:EUR|€)\s*/i, "")
    .replace(/\s*(?:EUR|€)$/i, "")
    .trim();

  let whole = "";
  let fraction = "";

  if (rawAmount.includes(".") && rawAmount.includes(",")) {
    const dotIdx = rawAmount.indexOf(".");
    const commaIdx = rawAmount.indexOf(",");
    if (dotIdx < commaIdx) {
      whole = rawAmount.slice(0, commaIdx).replaceAll(".", "");
      fraction = rawAmount.slice(commaIdx + 1);
    } else {
      whole = rawAmount.slice(0, dotIdx).replaceAll(",", "");
      fraction = rawAmount.slice(dotIdx + 1);
    }
  } else if (rawAmount.includes(",")) {
    const parts = rawAmount.split(",");
    if (parts.length === 2 && parts[1].length <= EXPONENT) {
      whole = parts[0];
      fraction = parts[1];
    } else {
      return fail("Amount must be a decimal string within currency precision");
    }
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

  if (/^\d{1,3}([\s\u00A0\u202F]\d{3})+$/.test(whole)) {
    whole = whole.replace(/[\s\u00A0\u202F]/g, "");
  }

  if (!/^(0|[1-9]\d{0,14})$/.test(whole) || !/^\d*$/.test(fraction) || fraction.length > EXPONENT) {
    return fail("Amount must be a decimal string within currency precision");
  }

  const minor = BigInt(whole) * 100n + BigInt(fraction.padEnd(EXPONENT, "0"));
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
    typeof payer?.iban === "string"
      ? payer.iban
      : typeof payer?.accountNumber === "string"
        ? payer.accountNumber
        : typeof payer?.id === "string"
          ? payer.id
          : "";
  if (!text(rawPayerId) || /[*•?]/.test(rawPayerId)) {
    return fail("Unmasked payer IBAN identifier is required");
  }
  const payerClean = rawPayerId.replace(/[\s-]/g, "").toUpperCase();
  const isPayerIban = /^ES\d{22}$/.test(payerClean);
  if (!isPayerIban) {
    return fail("Valid Spanish IBAN is required for payer");
  }

  const payee = object(row.payee) ?? object(row.counterparty);
  const rawPayeeId =
    typeof payee?.iban === "string"
      ? payee.iban
      : typeof payee?.accountNumber === "string"
        ? payee.accountNumber
        : typeof payee?.id === "string"
          ? payee.id
          : "";
  if (!text(rawPayeeId) || /[*•?]/.test(rawPayeeId)) {
    return fail("Unmasked counterparty IBAN identifier is required");
  }
  const payeeClean = rawPayeeId.replace(/[\s-]/g, "").toUpperCase();
  const isPayeeIban = /^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/.test(payeeClean);
  if (!isPayeeIban) {
    return fail("Valid SEPA IBAN is required for payee");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "es/bbva",
      transactionId,
      payer: {
        id: payerClean,
        scheme: "iban",
        provenance: "account.iban",
      },
      payee: {
        id: payeeClean,
        scheme: "iban",
        provenance: "transaction.payee.iban",
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
        "Executed is the sender bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is an IBAN account reference, not a verified legal person.",
        "Transaction ID is local to BBVA Spain; no cross bank deduplication is claimed.",
        "Bizum mobile payments, direct debits, card transactions, and international non SEPA wires are unsupported.",
      ],
    },
  };
}
