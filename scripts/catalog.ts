import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// Filesystem discovery also works on deployment builders without Git metadata. Sort so the
// published catalog is byte-identical on every filesystem (readdir order is unspecified).
const files = readdirSync("banks", { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => join(entry.parentPath, entry.name).replaceAll("\\", "/"))
  .sort();
// Publish an explicit allowlist, never arbitrary manifest fields, on the public landing page.
const PUBLIC_FIELDS = [
  "schemaVersion",
  "id",
  "name",
  "country",
  "status",
  "version",
  "surface",
  "capability",
  "maintainers",
  "currencies",
  "unsupported",
  "fixtureProvenance",
  "logo",
] as const;
const providers = files
  .filter((f) => /^banks\/[^/]+\/[^/]+\/manifest.json$/.test(f))
  .map((file) => {
    const bank = file.replace("/manifest.json", "");
    const manifest = JSON.parse(readFileSync(file, "utf8"));
    const reports = files
      .filter((f) => f.startsWith(`${bank}/reports/`) && f.endsWith(".json"))
      .map((f) => JSON.parse(readFileSync(f, "utf8")));
    // Separate compatibility scopes and revisions. No carry-forward and no person/account uniqueness claim.
    const scopes = new Map<string, Map<string, (typeof reports)[number]>>();
    for (const r of reports) {
      const key = `${r.adapterRevision}:${r.harnessRevision}:${r.surface}:${r.capability}`;
      const reporters = scopes.get(key) ?? new Map();
      const old = reporters.get(r.reporter.toLowerCase());
      if (!old || Date.parse(r.testedAt) > Date.parse(old.testedAt))
        reporters.set(r.reporter.toLowerCase(), r);
      scopes.set(key, reporters);
    }
    const evidence = [...scopes.entries()].map(([scope, reporters]) => ({
      scope,
      reports: [...reporters.values()].map(({ reporter, outcome, evidenceClass, testedAt }) => ({
        reporter,
        outcome,
        evidenceClass,
        testedAt,
      })),
      distinctReportingHandles: reporters.size,
    }));
    const published = Object.fromEntries(
      PUBLIC_FIELDS.filter((key) => key in manifest).map((key) => [key, manifest[key]]),
    );
    return {
      ...published,
      reportCount: reports.length,
      evidence,
      source: `https://github.com/zkp2p/peer-link/tree/main/${bank}`,
    };
  });
writeFileSync(
  "app/public/catalog.json",
  `${JSON.stringify({ schemaVersion: "1", providers }, null, 2)}\n`,
);
console.log(`Built catalog for ${providers.length} providers.`);
