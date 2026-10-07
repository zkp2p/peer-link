import type { AdapterInput, AdapterOutput } from "../../types.ts";
import { metadata } from "./adapter.ts";

/**
 * China Merchants Bank (招商银行) adapter harness.
 *
 * Pure, deterministic, no network / credential / filesystem access.
 * Only CNY transfers from the personal internet banking or CMB App
 * transaction-detail surface are supported. Foreign-currency
 * sub-accounts and electronic-receipt-only pairs are out of scope.
 *
 * Ambiguity fails closed: any missing or non-success status aborts.
 */
export function acquire(input: AdapterInput): AdapterOutput {
  const raw = input as Record<string, unknown>;

  // --- surface ---
  const surface = raw["surface"] as string | undefined;
  if (surface !== "app" && surface !== "web") {
    throw new Error(
      `cmb: unsupported or missing surface; expected "app" or "web", got ${JSON.stringify(surface)}`
    );
  }

  // --- currency ---
  const currency = raw["currency"] as string | undefined;
  if (currency !== "CNY") {
    throw new Error(
      `cmb: unsupported currency ${JSON.stringify(currency)}; only CNY is in scope`
    );
  }

  // --- amount ---
  const amountCents = raw["amountCents"];
  if (
    typeof amountCents !== "number" ||
    !Number.isInteger(amountCents) ||
    amountCents < 1
  ) {
    throw new Error(
      `cmb: invalid amountCents ${JSON.stringify(amountCents)}; must be a positive integer`
    );
  }
  const amount = Number((amountCents / 100).toFixed(metadata.precision));
  if (amount < 0.01) {
    throw new Error(
      `cmb: amount below minimum after normalization (${amount} CNY)`
    );
  }

  // --- status ---
  const status = raw["status"] as string | undefined;
  if (status !== "success") {
    throw new Error(
      `cmb: only bank-reported success is accepted; got ${JSON.stringify(status)}`
    );
  }

  // --- timestamp ---
  const timestampUtc = raw["timestampUtc"] as string | undefined;
  if (
    !timestampUtc ||
    typeof timestampUtc !== "string" ||
    Number.isNaN(new Date(timestampUtc).getTime())
  ) {
    throw new Error(
      `cmb: missing or invalid timestampUtc ${JSON.stringify(timestampUtc)}`
    );
  }

  // --- payer ---
  const payer = raw["payer"] as Record<string, unknown> | undefined;
  if (!payer || typeof payer !== "object") {
    throw new Error("cmb: missing or invalid payer object");
  }
  const payerName = payer["name"] as string | undefined;
  const payerAccount = payer["accountNumber"] as string | undefined;
  if (!payerName || !payerAccount) {
    throw new Error(
      `cmb: payer must include name and accountNumber; got ${JSON.stringify(payer)}`
    );
  }

  // --- payee ---
  const payee = raw["payee"] as Record<string, unknown> | undefined;
  if (!payee || typeof payee !== "object") {
    throw new Error("cmb: missing or invalid payee object");
  }
  const payeeName = payee["name"] as string | undefined;
  const payeeAccount = payee["accountNumber"] as string | undefined;
  if (!payeeName || !payeeAccount) {
    throw new Error(
      `cmb: payee must include name and accountNumber; got ${JSON.stringify(payee)}`
    );
  }

  // --- transactionId ---
  const transactionId = raw["transactionId"] as string | undefined;
  if (!transactionId || typeof transactionId !== "string") {
    throw new Error(
      `cmb: missing or invalid transactionId ${JSON.stringify(transactionId)}`
    );
  }

  // --- memo (optional, untrusted) ---
  const memo = raw["memo"] as string | null | undefined;

  return {
    adapter: metadata.bankCode,
    currency: "CNY",
    precision: 2,
    amount,
    status: "success",
    timestampUtc,
    timezone: "Asia/Shanghai",
    payer: { name: payerName, accountNumber: payerAccount },
    payee: { name: payeeName, accountNumber: payeeAccount },
    transactionId,
    source: surface,
    memo: memo ?? null,
  };
}
