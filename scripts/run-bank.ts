/**
 * Work with a locally saved bank response without publishing anything:
 *   npm run try:bank -- --shape .local/<file>.json
 *       prints the response structure with values replaced by descriptions, for designing
 *       synthetic fixtures without reading banking data
 *   npm run try:bank -- <country>/<bank> .local/<file>.json <transactionId>
 *       runs the adapter and prints a redacted summary plus the revision to cite in a report
 * Inputs must stay under the Git-ignored .local/ directory: .json is parsed, .txt/.html is
 * passed to the adapter as a string. Delete them when you are done.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { BANK_ID, shapeOf, summarize } from "./harness-rules";

const die = (message: string): never => {
  console.error(message);
  process.exit(1);
};
const load = (input: string): unknown => {
  const local = resolve(".local");
  if (
    !existsSync(input) ||
    !existsSync(local) ||
    !realpathSync(input).startsWith(`${realpathSync(local)}${sep}`)
  )
    die("Keep captured responses inside .local/ (Git-ignored); refusing other paths");
  const text = readFileSync(input, "utf8");
  // Text evidence (an SMS confirmation, an HTML page) is passed through as a string.
  if (/\.(txt|html?)$/i.test(input)) return text;
  try {
    return JSON.parse(text);
  } catch {
    return die("The saved response is not JSON (contents not shown); use .txt for text evidence");
  }
};

const args = process.argv.slice(2);
if (args[0] === "--shape") {
  console.log(JSON.stringify(shapeOf(load(args[1] ?? "")), null, 2));
  process.exit(0);
}
const [id = "", input = "", transactionId] = args;
if (!BANK_ID.test(id) || !existsSync(`banks/${id}/manifest.json`) || !transactionId)
  die(
    "Usage: npm run try:bank -- <country>/<bank> .local/<file>.json <transactionId>\n   or: npm run try:bank -- --shape .local/<file>.json",
  );
const response = load(input);
const { entrypoint } = JSON.parse(readFileSync(`banks/${id}/manifest.json`, "utf8"));
const adapter = await import(pathToFileURL(resolve(`banks/${id}/transformer.js`)).href);
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
