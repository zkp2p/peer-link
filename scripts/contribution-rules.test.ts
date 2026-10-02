import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import mercuryFixture from "../banks/us/mercury/fixtures/sent.synthetic.json";
import mercuryManifest from "../banks/us/mercury/manifest.json";
import {
  type BankPath,
  CHECK_DEFINITIONS,
  checkContributorAdditions,
  checkReadme,
  checkRepositoryLayout,
  checkTransformerSource,
  classifyBankPath,
  parseJson,
  validateFixture,
  validateManifest,
  validateReport,
} from "./contribution-rules";
import { validateRepository } from "./validate";

const bank: BankPath = { bank: "banks/us/mercury", id: "us/mercury", country: "us", rest: "" };
const mercurySource = readFileSync("banks/us/mercury/transformer.js", "utf8");

describe("bank folder layout", () => {
  it.each([
    "banks/us/mercury/README.md",
    "banks/us/mercury/manifest.json",
    "banks/us/mercury/transformer.js",
    "banks/us/mercury/transformer.test.ts",
    "banks/us/mercury/fixtures/sent.synthetic.json",
    "banks/ua/monobank/fixtures/card-to-card.sanitized.json",
    "banks/us/mercury/reports/2026-09-23-0xsachink.json",
  ])("accepts %s", (file) => expect(classifyBankPath(file)).not.toHaveProperty("error"));
  it.each([
    ["banks/README.md", "inside a bank folder"],
    ["banks/xx/examplebank/README.md", "ISO 3166-1"],
    ["banks/USA/bank/README.md", "ISO 3166-1"],
    ["banks/zz/bank/README.md", "ISO 3166-1"],
    ["banks/us/Mercury/README.md", "kebab-case"],
    ["banks/us/my_bank/README.md", "kebab-case"],
    ["banks/us/mercury/transformer.ts", "transformer.js"],
    ["banks/us/mercury/fixtures/sent.json", "<case>.synthetic.json"],
    ["banks/us/mercury/fixtures/Sent.synthetic.json", "unexpected file"],
    ["banks/us/mercury/capture.har", "unexpected file"],
    ["banks/us/mercury/screenshot.png", "unexpected file"],
    ["banks/us/mercury/helpers.js", "unexpected file"],
    ["banks/us/mercury/reports/report.json", "unexpected file"],
    ["banks/us/mercury/fixtures/nested/a.synthetic.json", "unexpected file"],
  ])("rejects %s", (file, hint) => {
    const result = classifyBankPath(file);
    expect(result && "error" in result && result.error).toContain(hint);
  });
  it("ignores files outside banks and the shared contract test", () => {
    expect(classifyBankPath("lib/match.ts")).toBeNull();
    expect(classifyBankPath("banks/adapter-contract.test.ts")).toBeNull();
  });
});

describe("manifest", () => {
  const check = (patch: Record<string, unknown>, logo = true) =>
    validateManifest("m.json", { ...mercuryManifest, ...patch }, bank, () => logo);
  it("accepts the Mercury manifest", () => expect(check({})).toEqual([]));
  it.each([
    [{ id: "us/other" }, "id must be"],
    [{ country: "us" }, "country must be"],
    [{ schemaVersion: "2" }, "schemaVersion"],
    [{ status: "stable" }, "experimental"],
    [{ version: "1" }, "semantic"],
    [{ surface: "Web History" }, "kebab-case"],
    [{ capability: "" }, "capability"],
    [{ capability: "x".repeat(201) }, "capability"],
    [{ entrypoint: "not valid" }, "entrypoint"],
    [{ maintainers: [] }, "maintainers"],
    [{ maintainers: ["not a handle"] }, "maintainers"],
    [{ currencies: [] }, "currencies"],
    [{ currencies: ["usd"] }, "currencies"],
    [{ currencies: ["USD", "USD"] }, "currencies"],
    [{ unsupported: [] }, "unsupported"],
    [{ fixtureProvenance: "real" }, "fixtureProvenance"],
    [{ logo: "https://bank.example/logo.png" }, "local path"],
    [{ extra: true }, 'unknown field "extra"'],
    [{ name: "TODO" }, "TODO"],
  ])("rejects %j", (patch, message) => expect(check(patch).join("\n")).toContain(message));
  it("requires the logo file to exist", () =>
    expect(check({}, false).join("\n")).toContain("does not exist"));
  it("reports missing fields once", () => {
    const { currencies: _c, entrypoint: _e, ...rest } = mercuryManifest;
    expect(validateManifest("m.json", rest, bank, () => true)).toEqual([
      'm.json: missing required field "entrypoint"',
      'm.json: missing required field "currencies"',
    ]);
  });
  it("rejects non-objects", () =>
    expect(validateManifest("m.json", [], bank, () => true)).toHaveLength(1));
});

