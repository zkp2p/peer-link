/**
 * Redacted summaries for live testing. The account owner compares these values with the bank's
 * own UI; nothing from a summary is published. Identifiers keep only their last four characters.
 */
import type { Interpretation } from "../lib/types";

export const BANK_ID = /^[a-z]{2}\/[a-z0-9]+(?:-[a-z0-9]+)*$/;

const mask = (value: unknown) => {
  const text = String(value ?? "");
  return text.length <= 4 ? "*".repeat(text.length) : `...${text.slice(-4)}`;
};

/** Format integer minor units as a decimal string without floating point. */
export function formatMinor(amountMinor: string, exponent: number) {
  if (!/^\d+$/.test(amountMinor) || !Number.isInteger(exponent) || exponent < 0) return "invalid";
  if (exponent === 0) return amountMinor;
  const padded = amountMinor.padStart(exponent + 1, "0");
  return `${padded.slice(0, -exponent)}.${padded.slice(-exponent)}`;
}

export function summarize(result: Interpretation) {
  if (!result || typeof result !== "object") return { outcome: "invalid-result" };
  if (result.outcome !== "supported") return { outcome: result.outcome, reason: result.reason };
  const p = result.payment;
  return {
    outcome: p ? "supported" : "invalid-result",
    provider: p?.provider,
    transactionId: mask(p?.transactionId),
    payer: { scheme: p?.payer?.scheme, provenance: p?.payer?.provenance, id: mask(p?.payer?.id) },
    payee: { scheme: p?.payee?.scheme, provenance: p?.payee?.provenance, id: mask(p?.payee?.id) },
    amount: `${formatMinor(String(p?.amountMinor), Number(p?.currencyExponent))} ${p?.currency}`,
    direction: p?.direction,
    status: p?.status,
    timestamp: p?.timestamp,
    timestampMeaning: p?.timestampMeaning,
    limitations: Array.isArray(p?.limitations) ? p.limitations.length : 0,
  };
}
