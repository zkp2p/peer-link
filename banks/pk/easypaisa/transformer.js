/**
 * Pure, read-only Easypaisa interpretation. No login, network, clock, randomness or logging.
 * Interprets outgoing domestic completed PKR money transfers from Easypaisa receipt records.
 *
 * @param {unknown} input The response envelope the bank page or app loaded.
 * @param {string} transactionId The explicitly selected transaction.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretEasypaisa(input, transactionId) {
  const CURRENCY = "PKR";
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

  if (!nonempty(transactionId)) return fail("A non-empty transaction ID is required");

  const matches = Array.isArray(root.receipts)
    ? root.receipts.filter((r) => object(r)?.transactionId === transactionId)
    : object(root.receipt)?.transactionId === transactionId
      ? [object(root.receipt)]
      : root.transactionId === transactionId
        ? [root]
        : [];

  if (matches.length === 0) return fail("Selected transactionId not found in receipt data");
  if (matches.length > 1) return fail("Duplicate transactionId found in receipt data");

  const targetReceipt = /** @type {Record<string, unknown>} */ (matches[0]);

  // Gate payment type
  const txType = targetReceipt.transactionType ?? targetReceipt.type;
  if (
    txType !== "EASYPAISA_TRANSFER" &&
    txType !== "RAAST_IBFT" &&
    txType !== "MONEY_TRANSFER" &&
    txType !== "DOMESTIC_TRANSFER"
  ) {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic money transfers are supported on this surface",
    };
  }

  // Gate direction
  const direction = targetReceipt.direction;
  if (direction !== "DEBIT" && direction !== "OUTGOING") {
    return {
      outcome: "unsupported",
      reason: "Only debit/outgoing transfers are supported",
    };
  }

  // Gate status
  const status = targetReceipt.status;
  if (status !== "COMPLETED" && status !== "SUCCESS" && status !== "PAID") {
    return fail("Transaction status is not bank-reported COMPLETED or SUCCESS");
  }

  // Gate currency
  if (targetReceipt.currency !== CURRENCY) {
    return fail(`Currency must be ${CURRENCY}`);
  }

  // Parse amount in fixed-point paisa without floating-point math
  if (typeof targetReceipt.amount !== "string") {
    return fail("Amount must be a decimal string");
  }
  const match = /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(targetReceipt.amount);
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

  // Validate execution timestamp
  const ts =
    targetReceipt.executionTimestamp ?? targetReceipt.timestamp ?? targetReceipt.transactionDate;
  if (typeof ts !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(ts)) {
    return fail("Expected an explicit UTC ISO-8601 timestamp ending in Z");
  }
  const parsedTime = Date.parse(ts);
  const parsedDate = new Date(parsedTime);
  if (!Number.isFinite(parsedTime) || parsedDate.toISOString().slice(0, 19) !== ts.slice(0, 19)) {
    return fail("Invalid ISO timestamp");
  }

  // Validate sender / payer identifier
  const sender = object(targetReceipt.sender);
  const payerRaw = sender?.mobileNumber ?? sender?.accountNumber ?? sender?.id;
  if (!nonempty(payerRaw) || typeof payerRaw !== "string" || /\*|#/.test(payerRaw)) {
    return fail("Unmasked payer account or mobile number identifier is required");
  }

  // Validate receiver / payee identifier
  const receiver = object(targetReceipt.receiver);
  const payeeRaw = receiver?.mobileNumber ?? receiver?.accountNumber ?? receiver?.id;
  if (!nonempty(payeeRaw) || typeof payeeRaw !== "string" || /\*|#/.test(payeeRaw)) {
    return fail("Unmasked payee account or mobile number identifier is required");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "pk/easypaisa",
      transactionId,
      payer: {
        id: payerRaw,
        scheme: "pk-easypaisa-account",
        provenance: "receipt.sender.mobileNumber",
      },
      payee: {
        id: payeeRaw,
        scheme: "pk-easypaisa-account",
        provenance: "receipt.receiver.mobileNumber",
      },
      amountMinor: minorBigInt.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: /** @type {string} */ (status),
      timestamp: ts,
      timestampMeaning: "executionTimestamp",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this unauthenticated client-side parser.",
        "COMPLETED/SUCCESS status is sender-bank observation, not proof of recipient credit or finality.",
        "Payer/Payee identities are Easypaisa mobile/wallet references, not verified legal persons.",
        "Transaction ID is scoped to Easypaisa ledger activity; no cross-bank deduplication is claimed.",
        "Raw banking response stayed in local memory and is not published.",
      ],
    },
  };
}
