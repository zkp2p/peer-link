/**
 * Shared contract for every adapter in banks/<country>/<bank>/. Contributors get these checks
 * without writing them: every fixture's expected output is enforced, supported observations
 * must satisfy the PaymentObservation contract and convert to an attestation candidate, and
 * malformed input or an absent selection must abstain without throwing. Bank-specific negative
 * cases still belong in the adapter's own transformer.test.ts.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";
import { toAttestationCandidate } from "../lib/attestation-candidate";
import type { Interpretation, PaymentObservation } from "../lib/types";

const root = fileURLToPath(new URL(".", import.meta.url));
type Fixture = {
  file: string;
  transactionId: string;
  input: unknown;
  expected: Record<string, unknown> & { outcome: string };
};
type Adapter = {
  id: string;
  currencies: string[];
  interpret: (input: unknown, transactionId: string) => Interpretation;
  fixtures: Fixture[];
};

const manifests = readdirSync(root, { recursive: true, encoding: "utf8" })
  .map((file) => file.replaceAll("\\", "/"))
  .filter((file) => /^[a-z]{2}\/[a-z0-9-]+\/manifest\.json$/.test(file))
  .sort();
const adapters: Adapter[] = await Promise.all(
  manifests.map(async (file) => {
    const folder = join(root, file, "..");
    const manifest = JSON.parse(readFileSync(join(root, file), "utf8"));
    const module = await import(pathToFileURL(join(folder, "transformer.js")).href);
    const fixtureDir = join(folder, "fixtures");
    const fixtures = readdirSync(fixtureDir)
      .filter((name) => name.endsWith(".json"))
      .sort()
      .map((name) => ({
        file: relative(root, join(fixtureDir, name)),
        ...JSON.parse(readFileSync(join(fixtureDir, name), "utf8")),
      }));
    return {
      id: manifest.id,
      currencies: manifest.currencies,
      interpret: module[manifest.entrypoint],
      fixtures,
    };
  }),
);

const OBSERVATION_KEYS = [
  "schemaVersion",
  "provider",
  "transactionId",
  "payer",
  "payee",
  "amountMinor",
  "currency",
  "currencyExponent",
  "direction",
  "status",
  "timestamp",
  "timestampMeaning",
  "sourceAuthenticated",
  "limitations",
].sort();
const nonEmpty = (v: unknown) => typeof v === "string" && v.trim().length > 0;

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

/** Shape rules every adapter result must satisfy, whatever the bank. */
function checkInterpretation(result: Interpretation) {
  expect(
    ["supported", "insufficient_evidence", "unsupported"],
    "outcome is supported, insufficient_evidence or unsupported",
  ).toContain(result.outcome);
  if (result.outcome !== "supported") {
    expect(Object.keys(result).sort(), "abstentions are { outcome, reason }").toEqual([
      "outcome",
      "reason",
    ]);
    expect(nonEmpty(result.reason), "abstentions explain a non-empty reason").toBe(true);
  }
  expect(JSON.parse(JSON.stringify(result)), "results are plain JSON values").toEqual(result);
}

