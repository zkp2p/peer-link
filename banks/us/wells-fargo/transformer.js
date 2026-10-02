/**
 * Pure, read-only Wells Fargo transaction interpretation.
 * No login, network, clock, randomness, filesystem access, or console logging.
 *
 * @param {unknown} input The activity response payload loaded by the bank page.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretWellsFargo(input, transactionId) {
  const CURRENCY = "USD";
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
    return fail("Expected account metadata and transactions array");
  }

  if (!text(transactionId)) {
    return fail("A valid transaction ID is required");
  }

  const matchingRows = root.transactions.filter((row) => object(row)?.id === transactionId);
  if (matchingRows.length !== 1) {
    return fail("Selected transaction must occur exactly once in transaction history");
  }

  const row = object(matchingRows[0]);
  if (!row) {
    return fail("Transaction entry is invalid");
  }

  // Check payment verb and direction: only outgoing domestic transfers supported
  if (row.type !== "outgoingDomesticTransfer" || row.direction !== "debit") {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic debit transfers are supported by this adapter",
    };
  }

  // Status check: pending/scheduled must fail closed
  if (row.status !== "completed") {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency code");
  }

  // Parse amount in fixed-point decimal string to prevent floating-point imprecision
  if (typeof row.amount !== "string") {
    return fail("Expected amount as a formatted decimal string");
  }

  const parsedAmount = /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount);
  if (!parsedAmount) {
    return fail("Amount must be a valid positive decimal string");
  }

  const whole = parsedAmount[1];
  const fraction = parsedAmount[2] ?? "";
  if (fraction.length > EXPONENT) {
    return fail("Amount fraction exceeds supported currency precision");
  }

  const minorUnits = BigInt(whole) * 100n + BigInt(fraction.padEnd(EXPONENT, "0") || "0");
  if (minorUnits <= 0n) {
    return fail("Amount must be strictly greater than zero");
  }

  // Validate posted timestamp format (UTC ISO string)
  if (
    typeof row.postedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.postedAt)
  ) {
    return fail("Expected an explicit UTC ISO-8601 timestamp in postedAt");
  }

  const parsedTime = Date.parse(row.postedAt);
  if (
    !Number.isFinite(parsedTime) ||
    new Date(parsedTime).toISOString().slice(0, 19) !== row.postedAt.slice(0, 19)
  ) {
    return fail("Invalid postedAt date format");
  }

  if (!text(account.id)) {
    return fail("Payer account identifier is missing");
  }

  const counterparty = object(row.counterparty);
  if (!counterparty) {
    return fail("Counterparty information is required");
  }

  if (
    typeof counterparty.routingNumber !== "string" ||
    !/^\d{9}$/.test(counterparty.routingNumber)
  ) {
    return fail("Valid 9-digit US routing number is required");
  }

  if (
    typeof counterparty.accountNumber !== "string" ||
    !/^\d{4,17}$/.test(counterparty.accountNumber)
  ) {
    return fail("Full unmasked counterparty account number is required");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "us/wells-fargo",
      transactionId,
      payer: {
        id: /** @type {string} */ (account.id),
        scheme: "wells-fargo-account-id",
        provenance: "account.id",
      },
      payee: {
        id: `${counterparty.routingNumber}:${counterparty.accountNumber}`,
        scheme: "us-routing-account",
        provenance: "transaction.counterparty",
      },
      amountMinor: minorUnits.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: "completed",
      timestamp: row.postedAt,
      timestampMeaning: "postedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "Completed represents sender-bank status, not proof of recipient credit or final settlement.",
        "Payer identity is an internal account reference, not a verified legal entity.",
        "Transaction ID is local to Wells Fargo ledger records; no global deduplication is claimed.",
      ],
    },
  };
}
