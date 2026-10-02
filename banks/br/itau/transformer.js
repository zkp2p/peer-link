/**
 * Pure, read-only Itaú Pix receipt interpretation. No login, I/O, clock or payment action.
 * @param {unknown} input Captured mobile-app Pix receipt data.
 * @param {string} transactionId The receipt E2E ID, or its local ID when E2E is absent.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretItauBrazil(input, transactionId) {
  const fail = (/** @type {string} */ reason) =>
    /** @type {const} */ ({ outcome: "insufficient_evidence", reason });
  const object = (/** @type {unknown} */ value) =>
    value !== null && typeof value === "object" && !Array.isArray(value)
      ? /** @type {Record<string, unknown>} */ (value)
      : null;
  const text = (/** @type {unknown} */ value) =>
    typeof value === "string" && value.trim() === value && value.length > 0;

  const root = object(input);
  if (!root || !Array.isArray(root.receipts)) return fail("Expected a receipts array");
  if (!text(transactionId)) return fail("A transaction ID is required");
  const rows = root.receipts.filter((candidate) => {
    const row = object(candidate);
    if (!row) return false;
    const e2e = text(row.endToEndId) ? row.endToEndId : undefined;
    return (e2e ?? row.id) === transactionId;
  });
  if (rows.length !== 1) return fail("Selected transaction must occur exactly once");
  const row = object(rows[0]);
  if (!row) return fail("Malformed receipt");
  if (row.type !== "PIX" || row.direction !== "SAIDA")
    return { outcome: "unsupported", reason: "Only outgoing Pix receipts are supported" };
  if (row.status !== "CONCLUIDA")
    return fail("Transaction is not bank-reported CONCLUIDA");
  if (row.currency !== "BRL") return fail("Missing or conflicting BRL currency");

  const amount =
    typeof row.amount === "string"
      ? /^R\$ (0|[1-9]\d{0,2}(?:\.\d{3})*|[1-9]\d*)(?:,(\d{1,2}))?$/.exec(row.amount)
      : null;
  if (!amount) return fail("Amount must be a positive pt-BR BRL display string");
  const whole = amount[1].replaceAll(".", "");
  const minor = BigInt(whole) * 100n + BigInt((amount[2] ?? "").padEnd(2, "0") || "0");
  if (minor <= 0n || minor > BigInt(Number.MAX_SAFE_INTEGER))
    return fail("Amount is outside the supported range");

  if (
    typeof row.completedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-03:00$/.test(row.completedAt)
  )
    return fail("Expected an America/Sao_Paulo completion timestamp with -03:00 offset");
  const instant = Date.parse(row.completedAt);
  if (
    !Number.isFinite(instant) ||
    new Date(instant - 3 * 60 * 60 * 1000).toISOString().slice(0, 19) !==
      row.completedAt.slice(0, 19)
  )
    return fail("Invalid completion timestamp");

  const payer = object(row.payer);
  if (!payer || !text(payer.accountId) || /[*•]/.test(payer.accountId))
    return fail("A full payer account identifier is required");
  const recipient = object(row.recipient);
  const key = object(recipient?.pixKey);
  const keyTypes = ["PHONE", "EMAIL", "CPF", "CNPJ", "RANDOM"];
  if (!key || !keyTypes.includes(/** @type {string} */ (key.type)) || !text(key.value))
    return fail("A typed full recipient Pix key is required");
  const patterns = {
    PHONE: /^\+55\d{10,11}$/,
    EMAIL: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
    CPF: /^\d{3}\.\d{3}\.\d{3}-\d{2}$/,
    CNPJ: /^\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}$/,
    RANDOM: /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
  };
  const pattern = patterns[/** @type {keyof typeof patterns} */ (key.type)];
  if (!pattern.test(/** @type {string} */ (key.value)))
    return fail("Recipient Pix key is malformed or incomplete");
  if (row.endToEndId !== undefined && (!text(row.endToEndId) || row.endToEndId !== transactionId))
    return fail("E2E ID is malformed or does not match the selected transaction");
  if (row.endToEndId === undefined && row.id !== transactionId)
    return fail("Local receipt ID does not match the selected transaction");

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "br/itau",
      transactionId,
      payer: {
        id: /** @type {string} */ (payer.accountId),
        scheme: "itau-account-id",
        provenance: "receipt.payer.accountId",
      },
      payee: {
        id: /** @type {string} */ (key.value),
        scheme: `pix-${/** @type {string} */ (key.type).toLowerCase()}`,
        provenance: "receipt.recipient.pixKey.value",
      },
      amountMinor: minor.toString(),
      currency: "BRL",
      currencyExponent: 2,
      direction: "outgoing",
      status: "CONCLUIDA",
      timestamp: new Date(instant).toISOString(),
      timestampMeaning: "completedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "CONCLUIDA is Itaú sender-bank status, not proof of irreversible settlement.",
        row.endToEndId === undefined
          ? "Itaú did not provide an E2E ID; transactionId is the receipt-local ID."
          : "transactionId is the Itaú-provided Pix E2E ID.",
        "America/Sao_Paulo evidence is limited to an explicit -03:00 offset.",
      ],
    },
  };
}
