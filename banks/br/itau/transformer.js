/**
 * Pure, read-only Itau Brazil transaction interpretation. No login, network, clock, randomness or logging.
 * Interprets completed outgoing domestic BRL Pix transfers from Itau Brazil account statements.
 * @param {unknown} input The response envelope from Itau Brazil statement/extrato.
 * @param {string} transactionId The explicitly selected transaction ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretItauBrazil(input, transactionId) {
  const CURRENCY = "BRL";
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

  const rows = root.transactions.filter((item) => {
    const rowObj = object(item);
    return rowObj?.id === transactionId || rowObj?.endToEndId === transactionId;
  });

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
    /\bted\b/i.test(rawType) ||
    /\bted\b/i.test(rawDescription) ||
    /\bdoc\b/i.test(rawType) ||
    /\bdoc\b/i.test(rawDescription)
  ) {
    return {
      outcome: "unsupported",
      reason: "TED and DOC transfers are outside this adapter scope",
    };
  }

  if (
    typeLower.includes("boleto") ||
    descLower.includes("boleto") ||
    typeLower.includes("convenio") ||
    descLower.includes("convenio")
  ) {
    return { outcome: "unsupported", reason: "Boleto and utility bill payments are outside scope" };
  }

  if (
    typeLower.includes("cartao") ||
    descLower.includes("cartao") ||
    /\bcard\b/i.test(rawType) ||
    /\bcard\b/i.test(rawDescription)
  ) {
    return { outcome: "unsupported", reason: "Card purchases are outside scope" };
  }

  if (
    typeLower.includes("saque") ||
    descLower.includes("saque") ||
    /\batm\b/i.test(rawType) ||
    /\batm\b/i.test(rawDescription)
  ) {
    return { outcome: "unsupported", reason: "ATM cash withdrawals are outside scope" };
  }

  // Direction filter: only outgoing debit transactions
  if (row.direction !== "debit") {
    return { outcome: "unsupported", reason: "Only outgoing debit movements are supported" };
  }

  // Supported transaction types
  const supportedTypes = new Set([
    "pix",
    "pixTransfer",
    "pix_transfer",
    "transferencia_pix",
    "pix_enviado",
    "pix_debito",
    "transfer",
  ]);

  if (!supportedTypes.has(rawType)) {
    return { outcome: "unsupported", reason: "Only outgoing domestic Pix transfers are supported" };
  }

  // Terminal completed status verification
  const finalStatuses = new Set([
    "completed",
    "LIQUIDADA",
    "EFETIVADA",
    "SUCCESS",
    "CONCLUIDA",
    "REALIZADA",
  ]);

  const rawStatus = typeof row.status === "string" ? row.status : "";
  if (!finalStatuses.has(rawStatus)) {
    return fail("Transaction is not bank-reported completed");
  }

  // Currency validation
  if (row.currency !== CURRENCY) {
    return fail("Missing or conflicting currency");
  }

  // Amount parsing
  const amountMatch =
    typeof row.amount === "string" ? /^(0|[1-9]\d{0,14})(?:\.(\d+))?$/.exec(row.amount) : null;
  const fraction = amountMatch?.[2] ?? "";
  if (!amountMatch || fraction.length > EXPONENT) {
    return fail("Amount must be a decimal string within currency precision");
  }

  const minor =
    BigInt(amountMatch[1]) * 10n ** BigInt(EXPONENT) +
    BigInt(fraction.padEnd(EXPONENT, "0") || "0");
  if (minor <= 0n) {
    return fail("Amount must be positive");
  }

  // Booked timestamp validation
  if (
    typeof row.bookedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.bookedAt)
  ) {
    return fail("Expected an explicit UTC timestamp");
  }

  const timeMs = Date.parse(row.bookedAt);
  if (
    !Number.isFinite(timeMs) ||
    new Date(timeMs).toISOString().slice(0, 19) !== row.bookedAt.slice(0, 19)
  ) {
    return fail("Invalid timestamp");
  }

  // Payer account identification
  const payerAgency = typeof account.agency === "string" ? account.agency : null;
  const payerAccount = typeof account.accountNumber === "string" ? account.accountNumber : null;
  const payerPixKey = typeof account.pixKey === "string" ? account.pixKey : null;
  const payerCpf = typeof account.cpf === "string" ? account.cpf : null;

  let payerId = "";
  let payerScheme = "";
  let payerProvenance = "";

  if (payerAgency !== null && payerAccount !== null) {
    const cleanAgency = payerAgency.replace(/[-\s]/g, "");
    const cleanAccount = payerAccount.replace(/[-\s]/g, "");
    if (
      cleanAgency.includes("*") ||
      cleanAccount.includes("*") ||
      cleanAgency.includes("•") ||
      cleanAccount.includes("•")
    ) {
      return fail("Masked payer account identifier is insufficient");
    }
    payerId = `${cleanAgency}:${cleanAccount}`;
    payerScheme = "br-itau-agency-account";
    payerProvenance = "account.agency:account.accountNumber";
  } else if (payerPixKey !== null) {
    const cleanKey = payerPixKey.trim();
    if (cleanKey.includes("*") || cleanKey.includes("•")) {
      return fail("Masked payer Pix key is insufficient");
    }
    payerId = cleanKey;
    payerScheme = "pix-key";
    payerProvenance = "account.pixKey";
  } else if (payerCpf !== null) {
    const cleanCpf = payerCpf.replace(/[-\s.]/g, "");
    if (cleanCpf.includes("*") || cleanCpf.includes("•")) {
      return fail("Masked payer CPF identifier is insufficient");
    }
    payerId = cleanCpf;
    payerScheme = "br-cpf";
    payerProvenance = "account.cpf";
  } else if (text(account.id)) {
    const cleanId = String(account.id).trim();
    if (cleanId.includes("*") || cleanId.includes("•")) {
      return fail("Masked payer identifier is insufficient");
    }
    payerId = cleanId;
    payerScheme = "itau-account-id";
    payerProvenance = "account.id";
  } else {
    return fail("Payer account identifier is missing");
  }

  // Payee counterparty identification
  const counterparty = object(row.counterparty);
  const payeePixKey = typeof counterparty?.pixKey === "string" ? counterparty.pixKey : null;
  const payeeAgency = typeof counterparty?.agency === "string" ? counterparty.agency : null;
  const payeeAccount =
    typeof counterparty?.accountNumber === "string" ? counterparty.accountNumber : null;

  let payeeId = "";
  let payeeScheme = "";
  let payeeProvenance = "";

  if (payeePixKey !== null) {
    const keyRaw = payeePixKey.trim();
    if (keyRaw.includes("*") || keyRaw.includes("•")) {
      return fail("Masked recipient Pix key is insufficient");
    }
    const digitsOnly = keyRaw.replace(/[\s-]/g, "");
    if (/^\+?55\d{10,11}$/.test(digitsOnly)) {
      payeeId = digitsOnly;
      payeeScheme = "br-pix-phone";
    } else if (keyRaw.includes("@")) {
      payeeId = keyRaw.replace(/\s/g, "");
      payeeScheme = "br-pix-email";
    } else if (/^\d{11}$/.test(digitsOnly)) {
      payeeId = digitsOnly;
      payeeScheme = "br-pix-cpf";
    } else if (/^\d{14}$/.test(digitsOnly)) {
      payeeId = digitsOnly;
      payeeScheme = "br-pix-cnpj";
    } else if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(keyRaw)) {
      payeeId = keyRaw.toLowerCase();
      payeeScheme = "br-pix-random";
    } else {
      payeeId = keyRaw;
      payeeScheme = "pix-key";
    }
    payeeProvenance = "transaction.counterparty.pixKey";
  } else if (payeeAgency !== null && payeeAccount !== null) {
    const cleanAgency = payeeAgency.replace(/[-\s]/g, "");
    const cleanAccount = payeeAccount.replace(/[-\s]/g, "");
    if (
      cleanAgency.includes("*") ||
      cleanAccount.includes("*") ||
      cleanAgency.includes("•") ||
      cleanAccount.includes("•")
    ) {
      return fail("Masked recipient account identifier is insufficient");
    }
    payeeId = `${cleanAgency}:${cleanAccount}`;
    payeeScheme = "br-agency-account";
    payeeProvenance = "transaction.counterparty.agency:accountNumber";
  } else if (text(counterparty?.id)) {
    const cleanId = String(counterparty?.id).trim();
    if (cleanId.includes("*") || cleanId.includes("•")) {
      return fail("Masked recipient identifier is insufficient");
    }
    payeeId = cleanId;
    payeeScheme = "counterparty-id";
    payeeProvenance = "transaction.counterparty.id";
  } else {
    return fail("Full recipient Pix key or account identifier is required");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "br/itau",
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
      timestamp: row.bookedAt,
      timestampMeaning: "bookedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not cryptographically proven by this parser.",
        "Bank-reported completed status does not guarantee irreversible recipient settlement.",
        "Payer and payee identities are bank and Pix references, not verified legal persons.",
        "TED, DOC, boleto, and card transactions are excluded.",
        "Transaction ID is scoped to this extrato statement.",
      ],
    },
  };
}