describe("fixtures", () => {
  const file = "banks/us/mercury/fixtures/sent.synthetic.json";
  const check = (patch: Record<string, unknown>, name = file) =>
    validateFixture(name, { ...mercuryFixture, ...patch });
  it("accepts the Mercury fixture", () => expect(check({})).toEqual([]));
  it("accepts an abstention with a reason", () =>
    expect(check({ expected: { outcome: "insufficient_evidence", reason: "Pending" } })).toEqual(
      [],
    ));
  it.each([
    [{ provenance: "sanitized" }, "match the file name"],
    [{ description: "" }, "description"],
    [{ transactionId: 1 }, "transactionId"],
    [{ expected: null }, "expected.outcome"],
    [{ expected: { outcome: "maybe" } }, "expected.outcome"],
    [{ expected: { outcome: "supported" } }, "expected.payerId is required"],
    [{ expected: { ...mercuryFixture.expected, amountMinor: "012" } }, "amountMinor"],
    [{ expected: { ...mercuryFixture.expected, currency: "usd" } }, "currency"],
    [{ expected: { ...mercuryFixture.expected, timestamp: "2026-01-15" } }, "UTC"],
    [{ expected: { ...mercuryFixture.expected, currencyExponent: 7 } }, "currencyExponent"],
    [{ expected: { ...mercuryFixture.expected, direction: "sideways" } }, "direction"],
    [{ expected: { ...mercuryFixture.expected, payerName: "x" } }, "unknown expected field"],
    [{ expected: { outcome: "unsupported", payerId: "x" } }, "may only set"],
    [{ expected: { outcome: "unsupported", reason: "" } }, "reason"],
    [{ raw: {} }, 'unknown field "raw"'],
  ])("rejects %j", (patch, message) => expect(check(patch).join("\n")).toContain(message));
  it("requires input", () => {
    const { input: _input, ...rest } = mercuryFixture;
    expect(validateFixture(file, rest).join("\n")).toContain('missing "input"');
  });
  it("rejects non-objects", () => expect(validateFixture(file, "x")).toHaveLength(1));
});

describe("reports", () => {
  const report = JSON.parse(
    readFileSync("banks/us/mercury/reports/2026-09-23-0xsachink.json", "utf8"),
  );
  const file = "banks/us/mercury/reports/2026-09-23-0xsachink.json";
  const ctx = {
    manifestSurface: "web-transactions-lite",
    fixtureExists: (ref: string) => ref === "fixtures/sent.synthetic.json",
    revision: (): "ok" | "missing-commit" | "not-ancestor" | "missing-bank" => "ok",
    now: Date.parse("2026-10-02T00:00:00Z"),
  };
  const check = (patch: Record<string, unknown>, context = ctx, name = file) =>
    validateReport(name, { ...report, ...patch }, bank, context).join("\n");
  it("accepts the Mercury report", () => expect(check({})).toBe(""));
  it.each([
    [{ schemaVersion: "2" }, "schemaVersion"],
    [{ provider: "us/other" }, "provider"],
    [{ reporter: "not a handle" }, "GitHub handle"],
    [{ reporter: "someoneelse" }, "file name"],
    [{ outcome: "great" }, "outcome"],
    [{ evidenceClass: "vibes" }, "evidenceClass"],
    [{ testedAt: "2026-09-22" }, "testedAt"],
    [{ testedAt: "2027-01-01T00:00:00Z" }, "testedAt"],
    [{ capability: "Outgoing wires" }, "kebab-case"],
    [{ surface: "web-other" }, "manifest surface"],
    [{ adapterRevision: "abc" }, "full 40-character"],
    [{ limitations: [] }, "limitations"],
    [{ limitations: [""] }, "limitations"],
    [{ fixtureRefs: "fixtures/sent.synthetic.json" }, "fixtureRefs must be an array"],
    [{ fixtureRefs: ["../../../package.json"] }, "fixtureRefs entry"],
    [{ fixtureRefs: ["fixtures/absent.synthetic.json"] }, "fixtureRefs entry"],
    [{ summary: "x".repeat(2001) }, "2000"],
    [{ summary: "" }, "missing summary"],
    [{ transcript: "..." }, "unexpected field"],
    [{ summary: "TODO" }, "TODO"],
  ])("rejects %j", (patch, message) => expect(check(patch)).toContain(message));
  it("requires revisions that exist and contain the bank folder", () => {
    expect(check({}, { ...ctx, revision: () => "missing-commit" })).toContain("two-PR flow");
    expect(check({}, { ...ctx, revision: () => "missing-bank" })).toContain("does not contain");
    expect(check({}, { ...ctx, revision: () => "not-ancestor" })).toContain("Do not rebase");
  });
  it("accepts a suffixed file name", () =>
    expect(check({}, ctx, "banks/us/mercury/reports/2026-09-23-0xsachink-ach.json")).toBe(""));
  it("rejects non-objects", () => expect(validateReport(file, 1, bank, ctx)).toHaveLength(1));
});

