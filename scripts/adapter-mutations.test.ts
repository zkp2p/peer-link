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
        p.label === "transactions.0 (missing)" &&
        (p.input as typeof input).transactions.length === 0,
    ),
  ).toBe(true);
  expect(probes.map((p) => p.label).join("\n")).not.toContain("SYNTHETIC_PRIVATE_VALUE");
  expect(probes).toEqual([...malformedInputs(input)]);
});

it("compacts missing array entries so every probe remains representable as JSON", () => {
  const probes = [...malformedInputs({ rows: [{ id: "first" }, { id: "second" }] })];
  expect(probes.find((probe) => probe.label === "rows.0 (missing)")?.input).toEqual({
    rows: [{ id: "second" }],
  });
  for (const probe of probes) expect(JSON.parse(JSON.stringify(probe.input))).toEqual(probe.input);
});

it("does not invent a field schema for scalar or empty responses", () => {
  for (const input of [null, 1, "x", [], {}]) expect([...malformedInputs(input)]).toEqual([]);
});
