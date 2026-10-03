/**
 * Pure, read-only Chase transaction interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope or transaction detail from Chase.
 * @param {string} transactionId The explicitly selected transaction ID.
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
  const text = (/** @type {unknown} */ v) => typeof v === "string" && v.trim().length > 0;

  if (!text(transactionId)) return fail("A transaction ID is required");

  const root = object(input);
  const account = object(root?.account);

  let txList = null;
  if (Array.isArray(input)) {
    txList = input;
  } else if (Array.isArray(root?.transactions)) {
    txList = root.transactions;
  } else if (Array.isArray(root?.items)) {
    txList = root.items;
  } else if (Array.isArray(root?.data)) {
    txList = root.data;
  } else if (root?.id === transactionId) {
    txList = [root];
  } else {
    const wrapped = object(root?.transaction) ?? object(root?.data);
    if (wrapped?.id === transactionId) {
      txList = [wrapped];
    }
  }

  if (!txList) {
    return fail("Expected transactions array or matching transaction payload");
  }

  const rows = txList.filter((r) => object(r)?.id === transactionId);
  if (rows.length !== 1) {
    return fail("Selected transaction must occur exactly once");
  }

  const row = /** @type {Record<string, unknown>} */ (rows[0]);

  const rawType = row.type ?? row.transactionType;
  if (
    rawType !== "achTransfer" &&
    rawType !== "achDebit" &&
    rawType !== "ach" &&
    rawType !== "ACH"
  ) {
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic ACH transfers are supported",
    };
  }

  if (row.direction !== "debit" && row.direction !== "outgoing") {
    return { outcome: "unsupported", reason: "Only outgoing debit transfers are supported" };
  }

  if (row.status === "PENDING" || row.status === "PROCESSING" || row.status === "SCHEDULED") {
    return fail("Transaction is still pending bank execution");
  }
  if (row.status === "RETURNED" || row.status === "FAILED" || row.status === "CANCELLED") {
    return fail("Transaction failed or was returned");
  }
  const completedStatuses = ["POSTED", "COMPLETED", "PAID"];
  if (typeof row.status !== "string" || !completedStatuses.includes(row.status)) {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency: only USD is supported");
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
    .replace(/^\$\s*/, "")
    .replace(/^(?:USD)\s*/i, "")
    .replace(/\s*(?:USD)$/i, "")
    .trim();

  let whole = "";
  let fraction = "";

  if (rawAmount.includes(",")) {
    const parts = rawAmount.split(",");
    const last = parts[parts.length - 1];
    if (last.includes(".")) {
      whole = parts.join("").split(".")[0];
      fraction = last.split(".")[1];
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

  if (!/^(0|[1-9]\d{0,14})$/.test(whole) || !/^\d*$/.test(fraction) || fraction.length > EXPONENT) {
    return fail("Amount must be a decimal string within currency precision");
  }

  const minor = BigInt(whole) * 100n + BigInt(fraction.padEnd(EXPONENT, "0"));
  if (minor <= 0n) return fail("Amount must be positive");

  const rawTime = row.postedAt ?? row.timestamp;
  if (
    typeof rawTime !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(rawTime)
  ) {
    return fail("Expected an explicit UTC ISO 8601 timestamp ending with Z");
  }
  const timeMs = Date.parse(rawTime);
  if (
    !Number.isFinite(timeMs) ||
    new Date(timeMs).toISOString().slice(0, 19) !== rawTime.slice(0, 19)
  ) {
    return fail("Invalid timestamp calendar date");
  }

  const payer = object(row.payer) ?? account;
  const rawPayerAcc =
    typeof payer?.accountNumber === "string"
      ? payer.accountNumber
      : typeof payer?.id === "string"
        ? payer.id
        : "";
  if (!text(rawPayerAcc) || /[*•?]/.test(rawPayerAcc)) {
    return fail("Unmasked payer account identifier is required");
  }
  const payerAcc = rawPayerAcc.replace(/[\s-]/g, "");
  if (!/^\d{4,17}$/.test(payerAcc)) {
    return fail("Payer account number must be between 4 and 17 digits");
  }
  const rawPayerRouting = typeof payer?.routingNumber === "string" ? payer.routingNumber : "";
  const payerRouting = rawPayerRouting.replace(/[\s-]/g, "");
  if (text(rawPayerRouting) && !/^\d{9}$/.test(payerRouting)) {
    return fail("Payer routing number must be a nine digit routing number");
  }
  const hasPayerRouting = /^\d{9}$/.test(payerRouting);

  const payee = object(row.payee);
  const rawPayeeRouting = typeof payee?.routingNumber === "string" ? payee.routingNumber : "";
  const payeeRouting = rawPayeeRouting.replace(/[\s-]/g, "");
  if (!/^\d{9}$/.test(payeeRouting)) {
    return fail("Nine digit destination routing number is required");
  }

  const rawPayeeAcc =
    typeof payee?.accountNumber === "string"
      ? payee.accountNumber
      : typeof payee?.id === "string"
        ? payee.id
        : "";
  if (!text(rawPayeeAcc) || /[*•?]/.test(rawPayeeAcc)) {
    return fail("Unmasked counterparty account identifier is required");
  }
  const payeeAcc = rawPayeeAcc.replace(/[\s-]/g, "");
  if (!/^\d{4,17}$/.test(payeeAcc)) {
    return fail("Destination account number must be between 4 and 17 digits");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "us/chase",
      transactionId,
      payer: {
        id: hasPayerRouting ? `${payerRouting}:${payerAcc}` : payerAcc,
        scheme: hasPayerRouting ? "us-routing-account" : "chase-account-number",
        provenance: "account.accountNumber",
      },
      payee: {
        id: `${payeeRouting}:${payeeAcc}`,
        scheme: "us-routing-account",
        provenance: "transaction.payee",
      },
      amountMinor: minor.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: row.status,
      timestamp: rawTime,
      timestampMeaning: "postedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "Posted is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a Chase account reference, not a verified legal person.",
        "Transaction ID is local to Chase; no cross-bank deduplication is claimed.",
        "ACH settlement is subject to Nacha operating rules and return windows.",
      ],
    },
  };
}
