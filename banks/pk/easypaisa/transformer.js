/**
 * Pure, read-only Easypaisa wallet-transfer interpretation. No login, network,
 * clock, randomness, storage or logging.
 *
 * Input contract (documented assumption — confirm against the real Easypaisa
 * app/web transaction-history surface during the account-owner live check):
 * an envelope `{ account: { id, msisdn }, transactions: [...] }` where each
 * transaction carries `id`, `type`, `direction`, decimal-string `amount`,
 * `currency`, `status`, a UTC `completedAt` timestamp and
 * `counterparty: { msisdn, displayName }`. Memos and display names are
 * untrusted and never establish identity.
 *
 * Supported claim: one completed outgoing Easypaisa-to-Easypaisa PKR wallet
 * transfer (debit), bank-reported SUCCESS. IBFT, Raast, bill payments,
 * top-ups, credits and every non-final status are out of scope.
 *
 * @param {unknown} input The response envelope the bank page loaded.
 * @param {string} transactionId The explicitly selected transaction.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretEasypaisa(input, transactionId) {
  // PKR (ISO 4217) uses 2 minor units (paisa).
  const CURRENCY = "PKR";
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
  if (row.type !== "walletTransfer" || row.direction !== "debit")
    return {
      outcome: "unsupported",
      reason: "Only outgoing Easypaisa-to-Easypaisa wallet transfers are supported",
    };
  // The bank's exact final status value; every other value abstains.
  if (row.status !== "SUCCESS") return fail("Transaction is not bank-reported SUCCESS");
  if (row.currency !== CURRENCY) return fail("Missing or conflicting currency");
  // Parse money from a decimal string. Never multiply floating-point numbers.
  const amount =
    typeof row.amount === "string" ? /^(0|[1-9]\d{0,14})(?:\.(\d{1,2}))?$/.exec(row.amount) : null;
  if (!amount) return fail("Amount must be a decimal string within PKR precision");
  const minor =
    BigInt(amount[1]) * 10n ** BigInt(EXPONENT) + BigInt((amount[2] ?? "").padEnd(EXPONENT, "0"));
  if (minor <= 0n) return fail("Amount must be positive");
  // Strict UTC timestamp. The Easypaisa surface reports Asia/Karachi (UTC+5, no
  // DST); acquisition converts local wall-clock time to UTC before parsing.
  if (
    typeof row.completedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.completedAt)
  )
    return fail("Expected an explicit UTC completedAt timestamp");
  const time = Date.parse(row.completedAt);
  if (
    !Number.isFinite(time) ||
    new Date(time).toISOString().slice(0, 19) !== row.completedAt.slice(0, 19)
  )
    return fail("Invalid completedAt timestamp");
  if (!text(account.id)) return fail("Payer account identifier is missing");
  const counterparty = object(row.counterparty);
  const msisdn = counterparty?.msisdn;
  // Full Pakistani mobile number only: 03XX-XXXXXXX or +923XX-XXXXXXX.
  // Masked numbers (0300****001) and display names alone are not unique
  // payee identifiers and must fail closed.
  if (typeof msisdn !== "string" || !/^(?:\+92|0)3\d{9}$/.test(msisdn))
    return fail("Full recipient MSISDN is required");
  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "pk/easypaisa",
      transactionId,
      payer: {
        id: /** @type {string} */ (account.id),
        scheme: "easypaisa-account-id",
        provenance: "account.id",
      },
      payee: {
        id: msisdn,
        scheme: "pk-msisdn",
        provenance: "transaction.counterparty.msisdn",
      },
      amountMinor: minor.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: "SUCCESS",
      timestamp: /** @type {string} */ (row.completedAt),
      timestampMeaning: "completedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "SUCCESS is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is an Easypaisa account reference, not a verified legal person.",
        "The recipient MSISDN is a routing identifier, not proof the wallet exists or is owned by the named party.",
        "Transaction ID is local to this bank; no cross-bank deduplication is claimed.",
        "The response shape is a documented assumption; confirm it against the real Easypaisa surface in the live check.",
      ],
    },
  };
}
