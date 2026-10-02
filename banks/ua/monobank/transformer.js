/**
 * Pure, read-only Monobank transaction interpretation. No login, network, clock, randomness or logging.
 * Interprets completed outgoing domestic UAH transfers from Monobank statement items.
 * @param {unknown} input The statement envelope from Monobank personal API.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretMonobank(input, transactionId) {
  const CURRENCY = "UAH";
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
    return fail("Expected account and transactions");
  }

  if (!text(transactionId)) {
    return fail("A transaction ID is required");
  }

  const rows = root.transactions.filter((item) => object(item)?.id === transactionId);
  if (rows.length !== 1) {
    return fail("Selected transaction must occur exactly once");
  }

  const row = /** @type {Record<string, unknown>} */ (rows[0]);

  const rawType = typeof row.type === "string" ? row.type : "";
  const rawDescription = typeof row.description === "string" ? row.description : "";
  const typeLower = rawType.toLowerCase();
  const descLower = rawDescription.toLowerCase();

  // Out-of-scope payment rail exclusions
  if (
    typeLower.includes("atm") ||
    /\batm\b/i.test(descLower) ||
    descLower.includes("банкомат") ||
    descLower.includes("готівк") ||
    typeLower.includes("cash")
  ) {
    return {
      outcome: "unsupported",
      reason: "Cash withdrawals and ATM operations are outside scope",
    };
  }

  if (
    typeLower.includes("utility") ||
    descLower.includes("комунал") ||
    descLower.includes("поповнення мобільного") ||
    descLower.includes("оплата послуг")
  ) {
    return { outcome: "unsupported", reason: "Utility and service payments are outside scope" };
  }

  if (
    typeLower.includes("merchant") ||
    typeLower.includes("pos") ||
    descLower.includes("покупка") ||
    descLower.includes("магазин")
  ) {
    return {
      outcome: "unsupported",
      reason: "Merchant purchases and POS debits are outside scope",
    };
  }

  // Active authorization hold check
  if (row.hold === true) {
    return fail("Transaction has an active hold and is not settled");
  }

  // Direction filter
  const isCredit = row.direction === "credit" || (typeof row.amount === "number" && row.amount > 0);
  if (isCredit) {
    return { outcome: "unsupported", reason: "Only outgoing debit movements are supported" };
  }

  // Currency validation
  const isUahCurrency =
    row.currency === CURRENCY || row.currencyCode === 980 || row.currencyCode === "980";
  if (!isUahCurrency) {
    return fail("Missing or conflicting currency");
  }

  // Status check
  if (typeof row.status === "string") {
    const finalStatuses = new Set(["completed", "settled", "success", "LIQUIDADA", "USPIKH"]);
    if (!finalStatuses.has(row.status)) {
      return fail("Transaction is not bank-reported completed");
    }
  }

  // Amount parsing
  let minor = 0n;
  if (typeof row.amount === "number" && Number.isFinite(row.amount)) {
    const intAmount = Math.round(row.amount);
    if (intAmount >= 0 && row.direction !== "debit") {
      return fail("Amount must be negative or debit");
    }
    const absMinor = Math.abs(intAmount);
    if (absMinor === 0) {
      return fail("Amount must be positive");
    }
    minor = BigInt(absMinor);
  } else if (typeof row.amount === "string") {
    const amountMatch = /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount);
    const fraction = amountMatch?.[2] ?? "";
    if (!amountMatch || fraction.length > EXPONENT) {
      return fail("Amount must be a decimal string within currency precision");
    }
    minor =
      BigInt(amountMatch[1]) * 10n ** BigInt(EXPONENT) +
      BigInt(fraction.padEnd(EXPONENT, "0") || "0");
    if (minor <= 0n) {
      return fail("Amount must be positive");
    }
  } else {
    return fail("Invalid amount format");
  }

  // Timestamp parsing
  let isoTimestamp = "";
  if (typeof row.timeIso === "string") {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.timeIso)) {
      return fail("Expected an explicit UTC timestamp");
    }
    const timeMs = Date.parse(row.timeIso);
    if (
      !Number.isFinite(timeMs) ||
      new Date(timeMs).toISOString().slice(0, 19) !== row.timeIso.slice(0, 19)
    ) {
      return fail("Invalid timestamp");
    }
    isoTimestamp = row.timeIso;
  } else if (typeof row.time === "number" && Number.isFinite(row.time) && row.time > 0) {
    const timeMs = Math.round(row.time) * 1000;
    isoTimestamp = new Date(timeMs).toISOString();
  } else {
    return fail("Missing or invalid transaction timestamp");
  }

  // Payer account identification
  const payerIban = typeof account.iban === "string" ? account.iban : null;
  const payerIdRaw = typeof account.id === "string" ? account.id : null;

  let payerId = "";
  let payerScheme = "";
  let payerProvenance = "";

  if (payerIban !== null) {
    const cleanIban = payerIban.replace(/[-\s]/g, "");
    if (cleanIban.includes("*") || cleanIban.includes("•")) {
      return fail("Masked payer account identifier is insufficient");
    }
    payerId = cleanIban;
    payerScheme = /^UA\d{27}$/i.test(cleanIban) ? "ua-iban" : "iban";
    payerProvenance = "account.iban";
  } else if (payerIdRaw !== null && text(payerIdRaw)) {
    const cleanId = payerIdRaw.trim();
    if (cleanId.includes("*") || cleanId.includes("•")) {
      return fail("Masked payer identifier is insufficient");
    }
    payerId = cleanId;
    payerScheme = "monobank-account-id";
    payerProvenance = "account.id";
  } else {
    return fail("Payer account identifier is missing");
  }

  // Payee counterparty identification
  const counterparty = object(row.counterparty);
  const payeeIban = typeof counterparty?.iban === "string" ? counterparty.iban : null;
  const payeeAccount =
    typeof counterparty?.accountNumber === "string" ? counterparty.accountNumber : null;
  const payeeIdRaw = typeof counterparty?.id === "string" ? counterparty.id : null;

  let payeeId = "";
  let payeeScheme = "";
  let payeeProvenance = "";

  if (payeeIban !== null) {
    const cleanIban = payeeIban.replace(/[-\s]/g, "");
    if (cleanIban.includes("*") || cleanIban.includes("•")) {
      return fail("Masked recipient account identifier is insufficient");
    }
    payeeId = cleanIban;
    payeeScheme = /^UA\d{27}$/i.test(cleanIban) ? "ua-iban" : "iban";
    payeeProvenance = "transaction.counterparty.iban";
  } else if (payeeAccount !== null) {
    const cleanAccount = payeeAccount.replace(/[-\s]/g, "");
    if (cleanAccount.includes("*") || cleanAccount.includes("•")) {
      return fail("Masked recipient account identifier is insufficient");
    }
    payeeId = cleanAccount;
    payeeScheme = "ua-account-number";
    payeeProvenance = "transaction.counterparty.accountNumber";
  } else if (payeeIdRaw !== null && text(payeeIdRaw)) {
    const cleanId = payeeIdRaw.trim();
    if (cleanId.includes("*") || cleanId.includes("•")) {
      return fail("Masked recipient identifier is insufficient");
    }
    payeeId = cleanId;
    payeeScheme = "counterparty-id";
    payeeProvenance = "transaction.counterparty.id";
  } else {
    return fail("Full recipient IBAN or account identifier is required");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "ua/monobank",
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
      status: "completed",
      timestamp: isoTimestamp,
      timestampMeaning: "time",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not cryptographically proven by this parser.",
        "Settled status is reported by the sender bank, not proof of recipient credit.",
        "Payer and payee identities are bank and IBAN references, not verified legal persons.",
        "Transactions with active holds, card purchases, and utility payments are excluded.",
        "Transaction ID is scoped to this statement envelope.",
      ],
    },
  };
}
