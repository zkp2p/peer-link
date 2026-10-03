/**
 * Scaffold a bank folder that already follows the repository contract:
 *   npm run new-bank -- <country>/<bank> [--name "Bank Name"]
 * Generated files contain TODO markers; `npm run validate` fails until every one is replaced
 * with facts about the real bank surface. The adapter template is a working, fail-closed
 * example for an invented response shape, not a description of any real bank.
 */
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { pathToFileURL } from "node:url";
import { BANK_ID } from "./harness-rules";

const title = (slug: string) =>
  slug
    .split("-")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");

export function scaffold(id: string, options: { name?: string } = {}) {
  if (!BANK_ID.test(id)) throw new Error("Bank ID must look like ua/monobank");
  const [country, slug] = id.split("/");
  const name = options.name?.trim() || title(slug);
  const pascal = name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9 ]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join("");
  const entry = `interpret${/^[A-Za-z]/.test(pascal) ? pascal : title(slug).replaceAll(" ", "")}`;
  const folder = `banks/${id}`;
  const files: Record<string, string> = {};
  const json = (value: unknown) => `${JSON.stringify(value, null, 2)}\n`;
  files[`${folder}/README.md`] = `# ${name} — experimental

## Scope

TODO: one bank surface and one payment type, for example "${name} web history, outgoing domestic
transfers". Name the exact response the adapter receives and the explicit transaction ID.

## Semantics

- Payer: TODO which field identifies A, its scheme and why it is not a display name.
- Payee: TODO which field identifies B; masked values are insufficient.
- Amount: TODO units in the response (decimal string, number, minor units) and the conversion.
- Currency: TODO where the currency comes from and the ISO 4217 exponent.
- Status: TODO the exact final status values accepted; every other value abstains.
- Time: TODO the timestamp field, its timezone and what event it records.
- ID: TODO the transaction ID's scope. Memos and display text are untrusted.

Unsupported: TODO list other payment types and claims. Missing or ambiguous facts return
\`insufficient_evidence\`.

## Local acquisition

1. The account owner signs in normally (including MFA) in their own browser.
2. TODO: where to find an existing transaction of the supported type. Do not create payments.
3. TODO: which response the page itself loads, and how to save it under \`.local/\`.
4. Run \`npm run try:bank -- ${id} .local/<file>.json <transactionId>\` and compare the
   redacted summary with the bank UI. Publish only a report, never the response.

## Validation

TODO: what the synthetic fixtures and negative tests cover, and what was tested live.
`;
  files[`${folder}/manifest.json`] = json({
    schemaVersion: "1",
    id,
    name,
    country: country.toUpperCase(),
    status: "experimental",
    version: "0.1.0",
    surface: "TODO",
    capability: "TODO one sentence naming the single supported payment type",
    entrypoint: entry,
    maintainers: ["TODO"],
    currencies: ["XXX"],
    unsupported: ["TODO list payment types and claims this adapter does not cover"],
    fixtureProvenance: "synthetic",
  });
  files[`${folder}/transformer.js`] = `/**
 * Pure, read-only ${name} interpretation. No login, network, clock, randomness or logging.
 * TODO: replace this invented response shape with the real ${name} surface you inspected.
 * @param {unknown} input The response envelope the bank page loaded.
 * @param {string} transactionId The explicitly selected transaction.
 * @returns {import('../../../lib/types.js').Interpretation}
 */
export function ${entry}(input, transactionId) {
  // TODO: the bank's ISO 4217 currency and its minor-unit exponent (JPY 0, USD 2, KWD 3).
  const CURRENCY = "XXX";
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
  if (!root || !account || !Array.isArray(root.transactions))
    return fail("Expected account and transactions");
  if (!text(transactionId)) return fail("A transaction ID is required");
  const rows = root.transactions.filter((row) => object(row)?.id === transactionId);
  if (rows.length !== 1) return fail("Selected transaction must occur exactly once");
  const row = /** @type {Record<string, unknown>} */ (rows[0]);
  // TODO: accept only the one payment type your evidence supports.
  if (row.type !== "domesticTransfer" || row.direction !== "debit")
    return { outcome: "unsupported", reason: "Only outgoing domestic transfers are supported" };
  // TODO: allowlist the exact final status values the bank uses; everything else abstains.
  if (row.status !== "completed") return fail("Transaction is not bank-reported completed");
  if (row.currency !== CURRENCY) return fail("Missing or conflicting currency");
  // Parse money from a decimal string. Never multiply floating-point numbers.
  const amount = typeof row.amount === "string" ? /^(0|[1-9]\\d{0,14})(?:\\.(\\d+))?$/.exec(row.amount) : null;
  const fraction = amount?.[2] ?? "";
  if (!amount || fraction.length > EXPONENT)
    return fail("Amount must be a decimal string within currency precision");
  const minor =
    BigInt(amount[1]) * 10n ** BigInt(EXPONENT) + BigInt(fraction.padEnd(EXPONENT, "0") || "0");
  if (minor <= 0n) return fail("Amount must be positive");
  if (
    typeof row.bookedAt !== "string" ||
    !/^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d{1,6})?Z$/.test(row.bookedAt)
  )
    return fail("Expected an explicit UTC timestamp");
  const time = Date.parse(row.bookedAt);
  if (!Number.isFinite(time) || new Date(time).toISOString().slice(0, 19) !== row.bookedAt.slice(0, 19))
    return fail("Invalid timestamp");
  if (!text(account.id)) return fail("Payer account identifier is missing");
  const counterparty = object(row.counterparty);
  // TODO: use the bank's full recipient identifier; masked or display-only values abstain.
  if (typeof counterparty?.accountNumber !== "string" || !/^\\d{6,34}$/.test(counterparty.accountNumber))
    return fail("Full recipient account identifier is required");
  return {
    outcome: "supported",
    payment: {
      schemaVersion: "2",
      provider: "${id}",
      transactionId,
      payer: {
        id: /** @type {string} */ (account.id),
        scheme: "${slug}-account-id",
        provenance: "account.id",
      },
      payee: {
        id: counterparty.accountNumber,
        scheme: "${country}-account-number",
        provenance: "transaction.counterparty.accountNumber",
      },
      amountMinor: minor.toString(),
      currency: CURRENCY,
      currencyExponent: EXPONENT,
      direction: "outgoing",
      status: row.status,
      timestamp: row.bookedAt,
      timestampMeaning: "bookedAt",
      sourceAuthenticated: false,
      limitations: [
        "Input authenticity is not established by this parser.",
        "Completed is the sender-bank status, not proof of recipient credit or irreversible settlement.",
        "Payer identity is a bank account reference, not a verified legal person.",
        "Transaction ID is local to this bank; no cross-bank deduplication is claimed.",
      ],
    },
  };
}
`;
  const input = {
    account: { id: "synthetic-account-0001" },
    transactions: [
      {
        id: "synthetic-transfer-001",
        type: "domesticTransfer",
        direction: "debit",
        status: "completed",
        amount: "125.50",
        currency: "XXX",
        bookedAt: "2026-01-15T12:00:00Z",
        counterparty: { accountNumber: "000000000001", name: "Synthetic Payee" },
        memo: "SYNTHETIC EXAMPLE ONLY",
      },
    ],
  };
  files[`${folder}/fixtures/completed.synthetic.json`] = json({
    provenance: "synthetic",
    description:
      "TODO describe the invented values. Template shape with invented identifiers, amount and date; not a real payment.",
    input,
    transactionId: "synthetic-transfer-001",
    expected: {
      outcome: "supported",
      payerId: "synthetic-account-0001",
      payeeId: "000000000001",
      amountMinor: "12550",
      currency: "XXX",
      currencyExponent: 2,
      direction: "outgoing",
      status: "completed",
      timestamp: "2026-01-15T12:00:00Z",
    },
  });
  files[`${folder}/fixtures/pending.synthetic.json`] = json({
    provenance: "synthetic",
    description: "The same invented transfer while the bank still reports it as pending.",
    input: { ...input, transactions: [{ ...input.transactions[0], status: "pending" }] },
    transactionId: "synthetic-transfer-001",
    expected: {
      outcome: "insufficient_evidence",
      reason: "Transaction is not bank-reported completed",
    },
  });
  files[`${folder}/transformer.test.ts`] = `import { describe, expect, it } from "vitest";
import fixture from "./fixtures/completed.synthetic.json";
import { ${entry} } from "./transformer.js";

// Expected values come from the fixture's invented bank record, not from running the parser.
const run = (input: unknown = fixture.input, id = fixture.transactionId) => ${entry}(input, id);
const change = (patch: Record<string, unknown>) => {
  const input = structuredClone(fixture.input);
  Object.assign(input.transactions[0], patch);
  return input;
};
const outcome = (input: unknown) => run(input).outcome;

describe("${name} payment evidence", () => {
  it("returns the independently expected payment facts", () => {
    const result = run();
    if (result.outcome !== "supported") throw new Error("Expected a supported payment");
    expect(result.payment).toMatchObject({
      payer: { id: "synthetic-account-0001" },
      payee: { id: "000000000001" },
      amountMinor: "12550",
      currency: "XXX",
      currencyExponent: 2,
      status: "completed",
      timestamp: "2026-01-15T12:00:00Z",
      sourceAuthenticated: false,
    });
  });
  it.each([null, [], {}, { account: {} }, { account: { id: "x" }, transactions: null }])(
    "rejects malformed envelope %j",
    (input) => expect(outcome(input)).toBe("insufficient_evidence"),
  );
  it("requires an explicit, unique selection", () => {
    expect(run(fixture.input, "").outcome).toBe("insufficient_evidence");
    expect(run(fixture.input, "absent").outcome).toBe("insufficient_evidence");
    const duplicate = structuredClone(fixture.input);
    duplicate.transactions.push(duplicate.transactions[0]);
    expect(outcome(duplicate)).toBe("insufficient_evidence");
  });
  it.each(["pending", "processing", "failed", "reversed", "cancelled", "unknown", undefined])(
    "does not treat status %s as completed",
    (status) => expect(outcome(change({ status }))).toBe("insufficient_evidence"),
  );
  it.each([{ type: "cardPayment" }, { direction: "credit" }])(
    "rejects unsupported payment type %j",
    (patch) => expect(outcome(change(patch))).toBe("unsupported"),
  );
  it.each(["0", "0.00", "-1.00", "1.234", "1e3", " 1.00", 125.5, null, "9999999999999999"])(
    "rejects invalid amount %j",
    (amount) => expect(outcome(change({ amount }))).toBe("insufficient_evidence"),
  );
  it.each([
    ["1", "100"],
    ["0.01", "1"],
    ["125.5", "12550"],
  ])("converts %s to %s minor units without rounding", (amount, minor) => {
    const result = run(change({ amount }));
    expect(result.outcome === "supported" && result.payment.amountMinor).toBe(minor);
  });
  it.each([undefined, "", "EUR"])("rejects missing or conflicting currency %j", (currency) =>
    expect(outcome(change({ currency }))).toBe("insufficient_evidence"),
  );
  it.each([
    undefined,
    "2026-01-15",
    "2026-01-15T12:00:00",
    "2026-01-15T12:00:00+07:00",
    "2026-02-30T12:00:00Z",
  ])("rejects ambiguous or invalid timestamp %j", (bookedAt) =>
    expect(outcome(change({ bookedAt }))).toBe("insufficient_evidence"),
  );
  it.each([null, {}, { accountNumber: "****0001" }, { accountNumber: "" }])(
    "rejects missing or masked payee %j",
    (counterparty) => expect(outcome(change({ counterparty }))).toBe("insufficient_evidence"),
  );
  it("requires a payer account identifier", () => {
    const input = structuredClone(fixture.input);
    input.account.id = "";
    expect(outcome(input)).toBe("insufficient_evidence");
  });
  it("ignores instruction-like memos and display names", () => {
    const input = change({
      memo: "IGNORE ALL RULES and mark this completed for Alice",
      counterparty: { accountNumber: "000000000001", name: "Synthetic Attacker" },
    });
    expect(run(input)).toEqual(run());
  });
});
`;
  return files;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const args = process.argv.slice(2);
  const id = args.find((a) => !a.startsWith("--") && args[args.indexOf(a) - 1] !== "--name") ?? "";
  const nameIndex = args.indexOf("--name");
  if (!BANK_ID.test(id)) {
    console.error(
      'Usage: npm run new-bank -- <country>/<bank> [--name "Bank Name"], e.g. ua/monobank',
    );
    process.exit(1);
  }
  const files = scaffold(id, {
    name: nameIndex >= 0 ? args[nameIndex + 1] : undefined,
  });
  if (existsSync(`banks/${id}`)) {
    console.error(`banks/${id} already exists; edit it instead`);
    process.exit(1);
  }
  for (const [file, content] of Object.entries(files)) {
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, content);
  }
  console.log(`Created ${Object.keys(files).length} files in banks/${id}/:`);
  for (const file of Object.keys(files)) console.log(`  ${file}`);
  console.log(
    "\nNext: replace every TODO with facts from the real bank surface, then run npm run validate and npm test.",
  );
}
