import { expect, it } from "vitest";
import fixture from "../banks/us/mercury/fixtures/sent.synthetic.json";
import { interpretMercury } from "../banks/us/mercury/transformer.js";
import { matchPayment } from "./match";
import type { Interpretation, PaymentObservation } from "./types";

const observation = interpretMercury(fixture.input, fixture.transactionId);
const claim = {
  payerId: "synthetic-payer-account",
  payeeId: "000000000:000000000001",
  amountMinor: "12345",
  currency: "USD",
};
const payment = () => {
  if (observation.outcome !== "supported") throw new Error("Invalid synthetic fixture");
  return observation.payment;
};
it("matches all payment facts", () =>
  expect(matchPayment(observation, claim).outcome).toBe("supported"));
it.each(["payerId", "payeeId", "amountMinor", "currency"] as const)(
  "rejects mismatching %s and names the field",
  (key) => {
    const value = { payerId: "other", payeeId: "other", amountMinor: "999", currency: "EUR" }[key];
    expect(matchPayment(observation, { ...claim, [key]: value })).toMatchObject({
      outcome: "contradicted",
      mismatched: [key],
    });
  },
);
it.each([
  { amountMinor: "0" },
  { amountMinor: "012345" },
  { amountMinor: "123.45" },
  { payerId: "" },
  { payeeId: "" },
  { payeeId: " 000000000:000000000001" },
  { currency: "usd" },
  { payeeScheme: "" },
  { notBefore: "2026-01-15" },
  { notAfter: "2026-01-15T12:00:00+07:00" },
])("requires a well-formed claim %j", (patch) =>
  expect(matchPayment(observation, { ...claim, ...patch }).outcome).toBe("insufficient_evidence"),
);
it("compares identifier schemes when the claim names them", () => {
  expect(
    matchPayment(observation, {
      ...claim,
      payerScheme: "mercury-party-id",
      payeeScheme: "us-routing-account",
    }).outcome,
  ).toBe("supported");
  expect(
    matchPayment(observation, { ...claim, payerScheme: "email", payeeScheme: "iban" }),
  ).toMatchObject({ outcome: "contradicted", mismatched: ["payerScheme", "payeeScheme"] });
});
it("enforces an inclusive UTC time window", () => {
  const at = "2026-01-15T12:00:00.000Z";
  expect(matchPayment(observation, { ...claim, notBefore: at, notAfter: at }).outcome).toBe(
    "supported",
  );
  expect(
    matchPayment(observation, { ...claim, notBefore: "2026-01-15T12:00:00.001Z" }),
  ).toMatchObject({ outcome: "contradicted", mismatched: ["notBefore"] });
  expect(matchPayment(observation, { ...claim, notAfter: "2026-01-15T11:59:59Z" })).toMatchObject({
    outcome: "contradicted",
    mismatched: ["notAfter"],
  });
});
it.each([
  { schemaVersion: "1" },
  { sourceAuthenticated: true },
  { amountMinor: "012345" },
  { timestamp: "2026-01-15T12:00:00" },
])("does not match an observation outside the contract %j", (patch) => {
  const malformed = { outcome: "supported", payment: { ...payment(), ...patch } } as Interpretation;
  expect(matchPayment(malformed, claim).outcome).toBe("insufficient_evidence");
});
it("preserves insufficient evidence", () =>
  expect(matchPayment({ outcome: "insufficient_evidence", reason: "missing" }, claim)).toEqual({
    outcome: "insufficient_evidence",
    reason: "missing",
  }));
it("keeps the observation for a contradicted claim", () => {
  const result = matchPayment(observation, { ...claim, amountMinor: "1" });
  expect(
    result.outcome === "contradicted" && (result.payment as PaymentObservation).transactionId,
  ).toBe("synthetic-wire-001");
});
