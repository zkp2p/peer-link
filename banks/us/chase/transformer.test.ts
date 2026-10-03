import { describe, expect, it } from "vitest";
import { toAttestationCandidate } from "../../../lib/attestation-candidate";
import { matchPayment } from "../../../lib/match";
import type { PaymentClaim } from "../../../lib/types";
import { interpretChase } from "./transformer.js";

const VALID_INPUT = {
  account: {
    id: "100000000001",
    accountNumber: "100000000001",
    routingNumber: "021000021",
    name: "Synthetic Chase Customer",
  },
  transactions: [
    {
      id: "CHASE-ACH-20261002-00001",
      type: "achTransfer",
      direction: "debit",
      status: "POSTED",
      amount: "345.50",
      currency: "USD",
      postedAt: "2026-10-02T16:20:00Z",
      payer: {
        accountNumber: "100000000001",
        routingNumber: "021000021",
        name: "Synthetic Chase Customer",
      },
      payee: {
        accountNumber: "200000000002",
        routingNumber: "122000049",
        name: "Synthetic Payee Corp",
      },
      memo: "Synthetic invoice",
    },
  ],
};

describe("interpretChase unit and contract coverage", () => {
  it("interprets standard completed ACH debit correctly", () => {
    const result = interpretChase(VALID_INPUT, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome !== "supported") return;
    expect(result.payment.amountMinor).toBe("34550");
    expect(result.payment.currency).toBe("USD");
    expect(result.payment.status).toBe("POSTED");
    expect(result.payment.payer.id).toBe("021000021:100000000001");
    expect(result.payment.payer.scheme).toBe("us-routing-account");
    expect(result.payment.payee.id).toBe("122000049:200000000002");
    expect(result.payment.payee.scheme).toBe("us-routing-account");
    expect(result.payment.timestamp).toBe("2026-10-02T16:20:00Z");
    expect(result.payment.sourceAuthenticated).toBe(false);
    expect(result.payment.limitations.length).toBeGreaterThan(0);
  });

  it("converts supported payment to attestation candidate without errors", () => {
    const result = interpretChase(VALID_INPUT, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome === "supported") {
      const candidate = toAttestationCandidate(result);
      expect(candidate.amount).toBe(34550n);
      expect(candidate.currency).toBe("USD");
    }
  });

  it("verifies matchPayment succeeds on exact matching claim", () => {
    const result = interpretChase(VALID_INPUT, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    const claim: PaymentClaim = {
      payerId: "021000021:100000000001",
      payeeId: "122000049:200000000002",
      amountMinor: "34550",
      currency: "USD",
      payerScheme: "us-routing-account",
      payeeScheme: "us-routing-account",
    };
    const match = matchPayment(result, claim);
    expect(match.outcome).toBe("supported");
  });

  it("verifies matchPayment fails on mismatched claim attributes", () => {
    const result = interpretChase(VALID_INPUT, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    const wrongAmount: PaymentClaim = {
      payerId: "021000021:100000000001",
      payeeId: "122000049:200000000002",
      amountMinor: "99999",
      currency: "USD",
    };
    const match = matchPayment(result, wrongAmount);
    expect(match.outcome).toBe("contradicted");
  });

  it("supports array input directly", () => {
    const arrayInput = VALID_INPUT.transactions;
    const result = interpretChase(arrayInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports root items array", () => {
    const itemsInput = { items: VALID_INPUT.transactions };
    const result = interpretChase(itemsInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports root data array", () => {
    const dataInput = { data: VALID_INPUT.transactions };
    const result = interpretChase(dataInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports single object root where id matches directly", () => {
    const singleInput = VALID_INPUT.transactions[0];
    const result = interpretChase(singleInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports root wrapped transaction object", () => {
    const wrappedInput = { transaction: VALID_INPUT.transactions[0] };
    const result = interpretChase(wrappedInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports root wrapped data object", () => {
    const wrappedData = { data: VALID_INPUT.transactions[0] };
    const result = interpretChase(wrappedData, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports numeric amount input", () => {
    const numericInput = structuredClone(VALID_INPUT);
    numericInput.transactions[0].amount = 550.25 as unknown as string;
    const result = interpretChase(numericInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome === "supported") {
      expect(result.payment.amountMinor).toBe("55025");
    }
  });

  it("supports integer amount string without decimal point", () => {
    const integerInput = structuredClone(VALID_INPUT);
    integerInput.transactions[0].amount = "100";
    const result = interpretChase(integerInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome === "supported") {
      expect(result.payment.amountMinor).toBe("10000");
    }
  });

  it("supports comma formatted amount with USD prefix", () => {
    const formattedInput = structuredClone(VALID_INPUT);
    formattedInput.transactions[0].amount = "USD 1,250.75";
    const result = interpretChase(formattedInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome === "supported") {
      expect(result.payment.amountMinor).toBe("125075");
    }
  });

  it("supports payer identifier fallback when payer routing is absent", () => {
    const noPayerRouting = structuredClone(VALID_INPUT);
    delete (noPayerRouting.transactions[0].payer as Record<string, unknown>).routingNumber;
    delete (noPayerRouting.account as Record<string, unknown>).routingNumber;
    const result = interpretChase(noPayerRouting, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome === "supported") {
      expect(result.payment.payer.id).toBe("100000000001");
      expect(result.payment.payer.scheme).toBe("chase-account-number");
    }
  });

  it("supports fallback to account object when transaction payer is absent", () => {
    const noPayerInTx = structuredClone(VALID_INPUT);
    delete (noPayerInTx.transactions[0] as Record<string, unknown>).payer;
    const result = interpretChase(noPayerInTx, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome === "supported") {
      expect(result.payment.payer.id).toBe("021000021:100000000001");
    }
  });

  it("supports timestamp field fallback when postedAt is absent", () => {
    const timestampFallback = structuredClone(VALID_INPUT);
    delete (timestampFallback.transactions[0] as Record<string, unknown>).postedAt;
    (timestampFallback.transactions[0] as Record<string, unknown>).timestamp =
      "2026-10-02T16:20:00Z";
    const result = interpretChase(timestampFallback, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports COMPLETED and PAID statuses", () => {
    for (const status of ["COMPLETED", "PAID"]) {
      const input = structuredClone(VALID_INPUT);
      input.transactions[0].status = status;
      const result = interpretChase(input, "CHASE-ACH-20261002-00001");
      expect(result.outcome).toBe("supported");
    }
  });

  it("supports alternative ACH type aliases", () => {
    for (const type of ["achDebit", "ach", "ACH"]) {
      const input = structuredClone(VALID_INPUT);
      input.transactions[0].type = type;
      const result = interpretChase(input, "CHASE-ACH-20261002-00001");
      expect(result.outcome).toBe("supported");
    }
  });

  it("supports transactionType field alias", () => {
    const aliasInput = structuredClone(VALID_INPUT);
    delete (aliasInput.transactions[0] as Record<string, unknown>).type;
    (aliasInput.transactions[0] as Record<string, unknown>).transactionType = "achTransfer";
    const result = interpretChase(aliasInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports outgoing direction alias", () => {
    const outgoingInput = structuredClone(VALID_INPUT);
    outgoingInput.transactions[0].direction = "outgoing";
    const result = interpretChase(outgoingInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
  });

  it("supports payee id when payee accountNumber is absent", () => {
    const payeeIdInput = structuredClone(VALID_INPUT);
    delete (payeeIdInput.transactions[0].payee as Record<string, unknown>).accountNumber;
    (payeeIdInput.transactions[0].payee as Record<string, unknown>).id = "200000000002";
    const result = interpretChase(payeeIdInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome === "supported") {
      expect(result.payment.payee.id).toBe("122000049:200000000002");
    }
  });

  it("supports payer id when payer accountNumber is absent", () => {
    const payerIdInput = structuredClone(VALID_INPUT);
    delete (payerIdInput.transactions[0].payer as Record<string, unknown>).accountNumber;
    (payerIdInput.transactions[0].payer as Record<string, unknown>).id = "100000000001";
    delete (payerIdInput.account as Record<string, unknown>).accountNumber;
    (payerIdInput.account as Record<string, unknown>).id = "100000000001";
    const result = interpretChase(payerIdInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("supported");
    if (result.outcome === "supported") {
      expect(result.payment.payer.id).toBe("021000021:100000000001");
    }
  });

  it("rejects when payee routingNumber is absent or non-string", () => {
    const noRouting = structuredClone(VALID_INPUT);
    delete (noRouting.transactions[0].payee as Record<string, unknown>).routingNumber;
    expect(interpretChase(noRouting, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );
  });

  it("rejects when payee id and accountNumber are both absent", () => {
    const noPayeeAcc = structuredClone(VALID_INPUT);
    delete (noPayeeAcc.transactions[0].payee as Record<string, unknown>).accountNumber;
    delete (noPayeeAcc.transactions[0].payee as Record<string, unknown>).id;
    expect(interpretChase(noPayeeAcc, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );
  });

  it("rejects empty or whitespace transaction ID", () => {
    expect(interpretChase(VALID_INPUT, "").outcome).toBe("insufficient_evidence");
    expect(interpretChase(VALID_INPUT, "   ").outcome).toBe("insufficient_evidence");
  });

  it("rejects null or non-object input", () => {
    expect(interpretChase(null, "CHASE-ACH-20261002-00001").outcome).toBe("insufficient_evidence");
    expect(interpretChase(42, "CHASE-ACH-20261002-00001").outcome).toBe("insufficient_evidence");
  });

  it("rejects when transactions list is missing", () => {
    expect(interpretChase({}, "CHASE-ACH-20261002-00001").outcome).toBe("insufficient_evidence");
  });

  it("rejects when transaction ID is not found", () => {
    expect(interpretChase(VALID_INPUT, "CHASE-MISSING").outcome).toBe("insufficient_evidence");
  });

  it("rejects duplicate transaction IDs in same envelope", () => {
    const dupInput = {
      transactions: [VALID_INPUT.transactions[0], VALID_INPUT.transactions[0]],
    };
    expect(interpretChase(dupInput, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );
  });

  it("returns unsupported for wire or zelle transfer types", () => {
    const wireInput = structuredClone(VALID_INPUT);
    wireInput.transactions[0].type = "wireTransfer";
    const result = interpretChase(wireInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("unsupported");
  });

  it("returns unsupported for incoming credit transfers", () => {
    const creditInput = structuredClone(VALID_INPUT);
    creditInput.transactions[0].direction = "credit";
    const result = interpretChase(creditInput, "CHASE-ACH-20261002-00001");
    expect(result.outcome).toBe("unsupported");
  });

  it("rejects pending, processing, or scheduled status", () => {
    for (const status of ["PENDING", "PROCESSING", "SCHEDULED"]) {
      const input = structuredClone(VALID_INPUT);
      input.transactions[0].status = status;
      const result = interpretChase(input, "CHASE-ACH-20261002-00001");
      expect(result.outcome).toBe("insufficient_evidence");
      if (result.outcome === "insufficient_evidence") {
        expect(result.reason).toBe("Transaction is still pending bank execution");
      }
    }
  });

  it("rejects returned, failed, or cancelled status", () => {
    for (const status of ["RETURNED", "FAILED", "CANCELLED"]) {
      const input = structuredClone(VALID_INPUT);
      input.transactions[0].status = status;
      const result = interpretChase(input, "CHASE-ACH-20261002-00001");
      expect(result.outcome).toBe("insufficient_evidence");
      if (result.outcome === "insufficient_evidence") {
        expect(result.reason).toBe("Transaction failed or was returned");
      }
    }
  });

  it("rejects unknown or invalid status", () => {
    const input = structuredClone(VALID_INPUT);
    input.transactions[0].status = "UNKNOWN_STATUS";
    expect(interpretChase(input, "CHASE-ACH-20261002-00001").outcome).toBe("insufficient_evidence");
  });

  it("rejects non-USD currency", () => {
    const eurInput = structuredClone(VALID_INPUT);
    eurInput.transactions[0].currency = "EUR";
    expect(interpretChase(eurInput, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );
  });

  it("rejects invalid amount types and non-positive numbers", () => {
    const invalidTypes = [null, undefined, true, {}, []];
    for (const bad of invalidTypes) {
      const input = structuredClone(VALID_INPUT);
      input.transactions[0].amount = bad as unknown as string;
      expect(interpretChase(input, "CHASE-ACH-20261002-00001").outcome).toBe(
        "insufficient_evidence",
      );
    }
    const nonPositive = [-10, 0, Number.NaN, Number.POSITIVE_INFINITY];
    for (const num of nonPositive) {
      const input = structuredClone(VALID_INPUT);
      input.transactions[0].amount = num as unknown as string;
      expect(interpretChase(input, "CHASE-ACH-20261002-00001").outcome).toBe(
        "insufficient_evidence",
      );
    }
  });

  it("rejects invalid amount strings and precision beyond two decimals", () => {
    const invalidStrings = ["abc", "10.123", "-50.00", "0.00", "1,200", "1.2.3"];
    for (const bad of invalidStrings) {
      const input = structuredClone(VALID_INPUT);
      input.transactions[0].amount = bad;
      expect(interpretChase(input, "CHASE-ACH-20261002-00001").outcome).toBe(
        "insufficient_evidence",
      );
    }
  });

  it("rejects invalid timestamp format or calendar date", () => {
    const badTimestamps = [
      "2026-10-02",
      "not-a-timestamp",
      "2026-10-02T16:20:00+02:00",
      "2026-02-30T16:20:00Z",
    ];
    for (const ts of badTimestamps) {
      const input = structuredClone(VALID_INPUT);
      input.transactions[0].postedAt = ts;
      expect(interpretChase(input, "CHASE-ACH-20261002-00001").outcome).toBe(
        "insufficient_evidence",
      );
    }
  });

  it("rejects masked or missing payer identifier", () => {
    const maskedPayer = structuredClone(VALID_INPUT);
    maskedPayer.transactions[0].payer.accountNumber = "1000000****1";
    delete (maskedPayer.account as Record<string, unknown>).accountNumber;
    expect(interpretChase(maskedPayer, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );

    const xMaskedPayer = structuredClone(VALID_INPUT);
    xMaskedPayer.transactions[0].payer.accountNumber = "XXXX1234";
    delete (xMaskedPayer.account as Record<string, unknown>).accountNumber;
    expect(interpretChase(xMaskedPayer, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );

    const shortPayer = structuredClone(VALID_INPUT);
    shortPayer.transactions[0].payer.accountNumber = "12";
    delete (shortPayer.account as Record<string, unknown>).accountNumber;
    expect(interpretChase(shortPayer, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );

    const longPayer = structuredClone(VALID_INPUT);
    longPayer.transactions[0].payer.accountNumber = "123456789012345678";
    delete (longPayer.account as Record<string, unknown>).accountNumber;
    expect(interpretChase(longPayer, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );

    const badPayerRouting = structuredClone(VALID_INPUT);
    badPayerRouting.transactions[0].payer.routingNumber = "123";
    delete (badPayerRouting.account as Record<string, unknown>).routingNumber;
    expect(interpretChase(badPayerRouting, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );

    const missingPayer = structuredClone(VALID_INPUT);
    delete (missingPayer.transactions[0].payer as Record<string, unknown>).accountNumber;
    delete (missingPayer.transactions[0].payer as Record<string, unknown>).id;
    delete (missingPayer.account as Record<string, unknown>).accountNumber;
    delete (missingPayer.account as Record<string, unknown>).id;
    expect(interpretChase(missingPayer, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );
  });

  it("rejects invalid payee routing or account number", () => {
    const badRouting = structuredClone(VALID_INPUT);
    badRouting.transactions[0].payee.routingNumber = "12345";
    expect(interpretChase(badRouting, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );

    const maskedPayee = structuredClone(VALID_INPUT);
    maskedPayee.transactions[0].payee.accountNumber = "2000000****2";
    expect(interpretChase(maskedPayee, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );

    const shortPayee = structuredClone(VALID_INPUT);
    shortPayee.transactions[0].payee.accountNumber = "12";
    expect(interpretChase(shortPayee, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );

    const longPayee = structuredClone(VALID_INPUT);
    longPayee.transactions[0].payee.accountNumber = "123456789012345678";
    expect(interpretChase(longPayee, "CHASE-ACH-20261002-00001").outcome).toBe(
      "insufficient_evidence",
    );
  });
});
