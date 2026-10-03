import { describe, it, expect } from "vitest";
import { interpretVietcombank } from "./transformer.js";
import validFixture from "./fixtures/valid-intrabank-transfer.synthetic.json";

const TX_ID = "16000000001";

describe("interpretVietcombank", () => {
  it("accepts a valid intra-bank transfer", () => {
    const result = interpretVietcombank(validFixture, TX_ID);
    expect(result.outcome === "supported").toBe(true);
    if (result.outcome !== "supported") throw new Error(`Got: ${JSON.stringify(result)}`);
    expect(result.payment.currency).toBe("VND");
    expect(result.payment.currencyExponent).toBe(0);
    expect(result.payment.amountMinor).toBe("2500000");
    expect(result.payment.direction).toBe("outgoing");
    expect(result.payment.status).toBe("completed");
    expect(result.payment.transactionId).toBe(TX_ID);
    expect(result.payment.timestamp).toBe("2026-09-14T00:49:00.000Z");
  });

  it("rejects a missing transaction ID", () => {
    const result = interpretVietcombank(validFixture, "");
    expect(result.outcome).toBe("insufficient_evidence");
  });

  it("rejects a mismatched transaction ID", () => {
    const result = interpretVietcombank(validFixture, "99999999999");
    expect(result.outcome).toBe("insufficient_evidence");
  });

  it("rejects a non-object input", () => {
    const result = interpretVietcombank("not-an-object", TX_ID);
    expect(result.outcome).toBe("insufficient_evidence");
  });

  it("rejects a non-success status", () => {
    const input = { ...validFixture, status: "pending" };
    const result = interpretVietcombank(input, TX_ID);
    expect(result.outcome).toBe("insufficient_evidence");
  });

  it("rejects NAPAS interbank transfers", () => {
    const input = { ...validFixture, transferType: "Chuyển tiền nhanh NAPAS 24/7" };
    const result = interpretVietcombank(input, TX_ID);
    expect(result.outcome).toBe("unsupported");
  });

  it("rejects zero or negative amounts", () => {
    const input = { ...validFixture, amount: 0 };
    expect(interpretVietcombank(input, TX_ID).outcome).toBe("insufficient_evidence");
    const input2 = { ...validFixture, amount: -100 };
    expect(interpretVietcombank(input2, TX_ID).outcome).toBe("insufficient_evidence");
  });

  it("rejects non-integer VND amounts", () => {
    const input = { ...validFixture, amount: 1000.5 };
    expect(interpretVietcombank(input, TX_ID).outcome).toBe("insufficient_evidence");
  });

  it("rejects conflicting currency", () => {
    const input = { ...validFixture, currency: "USD" };
    expect(interpretVietcombank(input, TX_ID).outcome).toBe("insufficient_evidence");
  });

  it("rejects invalid timestamps", () => {
    const input = { ...validFixture, timestamp: "not-a-date" };
    expect(interpretVietcombank(input, TX_ID).outcome).toBe("insufficient_evidence");
  });

  it("rejects missing recipient account", () => {
    const input = {
      ...validFixture,
      recipient: { ...validFixture.recipient, accountNumber: "" },
    };
    expect(interpretVietcombank(input, TX_ID).outcome).toBe("insufficient_evidence");
  });

  it("rejects malformed transaction IDs", () => {
    const input = { ...validFixture, transactionId: "abc" };
    expect(interpretVietcombank(input, TX_ID).outcome).toBe("insufficient_evidence");
  });

  it("handles ISO-8601 timestamps", () => {
    const input = { ...validFixture, timestamp: "2026-09-14T00:49:00.000Z" };
    const result = interpretVietcombank(input, TX_ID);
    expect(result.outcome).toBe("supported");
  });

  it("deterministic: same input produces same output", () => {
    const r1 = interpretVietcombank(validFixture, TX_ID);
    const r2 = interpretVietcombank(validFixture, TX_ID);
    expect(JSON.stringify(r1)).toBe(JSON.stringify(r2));
  });
});
