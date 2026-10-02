import { expect, it } from "vitest";
import fixture from "../banks/us/mercury/fixtures/sent.synthetic.json";
import { interpretMercury } from "../banks/us/mercury/transformer.js";
import type { Interpretation } from "../lib/types";
import { BANK_ID, formatMinor, shapeOf, summarize } from "./harness-rules";

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

it("describes a response shape without values", () => {
  const shape = shapeOf({
    data: {
      transactions: [
        {
          id: "txn-9f3a",
          status: "sent",
          kind: "outgoing Wire",
          currency: "USD",
          amount: -123.45,
          count: 2,
          postedAt: "2026-01-15T12:00:00.123Z",
          bookedAt: "2026-01-15T12:00:00+07:00",
          day: "2026-01-15",
          accountNumber: "000123456789",
          balance: "-10.50",
          masked: "••••1234",
          email: "someone@bank.example",
          uuid: "123e4567-e89b-12d3-a456-426614174000",
          ok: true,
          note: null,
        },
        {},
        {},
        {},
      ],
      acct_12345678: { name: "Jane" },
      "a@b": 1,
    },
  });
  expect(shape).toEqual({
    data: {
      transactions: [
        {
          id: "<string length 8>",
          status: "sent",
          kind: "outgoing Wire",
          currency: "USD",
          amount: "<number negative, 2 decimals>",
          count: "<number, integer>",
          postedAt: "<string length 24, datetime UTC>",
          bookedAt: "<string length 25, datetime with offset>",
          day: "<string length 10, date>",
          accountNumber: "<string length 12, digits 12>",
          balance: "<string length 6, decimal 2 places, negative>",
          masked: "<string length 8, masked>",
          email: "<string length 20, contains @>",
          uuid: "<string length 36, uuid>",
          ok: true,
          note: null,
        },
        {},
        {},
        "<1 more items>",
      ],
      "<id-like key 1>": { name: "<string length 4>" },
      "<id-like key 2>": "<number, integer>",
    },
  });
  expect(JSON.stringify(shape)).not.toMatch(/Jane|123\.45|000123456789|someone/);
  expect(shapeOf({ status: "Jane Doe the third with a long name!" })).toEqual({
    status: "<string length 36>",
  });
  let deep: unknown = 1;
  for (let i = 0; i < 20; i++) deep = [deep];
  expect(JSON.stringify(shapeOf(deep))).toContain("nested too deep");
});
