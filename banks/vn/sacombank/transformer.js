/**
 * Pure, read-only Sacombank (Ngân hàng TMCP Sài Gòn Thương Tín) transaction interpretation.
 * No login, network, or cryptographic signing.
 * @param {unknown} input A Sacombank transaction history response.
 * @param {string} transactionId Selected transaction reference ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretSacombank(input, transactionId) {
  const fail = (/** @type {string} */ reason) =>
    /** @type {const} */ ({ outcome: "insufficient_evidence", reason });
  const object = (/** @type {unknown} */ v) =>
    v !== null && typeof v === "object" && !Array.isArray(v)
      ? /** @type {Record<string, unknown>} */ (v)
      : null;
  const nonempty = (/** @type {unknown} */ v) =>
    typeof v === "string" && v.trim().length > 0;

  const root = object(input);
  const data = object(root?.data);
  if (!data || !Array.isArray(data.transactions) || !Array.isArray(data.accounts))
    return fail("Expected transactions and accounts arrays");

  if (!nonempty(transactionId)) return fail("A transaction ID is required");

  const rows = data.transactions.filter(
    (row) => object(row)?.id === transactionId,
  );
  if (rows.length !== 1)
    return fail("Selected transaction must occur exactly once in this page");

  const row = object(rows[0]);
  if (!row) return fail("Invalid transaction");

  const details = object(row.details);
  if (!details || (details.kind !== "napas247Transfer" && details.kind !== "domesticTransfer"))
    return {
      outcome: "unsupported",
      reason: "Only outgoing domestic VND transfers (Napas 247 or domestic) are supported",
    };

  if (row.status !== "SUCCESS" && row.status !== "COMPLETED")
    return fail("Transaction is not bank-reported successful");

  if (row.pending === true) return fail("Pending transactions are not final");

  if (!Array.isArray(row.holds) || row.holds.length !== 0)
    return fail("Active holds must be present and empty");

  if (row.disputed !== false)
    return fail("Disputed state is not supported or transaction is disputed");

  if (typeof row.amount !== "number" || !Number.isFinite(row.amount) || row.amount >= 0)
    return fail("Expected a finite negative VND debit");

  // VND minor unit exponent is 0 (integer VND). Check whole number.
  const decimal = String(-row.amount);
  if (!/^(0|[1-9]\d*)$/.test(decimal))
    return fail("VND amount must be an integer");

  const cents = BigInt(decimal);
  if (cents <= 0n || cents > BigInt(Number.MAX_SAFE_INTEGER))
    return fail("Amount outside supported range");

  if (row.currency !== undefined && row.currency !== "VND")
    return fail("Conflicting currency: only VND supported");

  if (
    typeof row.postedAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/.test(row.postedAt)
  )
    return fail("Expected a UTC postedAt timestamp");

  const date = new Date(row.postedAt);
  if (
    !Number.isFinite(date.getTime()) ||
    date.toISOString().slice(0, 19) !== row.postedAt.slice(0, 19)
  )
    return fail("Invalid postedAt timestamp");

  const recipientAccount = details.recipientAccount;
  const recipientBankCode = details.recipientBankCode;
  if (
    typeof recipientAccount !== "string" ||
    !/^\d{6,20}$/.test(recipientAccount) ||
    typeof recipientBankCode !== "string" ||
    !/^\d{4,8}$/.test(recipientBankCode)
  )
    return fail("Full recipient account and bank code are required");

  if (!nonempty(row.accountId))
    return fail("Payer account identifier is missing");

  const accounts = data.accounts.filter(
    (acc) => object(acc)?.id === row.accountId,
  );
  if (
    accounts.length !== 1 ||
    object(accounts[0])?.type !== "paymentChecking"
  )
    return fail("Payer must resolve to exactly one active paymentChecking account");

  const account = object(accounts[0]);
  if (!account) return fail("Invalid account object");

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "vn/sacombank",
      transactionId,
      payer: {
        id: /** @type {string} */ (account.id),
        scheme: "sacombank-account-id",
        provenance: "transaction.accountId",
      },
      payee: {
        id: `${recipientBankCode}:${recipientAccount}`,
        scheme: "vn-bank-account",
        provenance: "transaction.details",
      },
      amountMinor: cents.toString(),
      currency: "VND",
      currencyExponent: 0,
      direction: "outgoing",
      status: "sent",
      timestamp: row.postedAt,
      timestampMeaning: "postedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "Sent is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a Sacombank account reference, not a verified legal person.",
        "Transaction ID is local to this bank; no cross-bank deduplication is claimed.",
        "VND is inferred from the supported domestic transfer surface.",
      ],
    },
  };
}
