/**
 * Pure, read-only Bank of America transaction interpretation. No login, network or signing.
 * @param {unknown} input A Bank of America web activity-detail response.
 * @param {string} transactionId Selected Bank of America activity ID.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretBankOfAmerica(input, transactionId) {
  const fail = (/** @type {string} */ reason) =>
    /** @type {const} */ ({ outcome: "insufficient_evidence", reason });
  const object = (/** @type {unknown} */ v) =>
    v !== null && typeof v === "object" && !Array.isArray(v)
      ? /** @type {Record<string, unknown>} */ (v)
      : null;
  const nonempty = (/** @type {unknown} */ v) => typeof v === "string" && v.trim().length > 0;

  const root = object(input);
  const data = object(root?.data);
  if (!data || !Array.isArray(data.activities)) return fail("Expected activities array in data");
  if (!nonempty(transactionId)) return fail("A transaction ID is required");

  const rows = data.activities.filter((row) => object(row)?.id === transactionId);
  if (rows.length !== 1) return fail("Selected transaction must occur exactly once in this page");

  const row = object(rows[0]);
  if (!row) return fail("Invalid transaction");

  const details = object(row.details);
  const paymentMethod =
    typeof details?.paymentMethod === "string" ? details.paymentMethod : row.paymentMethod;
  const activityType = typeof row.type === "string" ? row.type : "";

  if (activityType === "ZELLE_CREDIT")
    return { outcome: "unsupported", reason: "Only outgoing USD Zelle payments are supported" };

  if (paymentMethod !== "Zelle" && activityType !== "ZELLE_DEBIT")
    return { outcome: "unsupported", reason: "Only outgoing USD Zelle payments are supported" };

  if (row.status !== "COMPLETED") return fail("Transaction is not bank-reported completed");

  if (row.hold === true || (Array.isArray(row.activeHolds) && row.activeHolds.length > 0))
    return fail("Active holds must be absent or empty");

  if (row.disputeStatus && row.disputeStatus !== "NONE" && row.disputeStatus !== "NOT_DISPUTED")
    return fail("Dispute state is not supported");

  if (typeof row.amount !== "number" || !Number.isFinite(row.amount) || row.amount >= 0)
    return fail("Expected a finite negative USD debit");

  const decimal = String(-row.amount);
  if (!/^(0|[1-9]\d*)(\.\d{1,2})?$/.test(decimal))
    return fail("Amount must have at most two decimals");

  const [whole, fraction = ""] = decimal.split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (cents <= 0n || cents > BigInt(Number.MAX_SAFE_INTEGER))
    return fail("Amount outside supported range");

  if (row.currency !== undefined && row.currency !== "USD") return fail("Conflicting currency");

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

  const recipient = object(row.recipient);
  if (!recipient || typeof recipient.token !== "string" || !recipient.token.trim())
    return fail("Recipient token is required");

  const token = recipient.token.trim();
  let payeeId = "";
  let payeeScheme = "";
  if (
    /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/.test(
      token,
    )
  ) {
    payeeId = token.toLowerCase();
    payeeScheme = "email";
  } else if (/^\+[1-9]\d{1,14}$/.test(token)) {
    payeeId = token;
    payeeScheme = "tel";
  } else {
    return fail("Recipient token must be a valid email or E.164 phone identifier");
  }

  const sender = object(row.sender);
  if (!sender || typeof sender.accountId !== "string" || !sender.accountId.trim())
    return fail("Payer account identifier is missing");

  const payerAccountId = sender.accountId.trim();

  if (Array.isArray(data.accounts)) {
    const matchingAccounts = data.accounts.filter((a) => object(a)?.id === payerAccountId);
    if (matchingAccounts.length !== 1)
      return fail("Payer must resolve to exactly one account in envelope");
  }

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "us/bank-of-america",
      transactionId,
      payer: {
        id: payerAccountId,
        scheme: "bofa-account-id",
        provenance: "transaction.sender.accountId",
      },
      payee: {
        id: payeeId,
        scheme: payeeScheme,
        provenance: "transaction.recipient.token",
      },
      amountMinor: cents.toString(),
      currency: "USD",
      currencyExponent: 2,
      direction: "outgoing",
      status: "COMPLETED",
      timestamp: row.postedAt,
      timestampMeaning: "postedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "COMPLETED is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a Bank of America account reference, not a verified legal person.",
        "Payee identity is a Zelle email or telephone token, not a validated bank routing or legal entity.",
        "Transaction ID is local to Bank of America activity records; no cross-bank deduplication is claimed.",
        "USD is inferred from the supported Bank of America domestic Zelle surface.",
      ],
    },
  };
}
