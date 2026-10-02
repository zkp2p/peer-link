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

const ENUM_KEY =
  /(status|state|type|kind|direction|currency|ccy|category|method|channel|side|sign)$/i;

function describeString(value: string) {
  const hints = [`length ${value.length}`];
  if (/^\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:?\d{2})$/.test(value))
    hints.push(`datetime ${value.endsWith("Z") ? "UTC" : "with offset"}`);
  else if (/^\d{4}-\d{2}-\d{2}$/.test(value)) hints.push("date");
  else if (/^-?\d+$/.test(value)) hints.push(`digits ${value.replace("-", "").length}`);
  else if (/^-?\d+\.\d+$/.test(value)) hints.push(`decimal ${value.split(".")[1].length} places`);
  else if (/^\d[\d -]*\d$/.test(value))
    hints.push(`digits ${value.replace(/\D/g, "").length} with separators`);
  if (/[*•x]{3,}/i.test(value)) hints.push("masked");
  if (/@/.test(value)) hints.push("contains @");
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(value)) hints.push("uuid");
  if (value.startsWith("-")) hints.push("negative");
  return `<string ${hints.join(", ")}>`;
}

/**
 * The structure of a saved response with values replaced by descriptions, so an agent can
 * design synthetic fixtures without reading banking data. Short enum-like values of fields
 * such as status, type, direction and currency are kept because they define semantics.
 */
export function shapeOf(value: unknown, key = "", depth = 0): unknown {
  if (depth > 16) return "<nested too deep>";
  if (Array.isArray(value)) {
    const items = value.slice(0, 3).map((v) => shapeOf(v, key, depth + 1));
    return value.length > 3 ? [...items, `<${value.length - 3} more items>`] : items;
  }
  if (value !== null && typeof value === "object") {
    let hidden = 0;
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [
        /\d{4,}|@/.test(k) ? `<id-like key ${++hidden}>` : k,
        shapeOf(v, k, depth + 1),
      ]),
    );
  }
  if (typeof value === "string")
    return ENUM_KEY.test(key) && /^[A-Za-z][A-Za-z_ -]{0,31}$/.test(value)
      ? value
      : describeString(value);
  if (typeof value === "number") {
    const decimals = String(value).split(".")[1]?.length ?? 0;
    return `<number${value < 0 ? " negative" : ""}${decimals ? `, ${decimals} decimals` : ", integer"}>`;
  }
  return value;
}
