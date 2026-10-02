/**
 * Build a browser bundle of one adapter for in-page testing by a browser-capable agent:
 *   npm run bundle:bank -- <country>/<bank>
 * The bundle contains only repository code, never banking data, and makes no requests.
 * In the signed-in bank tab, evaluate the bundle, then call
 *   PeerLinkHarness.run(response, transactionId)   // redacted summary for comparison
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { build } from "esbuild";
import { BANK_ID } from "./harness-rules";

const id = process.argv[2] ?? "";
if (!BANK_ID.test(id) || !existsSync(`banks/${id}/manifest.json`)) {
  console.error("Usage: npm run bundle:bank -- <country>/<bank> (an adapter with manifest.json)");
  process.exit(1);
}
const { entrypoint } = JSON.parse(readFileSync(`banks/${id}/manifest.json`, "utf8"));
const transformer = `banks/${id}/transformer.js`;
const result = await build({
  stdin: {
    contents: [
      `import { ${entrypoint} as interpret } from "./${transformer}";`,
      `import { summarize } from "./scripts/harness-rules.ts";`,
      `globalThis.PeerLinkHarness = { id: ${JSON.stringify(id)}, interpret,`,
      "  run: (response, transactionId) => summarize(interpret(response, transactionId)) };",
    ].join("\n"),
    resolveDir: process.cwd(),
    loader: "js",
  },
  bundle: true,
  format: "iife",
  minify: true,
  write: false,
  platform: "browser",
  logLevel: "silent",
});
const bundle = result.outputFiles[0].text;
const out = `.local/${id.replace("/", "-")}-harness.js`;
mkdirSync(".local", { recursive: true });
writeFileSync(out, bundle);
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
const head = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
const dirty = execFileSync(
  "git",
  ["status", "--porcelain", "--", `banks/${id}`, "scripts", "lib"],
  {
    encoding: "utf8",
  },
).trim();
console.log(`Harness bundle: ${out} (repository code only, no banking data)`);
console.log(
  `Revision: ${head}${dirty ? " (UNCOMMITTED CHANGES: a report cannot cite this revision)" : ""}`,
);
console.log(`Transformer SHA-256: ${sha(readFileSync(transformer, "utf8"))}`);
console.log(`Bundle SHA-256: ${sha(bundle)}`);
console.log(
  "In the bank tab: evaluate the bundle, then PeerLinkHarness.run(response, transactionId).",
);
