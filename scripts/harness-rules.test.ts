import { expect, it } from "vitest";
import fixture from "../banks/us/mercury/fixtures/sent.synthetic.json";
import { interpretMercury } from "../banks/us/mercury/transformer.js";
import type { Interpretation } from "../lib/types";
import { BANK_ID, formatMinor, summarize } from "./harness-rules";

it("summarizes a supported payment without full identifiers", () => {
  const summary = summarize(interpretMercury(fixture.input, fixture.transactionId));
  expect(summary).toEqual({
    outcome: "supported",
    provider: "us/mercury",
    transactionId: "...-001",
    payer: { scheme: "mercury-party-id", provenance: "transaction.primaryPartyId", id: "...ount" },
    payee: {
      scheme: "us-routing-account",
      provenance: "transaction.details.domesticWireRoutingInfo",
      id: "...0001",
    },
    amount: "123.45 USD",
    direction: "outgoing",
    status: "sent",
    timestamp: "2026-01-15T12:00:00.000Z",
    timestampMeaning: "postedAt",
    limitations: 5,
  });
  expect(JSON.stringify(summary)).not.toContain("000000000:000000000001");
});

it("passes abstentions through and tolerates malformed adapter results", () => {
  expect(summarize({ outcome: "unsupported", reason: "ACH" })).toEqual({
    outcome: "unsupported",
    reason: "ACH",
  });
  expect(summarize(null as unknown as Interpretation)).toEqual({ outcome: "invalid-result" });
  const broken = summarize({ outcome: "supported" } as unknown as Interpretation);
  expect(broken).toMatchObject({ outcome: "invalid-result", amount: "invalid undefined" });
  const short = summarize({
    outcome: "supported",
    payment: { payer: { id: "ab" }, payee: {}, amountMinor: "5", currencyExponent: 0 },
  } as unknown as Interpretation);
  expect(short).toMatchObject({ payer: { id: "**" }, payee: { id: "" }, limitations: 0 });
});

it.each([
  ["12345", 2, "123.45"],
  ["5", 2, "0.05"],
  ["25000", 0, "25000"],
  ["1", 3, "0.001"],
  ["x", 2, "invalid"],
  ["1", -1, "invalid"],
])("formats %s with exponent %i as %s", (minor, exponent, text) =>
  expect(formatMinor(minor, exponent)).toBe(text),
);

it("accepts only country/bank identifiers", () => {
  expect(BANK_ID.test("ua/monobank")).toBe(true);
  for (const id of ["../x", "ua/../../x", "UA/monobank", "ua/mono_bank", "ua"])
    expect(BANK_ID.test(id)).toBe(false);
});
