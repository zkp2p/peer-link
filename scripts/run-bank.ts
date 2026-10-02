/**
 * Run one adapter against a locally saved response without publishing anything:
 *   npm run try:bank -- <country>/<bank> .local/<file>.json <transactionId>
 * The input must stay under the Git-ignored .local/ directory. Output is a redacted summary
 * plus the exact revision to cite in a report. Delete the local file when you are done.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { BANK_ID, summarize } from "./harness-rules";

const die = (message: string): never => {
  console.error(message);
  process.exit(1);
};

const [id = "", input = "", transactionId] = process.argv.slice(2);
if (!BANK_ID.test(id) || !existsSync(`banks/${id}/manifest.json`) || !transactionId)
  die("Usage: npm run try:bank -- <country>/<bank> .local/<file>.json <transactionId>");
const local = resolve(".local");
if (!existsSync(input) || !realpathSync(input).startsWith(`${realpathSync(local)}${sep}`))
  die("Keep captured responses inside .local/ (Git-ignored); refusing other paths");
const { entrypoint } = JSON.parse(readFileSync(`banks/${id}/manifest.json`, "utf8"));
const adapter = await import(pathToFileURL(resolve(`banks/${id}/transformer.js`)).href);
let response: unknown;
try {
  response = JSON.parse(readFileSync(input, "utf8"));
} catch {
  die("The saved response is not JSON (contents not shown)");
}
// Adapter error messages could quote banking data, so only the error type is printed.
let result: unknown;
try {
  result = adapter[entrypoint](response, transactionId);
} catch (error) {
  die(
    `The adapter threw ${(error as Error)?.name ?? "an error"} instead of returning insufficient_evidence (message hidden)`,
  );
}
const head = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
const dirty = execFileSync(
  "git",
  ["status", "--porcelain", "--", `banks/${id}`, "scripts", "lib"],
  {
    encoding: "utf8",
  },
).trim();
console.log(
  JSON.stringify(
    {
      provider: id,
      revision: head,
      revisionClean: !dirty,
      summary: summarize(result as Parameters<typeof summarize>[0]),
      next: "Compare each field with the bank UI. Publish only a report (docs/evidence.md), never this output or the input file.",
    },
    null,
    2,
  ),
);
