import { expect, it } from "vitest";
import { malformedInputs } from "./adapter-mutations";

it("probes nested records and array entries without changing the original or echoing values", () => {
  const input = { transactions: [{ time: 123, optional: "SYNTHETIC_PRIVATE_VALUE" }] };
  const original = structuredClone(input);
  const probes = [...malformedInputs(input)];
  expect(input).toEqual(original);
  expect(
    probes.some(
      (p) =>
        p.label === "transactions.0.time (large number)" &&
        (p.input as typeof input).transactions[0].time === 1e308,
    ),
  ).toBe(true);
  expect(
    probes.some(
      (p) =>
        p.label === "transactions.0 (missing)" && !(0 in (p.input as typeof input).transactions),
    ),
  ).toBe(true);
  expect(probes.map((p) => p.label).join("\n")).not.toContain("SYNTHETIC_PRIVATE_VALUE");
  expect(probes).toEqual([...malformedInputs(input)]);
});

it("does not invent a field schema for scalar or empty responses", () => {
  for (const input of [null, 1, "x", [], {}]) expect([...malformedInputs(input)]).toEqual([]);
});
