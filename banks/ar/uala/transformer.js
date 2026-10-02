/**
 * Pure, read-only Ualá Argentina interpretation. No login, network, clock, randomness or logging.
 * Interprets outgoing completed ARS transfers by CVU/CBU/alias from Ualá mobile receipts.
 *
 * @param {unknown} input The response envelope the bank page or app loaded.
 * @param {string} transactionId The explicitly selected transaction.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretUala(input, transactionId) {
  const CURRENCY = "ARS";
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
    txType !== "TRANSFER_OUTGOING" &&
    txType !== "DOMESTIC_TRANSFER" &&
    txType !== "TRANSFER" &&
    txType !== "CVU_TRANSFER"
  ) {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic transfers are supported on this surface",
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
  if (status !== "COMPLETED" && status !== "APROBADA" && status !== "EXITOSA") {
    return fail("Transaction status is not bank-reported COMPLETED, APROBADA, or EXITOSA");
  }

  // Gate currency
  if (targetReceipt.currency !== CURRENCY) {
    return fail(`Currency must be ${CURRENCY}`);
  }

  // Parse amount in fixed-point centavos without floating-point math
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

  // Validate settlement timestamp
  const ts =
    targetReceipt.settlementTimestamp ??
    targetReceipt.timestamp ??
    targetReceipt.executionTimestamp;
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
  const payerRaw = sender?.cvu ?? sender?.accountId ?? sender?.cbu ?? sender?.id;
  if (!nonempty(payerRaw) || typeof payerRaw !== "string" || /\*|#/.test(payerRaw)) {
    return fail("Unmasked payer CVU or account identifier is required");
  }

  // Validate receiver / payee identifier
  const receiver = object(targetReceipt.receiver);
  const payeeRaw = receiver?.cvu ?? receiver?.cbu ?? receiver?.alias ?? receiver?.accountId;
  if (!nonempty(payeeRaw) || typeof payeeRaw !== "string" || /\*|#/.test(payeeRaw)) {
    return fail("Unmasked payee CVU, CBU, or registered alias identifier is required");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "ar/uala",
      transactionId,
      payer: {
        id: payerRaw,
        scheme: "ar-cvu",
        provenance: "receipt.sender.cvu",
      },
      payee: {
        id: payeeRaw,
        scheme: "ar-cvu",
        provenance: "receipt.receiver.cvu",
      },
      amountMinor: minorBigInt.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: /** @type {string} */ (status),
      timestamp: ts,
      timestampMeaning: "settlementTimestamp",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this unauthenticated client-side parser.",
        "COMPLETED/APROBADA status is sender-bank observation, not proof of recipient credit or finality.",
        "Payer/Payee identities are Argentine banking CVU/alias references, not verified legal persons.",
        "Transaction ID is scoped to Ualá/COELSA ledger activity; no cross-bank deduplication is claimed.",
        "Raw banking response stayed in local memory and is not published.",
      ],
    },
  };
}