function checkObservation(adapter: Adapter, fixture: Fixture, payment: PaymentObservation) {
  const rule = (message: string) => `${fixture.file}: ${message} (see lib/types.ts)`;
  expect(
    Object.keys(payment).sort(),
    rule("payment has exactly the PaymentObservation fields"),
  ).toEqual(OBSERVATION_KEYS);
  expect(payment.schemaVersion, rule('schemaVersion is "2"')).toBe("2");
  expect(payment.provider, rule("provider equals the manifest id")).toBe(adapter.id);
  expect(payment.transactionId, rule("transactionId echoes the selected ID")).toBe(
    fixture.transactionId,
  );
  for (const party of [payment.payer, payment.payee]) {
    expect(Object.keys(party).sort(), rule("payer/payee are { id, scheme, provenance }")).toEqual([
      "id",
      "provenance",
      "scheme",
    ]);
    expect(
      [party.id, party.scheme, party.provenance].every(nonEmpty),
      rule("payer/payee id, scheme and provenance are non-empty strings"),
    ).toBe(true);
  }
  expect(payment.amountMinor, rule("amountMinor is positive integer minor units")).toMatch(
    /^[1-9]\d*$/,
  );
  expect(adapter.currencies, rule("currency is listed in manifest currencies")).toContain(
    payment.currency,
  );
  expect(
    Number.isInteger(payment.currencyExponent) &&
      payment.currencyExponent >= 0 &&
      payment.currencyExponent <= 6,
    rule("currencyExponent is an integer from 0 to 6"),
  ).toBe(true);
  expect(["incoming", "outgoing"], rule("direction is incoming or outgoing")).toContain(
    payment.direction,
  );
  expect(nonEmpty(payment.status), rule("status preserves the bank's non-empty status")).toBe(true);
  expect(nonEmpty(payment.timestampMeaning), rule("timestampMeaning names the bank field")).toBe(
    true,
  );
  expect(payment.sourceAuthenticated, rule("sourceAuthenticated is false")).toBe(false);
  expect(
    payment.limitations.length > 0 && payment.limitations.every(nonEmpty),
    rule("limitations lists at least one non-empty limitation"),
  ).toBe(true);
  // Throws unless amount, currency, timestamp and identity are attestation-ready.
  expect(
    () => toAttestationCandidate({ outcome: "supported", payment }),
    rule("observation converts with toAttestationCandidate (UTC timestamp, exact amount)"),
  ).not.toThrow();
}

const fieldOf: Record<string, (p: PaymentObservation) => unknown> = {
  payerId: (p) => p.payer.id,
  payeeId: (p) => p.payee.id,
  payerScheme: (p) => p.payer.scheme,
  payeeScheme: (p) => p.payee.scheme,
};

describe.each(adapters)("adapter contract: $id", (adapter) => {
  it("exports the manifest entrypoint", () => expect(typeof adapter.interpret).toBe("function"));

  it.each(adapter.fixtures)("matches the expected output of $file", (fixture) => {
    const input = deepFreeze(structuredClone(fixture.input));
    let result: Interpretation | undefined;
    expect(() => {
      result = adapter.interpret(input, fixture.transactionId);
    }, "adapters must not throw or mutate their input").not.toThrow();
    if (!result) throw new Error("No result");
    checkInterpretation(result);
    expect(
      adapter.interpret(structuredClone(fixture.input), fixture.transactionId),
      `${fixture.file}: the same input must give the same result`,
    ).toEqual(result);
    expect(result.outcome, `${fixture.file}: expected.outcome`).toBe(fixture.expected.outcome);
    if (result.outcome === "supported") {
      checkObservation(adapter, fixture, result.payment);
      const payment = result.payment;
      for (const [key, value] of Object.entries(fixture.expected))
        if (key !== "outcome")
          expect(
            fieldOf[key]?.(payment) ?? payment[key as keyof PaymentObservation],
            `${fixture.file}: expected.${key} (derive it from the bank record, not the parser)`,
          ).toEqual(value);
    } else if (typeof fixture.expected.reason === "string")
      expect(result.reason, `${fixture.file}: expected.reason`).toBe(fixture.expected.reason);
  });

  it("abstains without throwing on malformed input or an absent selection", () => {
    const selected = adapter.fixtures.find((f) => f.expected.outcome === "supported");
    if (!selected) throw new Error("Each adapter needs a supported fixture");
    const cases: [unknown, string][] = [
      ...[undefined, null, true, 0, "", "x", [], {}, { data: null }, { data: [] }].map(
        (input) => [input, selected.transactionId] as [unknown, string],
      ),
      [selected.input, ""],
      [selected.input, "peer-link-absent-transaction-id"],
    ];
    for (const [input, transactionId] of cases) {
      const label = `${adapter.id}: input ${JSON.stringify(input === selected.input ? "<fixture>" : input) ?? "undefined"} with transaction ID ${JSON.stringify(transactionId)}`;
      let result: Interpretation | undefined;
      expect(() => {
        result = adapter.interpret(deepFreeze(structuredClone(input)), transactionId);
      }, `${label} must return insufficient_evidence, not throw`).not.toThrow();
      if (!result) throw new Error("No result");
      checkInterpretation(result);
      expect(result.outcome, `${label} must not be supported`).not.toBe("supported");
    }
  });
});

it("discovers at least one adapter", () => expect(adapters.length).toBeGreaterThan(0));
