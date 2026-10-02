# Promoting an adapter into Peer

The public contract is version 2 (`peer-link` 0.2.0). It consists of an original
pure interpretation function `(evidence, transactionId) => Interpretation`, exported
from each adapter's `transformer.js` under the name in its manifest `entrypoint` (the
`BankAdapter` type in `lib/types.ts` describes the same shape), and a
`PaymentObservation`. It contains no private Peer implementation or fixtures.
`banks/adapter-contract.test.ts` checks every adapter's supported fixtures against this
contract and requires them to convert with `toAttestationCandidate`.

`schemaVersion: "2"` adds an explicit `currencyExponent` and allows documented
bank-specific identity schemes, directions and statuses. Version 1 consumers
must reject unknown schema versions until upgraded; never guess precision from
an amount string or assume all currencies have two decimals. Existing Mercury
observations use USD minor units with exponent 2.

`toAttestationCandidate` converts an accepted observation into an incomplete
private adoption input: exact recipient identity and scheme, `bigint` amount in
Peer settlement units (two decimals), currency, original source amount/exponent,
transaction ID and UTC milliseconds. It
preserves the raw bank status and `sourceAuthenticated: false`. Synthetic contract
tests cover USD, exact VND conversion, higher-precision rejection, integer range, dates and
ambiguous identities. These examples make no claim of a live VND integration.

Before use by the private attestation service, its owner must:

1. Authenticate the bank response through an independently approved reader and
   verify that it belongs to the intended owner/account and operation.
2. Validate the source currency and exponent against the service's registry. The
   current settlement input uses **two-decimal fiat units even for VND/JPY**. The
   candidate marks this as `amountExponent: 2` and preserves `sourceAmountMinor`
   and `sourceCurrencyExponent` for review. Thus 25,000 VND (source exponent 0)
   becomes 2,500,000 settlement units. Higher precision must divide exactly or
   the bridge rejects it; there is no silent rounding. This is not USDC base
   units or an 18-decimal rate. If the private settlement contract changes,
   update this bridge and its compatibility tests together.
3. Normalize the exact recipient with the service's approved scheme and hash it
   only inside the service. A display name or opaque bank-local ID is insufficient
   when the settlement rule needs a routing/account or phone/email identity.
4. Bind the requested intent and supported platform/method, enforce amount,
   currency, timestamp and direction rules, and maintain scoped deduplication.
5. Review bank-status meaning separately. Mercury `sent` establishes only the
   sender-bank status, not beneficiary credit or final settlement.
6. Complete the private repository's security/release gates before enabling a
   transformer or signing any production attestation.

The candidate deliberately omits `intentHash`, signing `method` and hashed
`payeeId`. A public adapter cannot supply those authority-bearing values. Do not
import community code directly into a credentialed transformer process; review
and adopt the narrow semantics and tests through the private repository's normal
change process.
