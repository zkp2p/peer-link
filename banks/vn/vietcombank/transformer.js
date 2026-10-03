/**
 * Pure, read-only Vietcombank transaction interpretation. No login, network or signing.
 *
 * Expects a normalized JSON object representing one transaction detail screen
 * from the VCB Digibank mobile app. The caller is responsible for capturing
 * and shaping the raw response into this object; the adapter only validates
 * and interprets it.
 *
 * VND has no minor unit in common use; amounts are whole Vietnamese đồng
 * represented as non-negative integers.
 *
 * @param {unknown} input A VCB Digibank transaction detail object.
 * @param {string} transactionId Selected Vietcombank transaction reference (mã giao dịch).
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function interpretVietcombank(input, transactionId) {
  const fail = (/** @type {string} */ reason) =>
    /** @type {const} */ ({ outcome: "insufficient_evidence", reason });
  const object = (/** @type {unknown} */ v) =>
    v !== null && typeof v === "object" && !Array.isArray(v)
      ? /** @type {Record<string, unknown>} */ (v)
      : null;
  const nonempty = (/** @type {unknown} */ v) =>
    typeof v === "string" && v.trim().length > 0;

  const root = object(input);
  if (!root) return fail("Expected a JSON object");

  if (!nonempty(transactionId)) return fail("A transaction ID is required");

  // --- Transaction reference ---
  const rawId = root.transactionId ?? root.transaction_id ?? root.reference;
  if (typeof rawId !== "string" || !/^\d{9,15}$/.test(rawId.trim()))
    return fail("Transaction ID must be a 9–15 digit numeric string");
  const normalizedId = rawId.trim();
  if (normalizedId !== transactionId.trim())
    return fail("Transaction ID in the payload does not match the requested ID");

  // --- Status ---
  const rawStatus = root.status ?? root.transactionStatus;
  if (typeof rawStatus !== "string") return fail("Missing transaction status");
  const statusLower = rawStatus.trim().toLowerCase();
  const successMarkers = ["success", "thành công", "completed", "successful"];
  if (!successMarkers.some((m) => statusLower.includes(m)))
    return fail(`Transaction is not bank-reported completed (got: ${rawStatus.trim().slice(0, 40)})`);

  // --- Transfer type: only intra-bank is supported ---
  const rawType = root.transferType ?? root.transfer_type ?? root.channelType;
  if (typeof rawType !== "string") return fail("Missing transfer type");
  const typeLower = rawType.trim().toLowerCase();
  const intraBankMarkers = ["intra_bank", "intrabank", "chuyển tiền trong vietcombank", "within vietcombank", "same bank"];
  if (!intraBankMarkers.some((m) => typeLower.includes(m)))
    return { outcome: "unsupported", reason: "Only outgoing intra-bank (Vietcombank-to-Vietcombank) transfers are supported" };

  // --- Amount ---
  const rawAmount = root.amount ?? root.transactionAmount;
  if (typeof rawAmount !== "number" || !Number.isFinite(rawAmount) || rawAmount <= 0)
    return fail("Expected a finite positive VND amount");
  if (!Number.isInteger(rawAmount))
    return fail("VND amounts must be whole numbers (no minor unit)");
  if (rawAmount > Number.MAX_SAFE_INTEGER)
    return fail("Amount exceeds safe integer range");
  const amountMinor = BigInt(rawAmount);
  if (amountMinor <= 0n) return fail("Amount must be positive");

  // --- Currency ---
  const rawCurrency = root.currency ?? root.currencyCode;
  if (rawCurrency !== undefined && rawCurrency !== null && typeof rawCurrency === "string" && rawCurrency.trim().toUpperCase() !== "VND")
    return fail(`Conflicting currency: expected VND, got ${rawCurrency.trim().toUpperCase()}`);

  // --- Timestamp ---
  const rawTimestamp = root.timestamp ?? root.transactionTime ?? root.transactionDate;
  if (typeof rawTimestamp !== "string" || !nonempty(rawTimestamp))
    return fail("Missing or invalid timestamp");
  let isoTimestamp;
  try {
    const parsed = parseVcbTimestamp(rawTimestamp);
    if (!parsed) return fail(`Cannot parse timestamp: ${rawTimestamp.trim().slice(0, 40)}`);
    isoTimestamp = parsed;
  } catch {
    return fail(`Cannot parse timestamp: ${rawTimestamp.trim().slice(0, 40)}`);
  }

  // --- Recipient (payee) ---
  const recipient = object(root.recipient ?? root.beneficiary ?? root.payee);
  if (!recipient) return fail("Missing recipient object");
  const payeeAccount = recipient.accountNumber ?? recipient.account ?? recipient.accountId;
  if (typeof payeeAccount !== "string" || !/^\d{6,20}$/.test(payeeAccount.trim()))
    return fail("Recipient account number must be 6–20 digits");
  const payeeName = recipient.name ?? recipient.accountName ?? recipient.fullName;
  if (typeof payeeName !== "string" || !nonempty(payeeName))
    return fail("Recipient name is missing or empty");
  const payeeBank = recipient.bank ?? recipient.bankName ?? recipient.bankShortName;
  if (typeof payeeBank !== "string" || !nonempty(payeeBank))
    return fail("Recipient bank name is missing");

  // --- Payer (sender) ---
  const payerAccount = root.senderAccount ?? root.sender_account ?? root.fromAccount;
  if (typeof payerAccount !== "string" || !/^\d{6,20}$/.test(payerAccount.trim()))
    return fail("Sender account number must be 6–20 digits");
  const payerName = root.senderName ?? root.sender_name;
  if (typeof payerName !== "string" || !nonempty(payerName))
    return fail("Sender name is missing or empty");

  // --- Fee ---
  const rawFee = root.fee ?? root.feeAmount ?? root.transferFee;
  const feeValue = typeof rawFee === "number" && Number.isFinite(rawFee) && rawFee >= 0 ? rawFee : 0;

  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "vn/vietcombank",
      transactionId: normalizedId,
      payer: {
        id: payerAccount.trim(),
        scheme: "vn-vietcombank-account",
        provenance: "transaction.senderAccount",
      },
      payee: {
        id: `${payeeBank.trim()}:${payeeAccount.trim()}`,
        scheme: "vn-bank-account",
        provenance: "transaction.recipient",
      },
      amountMinor: amountMinor.toString(),
      currency: "VND",
      currencyExponent: 0,
      direction: "outgoing",
      status: "completed",
      timestamp: isoTimestamp,
      timestampMeaning: "transactionTime",
      sourceAuthenticated: false,
      fee: { amountMinor: "0", currency: "VND" },
      limitations: [
        "Input authenticity is not established by this parser.",
        "Completed is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a Vietcombank account reference, not a verified legal person.",
        "Transaction ID is local to Vietcombank; no cross-bank deduplication is claimed.",
        "VND amount precision is whole đồng; no minor unit exists in common use.",
        "Transfer type is self-reported by the sender app; the parser cannot verify intra-bank routing independently.",
      ],
    },
  };
}