describe("transformer purity", () => {
  const check = (source: string, entrypoint: unknown = "interpret") =>
    checkTransformerSource("t.js", source, entrypoint).join("\n");
  it("accepts the Mercury adapter", () =>
    expect(checkTransformerSource("t.js", mercurySource, "interpretMercury")).toEqual([]));
  it("accepts an exported arrow function and local names that shadow nothing", () =>
    expect(
      check(
        "export const interpret = (input) => ({ fetchCount: input.fetch, n: Date.UTC(2026, 0, 1) });",
      ),
    ).toBe(""));
  it.each([
    ['import x from "./x.js"; export function interpret() {}', "imports"],
    ['export function interpret() {} export * from "./x.js";', "re-exports"],
    ["export default function interpret() {}", "named export"],
    ["export function interpret() { return import('./x.js'); }", "dynamic import"],
    ["export function interpret() { return import.meta.url; }", "import.meta"],
    ["export function interpret() { return fetch('https://bank.example'); }", '"fetch"'],
    ["export function interpret() { return globalThis.process; }", '"globalThis"'],
    ["export function interpret() { const { env } = process; return env; }", '"process"'],
    ["export function interpret() { console.log(1); }", '"console"'],
    ["export function interpret() { return eval('1'); }", '"eval"'],
    ["export function interpret() { return new Function('return 1')(); }", '"Function"'],
    ["export function interpret() { setTimeout(() => {}); }", '"setTimeout"'],
    ["export function interpret() { return Math.random(); }", "Math.random"],
    ["export function interpret() { return Date.now(); }", "Date.now"],
    ["export function interpret() { return new Date(); }", "reads the clock"],
    ["export function interpret() { return Date(); }", "reads the clock"],
    ["export function interpret() { return new Date(2026, 0, 1); }", "local time"],
    ["export function interpret(d) { return new Date(d).getHours(); }", "timezone"],
    ["export function interpret(d) { return d.toLocaleString(); }", "timezone"],
    ["export async function interpret() {}", "async"],
    ["export const interpret = async () => {};", "async"],
    ["export function interpret(p) { return (async () => await p)(); }", "await"],
    ["export function other() {}", "must export function interpret"],
    ["export function interpret( {", "does not parse"],
    ["// TODO\nexport function interpret() {}", "TODO"],
    [`export function interpret() {}\n//${"x".repeat(65536)}`, "at most"],
  ])("rejects %s", (source, message) => expect(check(source)).toContain(message));
});

it("requires adapter README sections without placeholders", () => {
  expect(checkReadme("R.md", readFileSync("banks/us/mercury/README.md", "utf8"))).toEqual([]);
  const errors = checkReadme("R.md", "# Bank\n\nTODO").join("\n");
  for (const part of ["## Semantics", "## Local acquisition", "TODO"])
    expect(errors).toContain(part);
});

it("never echoes invalid JSON contents", () => {
  const result = parseJson("f.json", '{"secret": "hunter2"');
  expect(result.error).toContain("invalid JSON");
  expect(result.error).not.toContain("hunter2");
  expect(parseJson("f.json", "[1]").value).toEqual([1]);
});

