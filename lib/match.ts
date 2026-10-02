import type { Interpretation, PaymentClaim } from "./types";

const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/;
const exact = (v: unknown) => typeof v === "string" && v.length > 0 && v.trim() === v;
const instant = (v: string) => (UTC.test(v) ? Date.parse(v) : Number.NaN);

/**
 * Exact identifiers only. Memos and display names never establish payer/payee identity.
 * Returns `contradicted` with the mismatched claim fields when evidence disagrees, and
 * `insufficient_evidence` when the claim or observation is malformed. Finality, replay
 * protection and source authentication remain the adopting service's responsibility.
 */
export function matchPayment(observation: Interpretation, claim: PaymentClaim) {
  if (observation.outcome !== "supported") return observation;
  const p = observation.payment;
  const window = [claim.notBefore, claim.notAfter].filter((v) => v !== undefined);
  if (
    !/^[1-9]\d*$/.test(claim.amountMinor) ||
    !exact(claim.payerId) ||
    !exact(claim.payeeId) ||
    !/^[A-Z]{3}$/.test(claim.currency) ||
    [claim.payerScheme, claim.payeeScheme].some((s) => s !== undefined && !exact(s)) ||
    window.some((v) => !Number.isFinite(instant(v as string)))
  )
    return {
      outcome: "insufficient_evidence",
      reason: "Claim needs exact identities, positive minor units, an ISO currency and UTC bounds",
    } as const;
  const time = instant(p.timestamp);
  if (
    p.schemaVersion !== "2" ||
    p.sourceAuthenticated !== false ||
    !/^[1-9]\d*$/.test(p.amountMinor) ||
    !Number.isFinite(time)
  )
    return {
      outcome: "insufficient_evidence",
      reason: "Observation does not satisfy the PaymentObservation contract",
    } as const;
  const mismatched = [
    p.payer.id !== claim.payerId && "payerId",
    claim.payerScheme !== undefined && p.payer.scheme !== claim.payerScheme && "payerScheme",
    p.payee.id !== claim.payeeId && "payeeId",
    claim.payeeScheme !== undefined && p.payee.scheme !== claim.payeeScheme && "payeeScheme",
    p.amountMinor !== claim.amountMinor && "amountMinor",
    p.currency !== claim.currency && "currency",
    claim.notBefore !== undefined && time < instant(claim.notBefore) && "notBefore",
    claim.notAfter !== undefined && time > instant(claim.notAfter) && "notAfter",
  ].filter((field): field is string => field !== false);
  return mismatched.length
    ? ({ outcome: "contradicted", payment: p, mismatched } as const)
    : ({ outcome: "supported", payment: p } as const);
}
