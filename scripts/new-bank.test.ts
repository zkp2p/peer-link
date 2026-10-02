import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import mercuryFixture from "../banks/us/mercury/fixtures/sent.synthetic.json";
import mercuryManifest from "../banks/us/mercury/manifest.json";
import { checkTransformerSource } from "./contribution-rules";
import { scaffold } from "./new-bank";
import { validateRepository } from "./validate";

const mercury: Record<string, string> = {
  "banks/us/mercury/README.md": "# Mercury\n\n## Semantics\n\n## Local acquisition\n",
  "banks/us/mercury/manifest.json": JSON.stringify(mercuryManifest),
  "banks/us/mercury/transformer.js": "export function interpretMercury() {}",
  "banks/us/mercury/transformer.test.ts": 'import { interpretMercury } from "./transformer.js";',
  "banks/us/mercury/fixtures/sent.synthetic.json": JSON.stringify(mercuryFixture),
};
const validate = (files: Record<string, string>) =>
  validateRepository({
    files: Object.keys(files),
    read: (file) => files[file],
    exists: () => true,
    revision: () => "ok",
    now: Date.now(),
  }).errors;
const temp = mkdtempSync(join(tmpdir(), "peer-link-scaffold-"));
afterAll(() => rmSync(temp, { recursive: true, force: true }));

describe("new-bank scaffold", () => {
  const files = scaffold("nz/example-bank", { name: "Example Bank" });
  it("creates the documented adapter layout", () =>
    expect(Object.keys(files).sort()).toEqual([
      "banks/nz/example-bank/README.md",
      "banks/nz/example-bank/fixtures/completed.synthetic.json",
      "banks/nz/example-bank/fixtures/pending.synthetic.json",
      "banks/nz/example-bank/manifest.json",
      "banks/nz/example-bank/transformer.js",
      "banks/nz/example-bank/transformer.test.ts",
    ]));
  it("fails validation only until the TODO placeholders are replaced", () => {
    const errors = validate({ ...mercury, ...files });
    expect(errors.length).toBeGreaterThan(0);
    for (const error of errors) expect(error).toMatch(/TODO|surface must be/);
    expect(errors.join("\n")).toContain("example-bank/README.md: replace every TODO");
  });
  it("passes the purity rules apart from placeholders", () => {
    const problems = checkTransformerSource(
      "t.js",
      files["banks/nz/example-bank/transformer.js"],
      "interpretExampleBank",
    );
    expect(problems).toEqual(["t.js: replace every TODO placeholder"]);
  });
  it("ships a template whose fixtures match its expected outputs", async () => {
    for (const [file, content] of Object.entries(files)) {
      mkdirSync(dirname(join(temp, file)), { recursive: true });
      writeFileSync(join(temp, file), content);
    }
    const adapter = await import(
      pathToFileURL(join(temp, "banks/nz/example-bank/transformer.js")).href
    );
    for (const name of ["completed", "pending"]) {
      const fixture = JSON.parse(files[`banks/nz/example-bank/fixtures/${name}.synthetic.json`]);
      const result = adapter.interpretExampleBank(fixture.input, fixture.transactionId);
      expect(result.outcome).toBe(fixture.expected.outcome);
      if (result.outcome === "supported")
        expect(result.payment).toMatchObject({
          payer: { id: fixture.expected.payerId },
          payee: { id: fixture.expected.payeeId },
          amountMinor: fixture.expected.amountMinor,
          currency: fixture.expected.currency,
          timestamp: fixture.expected.timestamp,
        });
      else expect(result.reason).toBe(fixture.expected.reason);
    }
  });
  it("derives the entrypoint from the display name", () => {
    expect(files["banks/nz/example-bank/manifest.json"]).toContain(
      '"entrypoint": "interpretExampleBank"',
    );
    expect(
      scaffold("pe/bcp", { name: "Banco de Crédito del Perú" })["banks/pe/bcp/manifest.json"],
    ).toContain('"entrypoint": "interpretBancoDeCreditoDelPeru"');
    expect(scaffold("us/x", { name: "123" })["banks/us/x/manifest.json"]).toContain(
      '"entrypoint": "interpretX"',
    );
  });
  it("derives names and rejects invalid IDs", () => {
    expect(scaffold("us/bank-of-america")["banks/us/bank-of-america/manifest.json"]).toContain(
      '"name": "Bank Of America"',
    );
    expect(() => scaffold("USA/bank")).toThrow("ua/monobank");
  });
});