/**
 * Parse a VCB Digibank timestamp string into an ISO-8601 UTC string.
 *
 * Accepted formats:
 *   - "DD/MM/YYYY HH:MM" (Vietnamese locale, ICT = UTC+7)
 *   - "YYYY-MM-DDTHH:MM:SS[.mmm]Z" (ISO-8601)
 *   - "YYYY-MM-DD HH:MM:SS" (assumed ICT)
 *
 * @param {string} raw
 * @returns {string|null} ISO-8601 UTC timestamp or null if unparseable.
 */
function parseVcbTimestamp(raw) {
  const trimmed = raw.trim();

  // ISO-8601 with Z or offset
  const isoMatch = trimmed.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2}))$/);
  if (isoMatch) {
    const date = new Date(trimmed);
    if (!Number.isFinite(date.getTime())) return null;
    return date.toISOString();
  }

  // Vietnamese format: "HH:MM DayName DD/MM/YYYY" (assumed ICT = UTC+7)
  // Parse by splitting instead of regex to avoid Unicode day-name matching issues.
  const vnParts = trimmed.split(/\s+/);
  if (vnParts.length >= 3) {
    const timeMatch = vnParts[0].match(/^(\d{1,2}):(\d{2})$/);
    const dateMatch = vnParts[vnParts.length - 1].match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (timeMatch && dateMatch) {
      const [, hh, mm] = timeMatch;
      const [, dd, mo, yyyy] = dateMatch;
      const date = new Date(Date.UTC(+yyyy, +mo - 1, +dd, +hh - 7, +mm, 0));
      if (!Number.isFinite(date.getTime())) return null;
      return date.toISOString();
    }
  }

  // Generic "YYYY-MM-DD HH:MM:SS" (assumed ICT = UTC+7)
  const genericMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/);
  if (genericMatch) {
    const [, yyyy, mo, dd, hh, mm, ss] = genericMatch;
    const date = new Date(Date.UTC(+yyyy, +mo - 1, +dd, +hh - 7, +mm, +ss));
    if (!Number.isFinite(date.getTime())) return null;
    return date.toISOString();
  }

  return null;
}
