/**
 * Pure, read-only Chase interpretation. No login, network, clock, randomness or logging.
 * Interprets outgoing domestic completed USD ACH transfers from Chase web account activity.
 *
 * @param {unknown} input The response envelope the bank page loaded.
 * @param {string} transactionId The explicitly selected transaction.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretChase(input, transactionId) {
  const CURRENCY = "USD";
  const EXPONENT = 2;

  const fail = (/** @type {string} */ reason) =>
    /** @type {const} */ ({ outcome: "insufficient_evidence", reason });
  const object = (/** @type {unknown} */ v) =>
    v !== null && typeof v === "object" && !Array.isArray(v)
      ? /** @type {Record<string, unknown>} */ (v)
      : null;
  const nonempty = (/** @type {unknown} */ v) => typeof v === "string" && v.trim().length > 0;

  const root = object(input);
  if (!root) return fail("Input must be a JSON object");
  const account = object(root.account);
  if (!account || !Array.isArray(root.transactions))
    return fail("Expected account object and transactions array in response");

  if (!nonempty(transactionId)) return fail("A non-empty transaction ID is required");

  const matchingRows = root.transactions.filter(
    (row) => object(row)?.transactionId === transactionId,
  );
  if (matchingRows.length === 0) return fail("Selected transactionId not found in activity");
  if (matchingRows.length > 1) return fail("Duplicate transactionId found in activity");

  const row = /** @type {Record<string, unknown>} */ (matchingRows[0]);

  // Gate payment type and method
  if (
    row.transactionType !== "ACH_OUTGOING" &&
    row.paymentMethod !== "ACH" &&
    row.transactionType !== "DOMESTIC_TRANSFER"
  ) {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic ACH transfers are supported on this surface",
    };
  }

  // Gate direction
  if (row.direction !== "DEBIT" && row.direction !== "OUTGOING") {
    return {
      outcome: "unsupported",
      reason: "Only debit/outgoing transfers are supported",
    };
  }

  // Gate status
  if (row.status !== "POSTED" && row.status !== "COMPLETED") {
    return fail("Transaction status is not bank-reported POSTED or COMPLETED");
  }

  // Gate currency
  if (row.currency !== CURRENCY) {
    return fail(`Currency must be ${CURRENCY}`);
  }

  // Parse amount in fixed-point cents without floating-point math
  if (typeof row.amount !== "string") {
    return fail("Amount must be a decimal string");
  }
  const match = /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount);
  if (!match) {
    return fail("Amount string format is invalid");
  }
  const majorPart = match[1];
  const minorPart = match[2] ?? "";
  if (minorPart.length > EXPONENT) {
    return fail("Amount precision exceeds 2 decimal places");
  }
  const paddedMinor = minorPart.padEnd(EXPONENT, "0");
  const minorBigInt = BigInt(majorPart) * 100n + BigInt(paddedMinor);
  if (minorBigInt <= 0n) {
    return fail("Amount must be greater than zero");
  }

  // Validate posted timestamp
  const ts = row.postedTimestamp ?? row.timestamp;
  if (typeof ts !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(ts)) {
    return fail("Expected an explicit UTC ISO-8601 timestamp ending in Z");
  }
  const parsedTime = Date.parse(ts);
  const parsedDate = new Date(parsedTime);
  if (!Number.isFinite(parsedTime) || parsedDate.toISOString().slice(0, 19) !== ts.slice(0, 19)) {
    return fail("Invalid ISO timestamp");
  }

  // Validate payer identifier
  const payerId = account.accountId ?? account.id;
  if (!nonempty(payerId)) {
    return fail("Payer account identifier is missing from account details");
  }

  // Validate payee counterparty identifiers
  const counterparty = object(row.counterparty);
  if (!counterparty) {
    return fail("Payee counterparty details are missing");
  }
  const routing = counterparty.routingNumber;
  const accountNumber = counterparty.accountNumber;
  if (
    typeof routing !== "string" ||
    !/^\d{9}$/.test(routing) ||
    typeof accountNumber !== "string" ||
    !/^\d{4,17}$/.test(accountNumber)
  ) {
    return fail("Full payee routing (9 digits) and account numbers (4-17 digits) are required");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "us/chase",
      transactionId,
      payer: {
        id: /** @type {string} */ (payerId),
        scheme: "chase-account-id",
        provenance: "account.accountId",
      },
      payee: {
        id: `${routing}:${accountNumber}`,
        scheme: "us-routing-account",
        provenance: "transaction.counterparty",
      },
      amountMinor: minorBigInt.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: /** @type {string} */ (row.status),
      timestamp: ts,
      timestampMeaning: "postedTimestamp",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this unauthenticated client-side parser.",
        "POSTED/COMPLETED status is sender-bank observation, not proof of recipient credit or settlement.",
        "Payer identity is a Chase account reference, not a verified legal person.",
        "Transaction ID is scoped to Chase ledger activity; no cross-bank uniqueness is claimed.",
        "Raw banking response stayed in local memory and is not published.",
      ],
    },
  };
}
