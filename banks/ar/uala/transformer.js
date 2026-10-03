/**
 * Pure, read-only Uala Argentina transfer interpretation.
 * No login, network, clock, randomness, or logging.
 *
 * @param {unknown} input The response envelope from Uala Argentina.
 * @param {string} transactionId The explicitly selected transaction ID.
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
  const text = (/** @type {unknown} */ v) => typeof v === "string" && v.trim().length > 0;

  if (!text(transactionId)) return fail("A transaction ID is required");

  const root = object(input);
  if (!root) return fail("Expected response object");

  const account = object(root.account);

  /** @type {unknown[] | null} */
  let txList = null;
  if (Array.isArray(root.transactions)) {
    txList = root.transactions;
  } else if (root.id === transactionId || root.operationId === transactionId) {
    txList = [root];
  }

  if (!txList) {
    return fail("Expected transactions array or matching transaction payload");
  }

  const rows = txList.filter((r) => {
    const obj = object(r);
    return obj?.id === transactionId || obj?.operationId === transactionId;
  });
  if (rows.length !== 1) {
    return fail("Selected transaction must occur exactly once");
  }

  const row = /** @type {Record<string, unknown>} */ (rows[0]);

  const rawType = row.type ?? row.transactionType;
  if (rawType !== "cvuTransfer" && rawType !== "transfer" && rawType !== "transferencia") {
    return {
      outcome: "unsupported",
      reason: "Only outgoing ARS CVU and alias transfers are supported",
    };
  }

  if (row.direction !== "debit" && row.direction !== "outgoing") {
    return {
      outcome: "unsupported",
      reason: "Only outgoing debit transfers are supported",
    };
  }

  const completedStatuses = ["COMPLETED", "APROBADA", "EXITOSA", "REALIZADA"];
  if (typeof row.status !== "string" || !completedStatuses.includes(row.status)) {
    return fail("Transaction is not bank-reported completed");
  }

  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency: only ARS is supported");
  }

  const amountStr = typeof row.amount === "string" ? row.amount.trim() : null;
  const amountMatch = amountStr ? /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(amountStr) : null;
  const fraction = amountMatch?.[2] ?? "";
  if (!amountMatch || fraction.length > EXPONENT) {
    return fail("Amount must be a decimal string within currency precision");
  }
  const minor = BigInt(amountMatch[1]) * 100n + BigInt(fraction.padEnd(EXPONENT, "0"));
  if (minor <= 0n) return fail("Amount must be positive");

  if (
    typeof row.timestamp !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.timestamp)
  ) {
    return fail("Expected an explicit UTC timestamp");
  }
  const timeMs = Date.parse(row.timestamp);
  if (
    !Number.isFinite(timeMs) ||
    new Date(timeMs).toISOString().slice(0, 19) !== row.timestamp.slice(0, 19)
  ) {
    return fail("Invalid timestamp calendar date");
  }

  const payerObj = object(row.payer) ?? account;
  const payerCvu =
    typeof payerObj?.cvu === "string" && /^\d{22}$/.test(payerObj.cvu) ? payerObj.cvu : null;
  const payerAlias =
    typeof payerObj?.alias === "string" && /^[a-zA-Z0-9.]{6,30}$/.test(payerObj.alias)
      ? payerObj.alias
      : null;
  const payerAccId =
    typeof payerObj?.id === "string" && /^[a-zA-Z0-9_-]{6,32}$/.test(payerObj.id)
      ? payerObj.id
      : null;

  const payerId = payerCvu ?? payerAlias ?? payerAccId;
  if (!payerId) {
    return fail("Full unmasked payer CVU, alias, or account identifier is required");
  }
  const payerScheme = payerCvu ? "ar-cvu" : payerAlias ? "ar-alias" : "uala-account-id";
  const payerProvenance = payerCvu ? "payer.cvu" : payerAlias ? "payer.alias" : "payer.id";

  const payeeObj = object(row.payee) ?? object(row.counterparty);
  const payeeCvu =
    typeof payeeObj?.cvu === "string" && /^\d{22}$/.test(payeeObj.cvu) ? payeeObj.cvu : null;
  const payeeCbu =
    typeof payeeObj?.cbu === "string" && /^\d{22}$/.test(payeeObj.cbu) ? payeeObj.cbu : null;
  const payeeAlias =
    typeof payeeObj?.alias === "string" && /^[a-zA-Z0-9.]{6,30}$/.test(payeeObj.alias)
      ? payeeObj.alias
      : null;

  const payeeId = payeeCvu ?? payeeCbu ?? payeeAlias;
  if (!payeeId) {
    return fail("Full unmasked payee CVU, CBU, or alias identifier is required");
  }
  const payeeScheme = payeeCvu ? "ar-cvu" : payeeCbu ? "ar-cbu" : "ar-alias";
  const payeeProvenance = payeeCvu ? "payee.cvu" : payeeCbu ? "payee.cbu" : "payee.alias";

  const coelsaRef =
    typeof row.coelsaId === "string" && row.coelsaId.trim().length > 0 ? row.coelsaId.trim() : null;

  const limitations = [
    "Input authenticity is not established by this parser.",
    "Completed is the sender-app status, not proof of recipient credit or irreversible settlement.",
    "Payer and payee identities are CVU, CBU, or alias identifiers, not verified legal persons.",
    "Transaction ID is local to Uala; no cross-bank deduplication is claimed.",
  ];
  if (coelsaRef) {
    limitations.push(`COELSA reference identifier: ${coelsaRef}`);
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "ar/uala",
      transactionId,
      payer: {
        id: payerId,
        scheme: payerScheme,
        provenance: payerProvenance,
      },
      payee: {
        id: payeeId,
        scheme: payeeScheme,
        provenance: payeeProvenance,
      },
      amountMinor: minor.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: row.status,
      timestamp: row.timestamp,
      timestampMeaning: "operationTime",
      sourceAuthenticated: false,
      limitations,
    },
  };
}
