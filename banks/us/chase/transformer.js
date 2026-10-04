/**
 * @fileoverview Chase USD Zelle transfer interpreter.
 * Pure function parsing Chase transaction responses.
 */

/**
 * Interpret a Chase response to extract a payment observation.
 * @param {unknown} input
 * @param {string} transactionId
 * @returns {import('../../../lib/types').Interpretation}
 */
export function interpretChase(input, transactionId) {
  if (!input || typeof input !== "object" || typeof transactionId !== "string" || !transactionId.trim()) {
    return { outcome: "insufficient_evidence", reason: "Invalid input or transaction ID" };
  }

  const data = /** @type {any} */ (input);
  const transactions = data?.transactions || data?.data?.transactions;
  if (!Array.isArray(transactions)) {
    return { outcome: "insufficient_evidence", reason: "Missing transactions array" };
  }

  const tx = transactions.find((t) => t && typeof t === "object" && t.id === transactionId);
  if (!tx) {
    return { outcome: "insufficient_evidence", reason: "Transaction not found" };
  }

  const status = typeof tx.status === "string" ? tx.status.toLowerCase() : "";
  if (status !== "completed" && status !== "sent") {
    return { outcome: "insufficient_evidence", reason: "Transaction is not completed or sent" };
  }

  const amount = Number(tx.amount);
  if (isNaN(amount) || amount === 0) {
    return { outcome: "insufficient_evidence", reason: "Invalid or zero amount" };
  }
  const absAmountMinor = Math.round(Math.abs(amount) * 100).toString();
  const direction = amount < 0 ? "outgoing" : "incoming";

  const currency = typeof tx.currency === "string" ? tx.currency.toUpperCase() : "USD";
  if (currency !== "USD") {
    return { outcome: "insufficient_evidence", reason: "Unsupported currency" };
  }

  const payerId = tx.payerPartyId || tx.senderId || tx.payer?.id;
  const payeeId = tx.payeePartyId || tx.recipientId || tx.payee?.id;
  if (!payerId || !payeeId) {
    return { outcome: "insufficient_evidence", reason: "Missing payer or payee identifier" };
  }

  const timestamp = typeof tx.timestamp === "string" ? tx.timestamp : tx.postedAt;
  if (!timestamp || typeof timestamp !== "string") {
    return { outcome: "insufficient_evidence", reason: "Missing timestamp" };
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "us/chase",
      transactionId: tx.id,
      payer: {
        id: String(payerId),
        scheme: "account-id",
        provenance: "bank-response"
      },
      payee: {
        id: String(payeeId),
        scheme: "zelle-handle",
        provenance: "bank-response"
      },
      amountMinor: absAmountMinor,
      currency: "USD",
      currencyExponent: 2,
      direction,
      status: tx.status,
      timestamp,
      timestampMeaning: "postedAt",
      sourceAuthenticated: false,
      limitations: [
        "Synthetically tested Zelle transfer observation.",
        "Source authenticity, legal ownership, and recipient credit are not proven."
      ]
    }
  };
}
