export type { Adapter, Currency, AdapterMetadata } from "../../types.ts";
export { createFixtureHarness, NegativeTestFailure } from "../../fixture-harness.ts";

export const metadata: AdapterMetadata = {
  bankCode: "cmb",
  bankName: "China Merchants Bank",
  country: "cn",
  currency: "CNY",
  precision: 2,
  units: "yuan",
};

export const adapter: Adapter = {
  metadata,
  name: "cmb",
  version: "1.0.0",
  description:
    "China Merchants Bank (招商银行) personal internet banking and CMB App transaction-detail surface for CNY transfers.",
  supportedTransactionTypes: ["transfer"],
  supportedSurfaces: ["app", "web"],
  inputSchema: "./schema.json",
  expectedOutputSchema: "./output-schema.json",
  fixtureCount: 6,
  notesUrl: "https://github.com/zkp2p/peer-link/issues/157",
};
