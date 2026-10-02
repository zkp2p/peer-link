/**
 * Pure, read-only Bank Central Asia (BCA) interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope or receipt the bank page/app loaded.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretBca(input, transactionId) {
  const CURRENCY = "IDR";
  const EXPONENT = 0;

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
  if (!root || !account || !Array.isArray(root.transactions)) {
    return fail("Expected account and transactions");
  }

  const rows = root.transactions.filter((row) => object(row)?.id === transactionId);
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

  if (row.status === "DIPROSES" || row.status === "pending" || row.status === "PENDING") {
    return fail("Transaction is still pending bank execution");
  }
  if (row.status !== "BERHASIL" && row.status !== "SUCCESS" && row.status !== "COMPLETED") {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency: only IDR is supported");
  }

  const amountMatch =
    typeof row.amount === "string" ? /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount) : null;
  const fraction = amountMatch?.[2] ?? "";
  if (!amountMatch || (fraction.length > 0 && fraction !== "0" && fraction !== "00")) {
    return fail("Amount must be a whole decimal string within currency precision");
  }

  const minor = BigInt(amountMatch[1]);
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
  const payerId =
    typeof payer.accountNumber === "string"
      ? payer.accountNumber
      : typeof payer.id === "string"
        ? payer.id
        : "";
  if (!text(payerId) || payerId.includes("*") || payerId.includes("•")) {
    return fail("Unmasked payer account identifier is required");
  }

  const payee = object(row.payee);
  const payeeId =
    typeof payee?.accountNumber === "string"
      ? payee.accountNumber
      : typeof payee?.id === "string"
        ? payee.id
        : "";
  if (!text(payeeId) || payeeId.includes("*") || payeeId.includes("•")) {
    return fail("Unmasked counterparty account identifier is required");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "id/bca",
      transactionId,
      payer: {
        id: payerId,
        scheme: /^\d{10}$/.test(payerId) ? "bca-account-number" : "bca-account-id",
        provenance: "account.id",
      },
      payee: {
        id: payeeId,
        scheme: /^\d{10}$/.test(payeeId) ? "bca-account-number" : "id-recipient-id",
        provenance: "transaction.payee",
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
        "Transaction ID is local to BCA; no cross-bank deduplication is claimed.",
        "BI-FAST transfers depend on Bank Indonesia settlement infrastructure availability.",
      ],
    },
  };
}
