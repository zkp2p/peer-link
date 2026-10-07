import type { FixtureSet } from "../../types.ts";
import { acquire } from "./acquire.ts";

/**
 * Synthetic fixtures for China Merchants Bank (CMB) CNY adapter.
 *
 * All values are synthetic and independently justified. No real
 * account data, credentials, or banking records are included.
 */
export const fixtures: FixtureSet = {
  positive: [
    {
      id: "cmb-cmb-success-001",
      description:
        "CMB-to-CMB completed transfer, app surface, round-yuan amount",
      input: {
        surface: "app",
        currency: "CNY",
        amountCents: 10000,
        status: "success",
        timestampUtc: "2026-06-15T02:10:00.000Z",
        payer: {
          name: "Zhang***",
          accountNumber: "62***********1234",
        },
        payee: {
          name: "Li***",
          accountNumber: "62***********5678",
        },
        transactionId: "CMB2026061502100012345678",
        memo: null,
      },
      expected: {
        adapter: "cmb",
        currency: "CNY",
        precision: 2,
        amount: 100.0,
        status: "success",
        timestampUtc: "2026-06-15T02:10:00.000Z",
        timezone: "Asia/Shanghai",
        payer: {
          name: "Zhang***",
          accountNumber: "62***********1234",
        },
        payee: {
          name: "Li***",
          accountNumber: "62***********5678",
        },
        transactionId: "CMB2026061502100012345678",
        source: "app",
        memo: null,
      },
    },
    {
      id: "cmb-web-success-002",
      description:
        "Interbank CNY transfer, web surface, two-decimal amount",
      input: {
        surface: "web",
        currency: "CNY",
        amountCents: 50050,
        status: "success",
        timestampUtc: "2026-07-01T10:00:30.000Z",
        payer: {
          name: "Wang**",
          accountNumber: "6225****8888",
        },
        payee: {
          name: "Chen*",
          accountNumber: "3***1001",
        },
        transactionId: "CMB20260701100030987654321",
        memo: "rent-july",
      },
      expected: {
        adapter: "cmb",
        currency: "CNY",
        precision: 2,
        amount: 500.5,
        status: "success",
        timestampUtc: "2026-07-01T10:00:30.000Z",
        timezone: "Asia/Shanghai",
        payer: {
          name: "Wang**",
          accountNumber: "6225****8888",
        },
        payee: {
          name: "Chen*",
          accountNumber: "3***1001",
        },
        transactionId: "CMB20260701100030987654321",
        source: "web",
        memo: "rent-july",
      },
    },
    {
      id: "cmb-cmb-success-003",
      description:
        "CMB-to-CMB small amount near precision floor",
      input: {
        surface: "app",
        currency: "CNY",
        amountCents: 1,
        status: "success",
        timestampUtc: "2026-08-20T08:00:00.000Z",
        payer: {
          name: "Authorised Holder",
          accountNumber: "62***********0001",
        },
        payee: {
          name: "Recipient",
          accountNumber: "62***********0002",
        },
        transactionId: "CMB20260820080000000000001",
        memo: null,
      },
      expected: {
        adapter: "cmb",
        currency: "CNY",
        precision: 2,
        amount: 0.01,
        status: "success",
        timestampUtc: "2026-08-20T08:00:00.000Z",
        timezone: "Asia/Shanghai",
        payer: {
          name: "Authorised Holder",
          accountNumber: "62***********0001",
        },
        payee: {
          name: "Recipient",
          accountNumber: "62***********0002",
        },
        transactionId: "CMB20260820080000000000001",
        source: "app",
        memo: null,
      },
    },
  ],
  negative: [
    {
      id: "cmb-negative-missing-surface",
      description: "Surface is missing",
      input: {
        surface: undefined as unknown as string,
        currency: "CNY",
        amountCents: 10000,
        status: "success",
        timestampUtc: "2026-06-15T02:10:00.000Z",
        payer: { name: "A", accountNumber: "1" },
        payee: { name: "B", accountNumber: "2" },
        transactionId: "TX-1",
      } as unknown as Parameters<typeof acquire>[0],
      expectedError: true,
      matchError: /cmb: unsupported or missing surface/,
    },
    {
      id: "cmb-negative-wrong-currency",
      description: "Non-CNY currency is rejected",
      input: {
        surface: "app",
        currency: "USD" as unknown as "CNY",
        amountCents: 10000,
        status: "success",
        timestampUtc: "2026-06-15T02:10:00.000Z",
        payer: { name: "A", accountNumber: "1" },
        payee: { name: "B", accountNumber: "2" },
        transactionId: "TX-1",
      } as unknown as Parameters<typeof acquire>[0],
      expectedError: true,
      matchError: /cmb: unsupported currency/,
    },
    {
      id: "cmb-negative-non-success-status",
      description: "Processing status fails closed",
      input: {
        surface: "app",
        currency: "CNY",
        amountCents: 10000,
        status: "processing" as unknown as "success",
        timestampUtc: "2026-06-15T02:10:00.000Z",
        payer: { name: "A", accountNumber: "1" },
        payee: { name: "B", accountNumber: "2" },
        transactionId: "TX-1",
      } as unknown as Parameters<typeof acquire>[0],
      expectedError: true,
      matchError: /cmb: only bank-reported success is accepted/,
    },
    {
      id: "cmb-negative-missing-payer-account",
      description: "Payer object missing accountNumber",
      input: {
        surface: "app",
        currency: "CNY",
        amountCents: 10000,
        status: "success",
        timestampUtc: "2026-06-15T02:10:00.000Z",
        payer: { name: "A", accountNumber: "" } as unknown as {
          name: string;
          accountNumber: string;
        },
        payee: { name: "B", accountNumber: "2" },
        transactionId: "TX-1",
      } as unknown as Parameters<typeof acquire>[0],
      expectedError: true,
      matchError: /cmb: payer must include name and accountNumber/,
    },
    {
      id: "cmb-negative-missing-payee-name",
      description: "Payee object missing name",
      input: {
        surface: "app",
        currency: "CNY",
        amountCents: 10000,
        status: "success",
        timestampUtc: "2026-06-15T02:10:00.000Z",
        payer: { name: "A", accountNumber: "1" },
        payee: { name: "", accountNumber: "2" } as unknown as {
          name: string;
          accountNumber: string;
        },
        transactionId: "TX-1",
      } as unknown as Parameters<typeof acquire>[0],
      expectedError: true,
      matchError: /cmb: payee must include name and accountNumber/,
    },
    {
      id: "cmb-negative-invalid-transaction-id",
      description: "Missing transactionId fails closed",
      input: {
        surface: "app",
        currency: "CNY",
        amountCents: 10000,
        status: "success",
        timestampUtc: "2026-06-15T02:10:00.000Z",
        payer: { name: "A", accountNumber: "1" },
        payee: { name: "B", accountNumber: "2" },
        transactionId: "" as unknown as string,
      } as unknown as Parameters<typeof acquire>[0],
      expectedError: true,
      matchError: /cmb: missing or invalid transactionId/,
    },
  ],
};
