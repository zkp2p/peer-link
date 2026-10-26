/**
 * Pure, read-only Kuda Bank transaction interpretation. No login, network or signing.
 * @param {unknown} input A Kuda Bank transaction envelope or record.
 * @param {string} transactionId Selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretKuda(input, transactionId) {
  const CURRENCY = "NGN";
  const EXPONENT = 2;
  const fail = (/** @type {string} */ reason) =>
    /** @type {const} */ ({ outcome: "insufficient_evidence", reason });
  const object = (/** @type {unknown} */ v) =>
    v !== null && typeof v === "object" && !Array.isArray(v)
      ? /** @type {Record<string, unknown>} */ (v)
      : null;
  const text = (/** @type {unknown} */ v) => typeof v === "string" && v.trim().length > 0;

  const root = object(input);
  if (!root) return fail("Expected a valid object envelope");

  const account = object(root.account);
  if (!account) return fail("Missing account details");

  if (!Array.isArray(root.transactions)) return fail("Expected transactions array");

  if (!text(transactionId)) return fail("A transaction ID is required");

  const rows = root.transactions.filter((row) => object(row)?.id === transactionId);
  if (rows.length !== 1) return fail("Selected transaction must occur exactly once");

  const row = object(rows[0]);
  if (!row) return fail("Invalid transaction record");

  if (row.type !== "domesticTransfer" || row.direction !== "debit") {
    return { outcome: "unsupported", reason: "Only outgoing domestic NGN transfers are supported" };
  }

  if (row.status !== "completed" && row.status !== "successful" && row.status !== "sent") {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) return fail("Missing or conflicting currency");

  if (typeof row.amount !== "string") return fail("Amount must be a decimal string");
  const match = /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount);
  if (!match) return fail("Amount must be a valid positive decimal string");
  const fraction = match[2] ?? "";
  if (fraction.length > EXPONENT) return fail("Amount must have at most two decimal places");
  const minor = BigInt(match[1]) * 100n + BigInt(fraction.padEnd(EXPONENT, "0") || "0");
  if (minor <= 0n) return fail("Amount must be positive");

  if (
    typeof row.postedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.postedAt)
  ) {
    return fail("Expected an explicit UTC timestamp");
  }
  const date = new Date(row.postedAt);
  if (
    !Number.isFinite(date.getTime()) ||
    date.toISOString().slice(0, 19) !== row.postedAt.slice(0, 19)
  ) {
    return fail("Invalid timestamp");
  }

  if (typeof account.accountNumber !== "string" || !/^\d{10}$/.test(account.accountNumber)) {
    return fail("Payer account number must be a 10-digit NUBAN");
  }

  const recipient = object(row.recipient);
  if (
    !recipient ||
    typeof recipient.accountNumber !== "string" ||
    !/^\d{10}$/.test(recipient.accountNumber)
  ) {
    return fail("Full recipient 10-digit NUBAN account identifier is required");
  }
  if (typeof recipient.bankCode !== "string" || !/^\d{3,6}$/.test(recipient.bankCode)) {
    return fail("Recipient bank code must be a 3 to 6 digit CBN bank code");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "ng/kuda",
      transactionId,
      payer: {
        id: account.accountNumber,
        scheme: "kuda-account-number",
        provenance: "account.accountNumber",
      },
      payee: {
        id: `${recipient.bankCode}:${recipient.accountNumber}`,
        scheme: "ng-cbn-nuban",
        provenance: "transaction.recipient",
      },
      amountMinor: minor.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: /** @type {string} */ (row.status),
      timestamp: row.postedAt,
      timestampMeaning: "postedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "Completed is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a Kuda account number, not a verified legal person.",
        "Transaction ID is local to Kuda Bank; no cross-bank deduplication is claimed.",
        "Recipient identity combines CBN bank code and NUBAN account number.",
      ],
    },
  };
}