describe("repository validation", () => {
  const base: Record<string, string> = {
    "banks/us/mercury/README.md": "# Mercury\n\n## Semantics\n\n## Local acquisition\n",
    "banks/us/mercury/manifest.json": JSON.stringify(mercuryManifest),
    "banks/us/mercury/transformer.js": mercurySource,
    "banks/us/mercury/transformer.test.ts": 'import { interpretMercury } from "./transformer.js";',
    "banks/us/mercury/fixtures/sent.synthetic.json": JSON.stringify(mercuryFixture),
  };
  const run = (files: Record<string, string>) =>
    validateRepository({
      files: Object.keys(files),
      read: (file) => files[file],
      exists: () => true,
      revision: () => "ok",
      now: Date.now(),
    });
  it("accepts a complete adapter", () =>
    expect(run(base)).toEqual({
      errors: [],
      counts: { adapters: 1, fixtures: 1, reports: 0 },
    }));
  it("requires each adapter component", () => {
    const errors = run({
      "banks/us/mercury/manifest.json": base["banks/us/mercury/manifest.json"],
    }).errors.join("\n");
    for (const part of [
      "README.md",
      "fixtures/<case>",
      "transformer.js: missing",
      "transformer.test.ts",
    ])
      expect(errors).toContain(part);
  });
  it("requires tests to exercise the transformer and a supported fixture", () => {
    const errors = run({
      ...base,
      "banks/us/mercury/transformer.test.ts": "it('passes', () => {});",
      "banks/us/mercury/fixtures/sent.synthetic.json": JSON.stringify({
        ...mercuryFixture,
        expected: { outcome: "unsupported" },
      }),
    }).errors.join("\n");
    expect(errors).toContain('must import the adapter from "./transformer.js"');
    expect(errors).toContain("expected.outcome is supported");
  });
  it("requires a manifest in every bank folder", () => {
    expect(run({ ...base, "banks/us/chase/README.md": "x" }).errors.join("\n")).toContain(
      "add manifest.json; every bank folder is an adapter",
    );
  });
  it("reports invalid JSON without contents and requires at least one adapter", () => {
    const errors = run({ ...base, "banks/us/mercury/manifest.json": "{secret" }).errors.join("\n");
    expect(errors).toContain("invalid JSON");
    expect(errors).not.toContain("secret");
    expect(run({}).errors).toEqual(["banks/: at least one adapter and one fixture are required"]);
  });
  it("validates reports against the manifest surface", () => {
    const report = readFileSync("banks/us/mercury/reports/2026-09-23-0xsachink.json", "utf8");
    expect(
      run({ ...base, "banks/us/mercury/reports/2026-09-23-0xsachink.json": report }).errors,
    ).toEqual([]);
    expect(
      run({
        ...base,
        "banks/us/mercury/reports/2026-09-23-0xsachink.json": report.replace(
          "web-transactions-lite",
          "web-other",
        ),
      }).errors.join("\n"),
    ).toContain("manifest surface");
  });
  it("lists every layout error once", () => {
    const errors = run({
      ...base,
      "banks/xx/a/README.md": "",
      "banks/xx/a/manifest.json": "",
    }).errors;
    expect(errors.filter((e) => e.includes("ISO 3166-1"))).toHaveLength(1);
  });
});

describe("repository layout guard", () => {
  it("accepts every file currently in the repository", () => {
    const files = execFileSync("git", ["ls-files", "-z"], { encoding: "utf8" })
      .split("\0")
      .filter(Boolean);
    expect(checkRepositoryLayout(files)).toEqual([]);
  });
  it.each([
    "ai_solution.py",
    "solution.md",
    "src/index.ts",
    "docs/run.sh",
    "docs/nested/page.md",
    "skills/contribute-bank/helper.py",
    "skills/new/README.md",
    "app/payload.js",
    "app/public/logos/x.exe",
    "lib/nested/x.ts",
    "lib/helper.py",
    "scripts/run.sh",
    ".github/workflows/x.yaml",
    ".github/ISSUE_TEMPLATE/../x.md",
  ])("rejects %s", (file) =>
    expect(checkRepositoryLayout([file])[0]).toContain("not part of the repository layout"),
  );
  it("leaves bank folders to the bank rules", () =>
    expect(checkRepositoryLayout(["banks/xx/a/anything.py"])).toEqual([]));
});

describe("fork pull request additions", () => {
  it.each([
    "banks/ua/monobank/README.md",
    "banks/ua/monobank/transformer.js",
    "banks/ua/monobank/transformer.test.ts",
    "banks/ua/monobank/fixtures/sent.synthetic.json",
    "banks/ua/monobank/reports/2026-10-10-octocat.json",
    "app/public/logos/monobank.png",
  ])("allows %s", (file) => expect(checkContributorAdditions([file])).toEqual([]));
  it.each([
    "ai_solution.py",
    "scripts/ai_solution.ts",
    "lib/helper.ts",
    "docs/monobank.md",
    "banks/ua/monobank/helper.js",
    "banks/adapter-contract.test.ts",
    ".github/workflows/x.yml",
    "app/public/logos/BANK-ASSETS.md",
  ])("rejects %s", (file) =>
    expect(checkContributorAdditions([file])[0]).toContain("forks may only add"),
  );
  it("flags modifications to check definitions for reviewers", () => {
    for (const file of [
      "package.json",
      "vitest.config.ts",
      "scripts/validate.ts",
      ".github/workflows/ci.yml",
    ])
      expect(CHECK_DEFINITIONS.test(file)).toBe(true);
    expect(CHECK_DEFINITIONS.test("banks/ua/monobank/transformer.js")).toBe(false);
  });
});
