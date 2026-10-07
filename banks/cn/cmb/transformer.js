/**
 * Pure, read-only China Merchants Bank interpretation. No login, network, clock, randomness or logging.
 * Interprets completed outgoing domestic CNY transfers from CMB personal internet banking transaction records.
 * @param {unknown} input The response envelope the bank page loaded.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretChinaMerchantsBank(input, transactionId) {
  const CURRENCY = "CNY";
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
  if (!root || !account || !Array.isArray(root.transactions))
    return fail("Expected account and transactions");
  if (!text(transactionId)) return fail("A transaction ID is required");
  const rows = root.transactions.filter((row) => object(row)?.id === transactionId);
  if (rows.length !== 1) return fail("Selected transaction must occur exactly once");
  const row = /** @type {Record<string, unknown>} */ (rows[0]);

  if (row.type !== "domesticTransfer" || row.direction !== "debit")
    return { outcome: "unsupported", reason: "Only outgoing domestic transfers are supported" };
  if (row.status !== "completed") return fail("Transaction is not bank-reported completed");
  if (row.currency !== CURRENCY) return fail("Missing or conflicting currency");

  // Parse money from a decimal string. Never multiply floating-point numbers.
  const amount =
    typeof row.amount === "string" ? /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount) : null;
  const fraction = amount?.[2] ?? "";
  if (!amount || fraction.length > EXPONENT)
    return fail("Amount must be a decimal string within currency precision");
  const minor =
    BigInt(amount[1]) * 10n ** BigInt(EXPONENT) + BigInt(fraction.padEnd(EXPONENT, "0") || "0");
  if (minor <= 0n) return fail("Amount must be positive");

  if (
    typeof row.bookedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.bookedAt)
  )
    return fail("Expected an explicit UTC timestamp");
  const time = Date.parse(row.bookedAt);
  if (
    !Number.isFinite(time) ||
    new Date(time).toISOString().slice(0, 19) !== row.bookedAt.slice(0, 19)
  )
    return fail("Invalid timestamp");

  if (!text(account.id)) return fail("Payer account identifier is missing");
  const counterparty = object(row.counterparty);
  if (
    typeof counterparty?.accountNumber !== "string" ||
    !/^\d{6,34}$/.test(counterparty.accountNumber)
  )
    return fail("Full recipient account identifier is required");

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "cn/cmb",
      transactionId,
      payer: {
        id: /** @type {string} */ (account.id),
        scheme: "cmb-account-id",
        provenance: "account.id",
      },
      payee: {
        id: counterparty.accountNumber,
        scheme: "cn-account-number",
        provenance: "transaction.counterparty.accountNumber",
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
        "Payer identity is a bank account reference, not a verified legal person.",
        "Transaction ID is local to this bank; no cross-bank deduplication is claimed.",
      ],
    },
  };
}
