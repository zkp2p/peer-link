import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { checkRepositoryLayout, classifyBankPath } from "./contribution-rules";
import { MAX_SCAN_BYTES, scanFile } from "./privacy-rules";

/**
 * Modes:
 *   npm run privacy                       tracked and untracked (non-ignored) working-tree files
 *   npm run privacy -- --staged           the exact index contents you are about to commit
 *   npm run privacy -- --range A..B       every file version added or changed by each commit in
 *                                         A..B, including ones a later commit deleted. Use
 *                                         origin/main..HEAD before pushing a branch.
 */
const args = process.argv.slice(2);
const rangeIndex = args.indexOf("--range");
const range =
  rangeIndex >= 0 ? args[rangeIndex + 1] : args.find((a) => a.startsWith("--range="))?.slice(8);
const usage = (message: string): never => {
  console.error(message);
  process.exit(1);
};
if (rangeIndex >= 0 && (!range || range.startsWith("-")))
  usage("Usage: npm run privacy -- --range origin/main..HEAD");
const git = (argv: string[]) =>
  execFileSync("git", argv, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
const decode = (bytes: Buffer) =>
  bytes.subarray(0, 8192).includes(0) ? null : bytes.toString("utf8");
const blob = (spec: string) => {
  const size = Number(git(["cat-file", "-s", spec]).trim());
  if (size > MAX_SCAN_BYTES) return { content: null, size };
  return {
    content: decode(
      execFileSync("git", ["cat-file", "blob", spec], { maxBuffer: MAX_SCAN_BYTES + 1 }),
    ),
    size,
  };
};

type Target = { label: string; file: string; load: () => { content: string | null; size: number } };
const targets: Target[] = [];
const list = (out: string) => out.split("\0").filter(Boolean);
if (range) {
  let commits: string[] = [];
  try {
    commits = list(
      execFileSync("git", ["rev-list", range], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      }).replaceAll("\n", "\0"),
    );
  } catch {
    usage(`Unknown revision range ${range}; fetch the base first (git fetch origin main)`);
  }
  for (const commit of commits)
    for (const file of list(
      git([
        "diff-tree",
        "--no-commit-id",
        "-r",
        "--root",
        // For merges, scan resolutions changed from all parents. Ordinary parent
        // commits are scanned separately; don't re-scan unchanged upstream history.
        "-c",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        commit,
      ]),
    ))
      targets.push({
        label: `${commit.slice(0, 12)}:${file}`,
        file,
        load: () => blob(`${commit}:${file}`),
      });
} else if (args.includes("--staged")) {
  for (const file of list(git(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"])))
    targets.push({ label: file, file, load: () => blob(`:${file}`) });
} else {
  for (const file of list(git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"])))
    if (existsSync(file))
      targets.push({
        label: file,
        file,
        load: () => {
          const size = statSync(file).size;
          return { content: size > MAX_SCAN_BYTES ? null : decode(readFileSync(file)), size };
        },
      });
}

const findings: string[] = [];
const warnings: string[] = [];
for (const target of targets) {
  if (range) {
    const bankPath = classifyBankPath(target.file);
    if (checkRepositoryLayout([target.file]).length || (bankPath && "error" in bankPath))
      warnings.push(
        `${target.label}: historical file outside the current repository layout; inspect it locally for captures or personal data even if it was later deleted`,
      );
  }
  const { content, size } = target.load();
  const result = scanFile(target.file, content, size);
  const relabel = (line: string) => line.replace(target.file, target.label);
  findings.push(...result.findings.map(relabel));
  warnings.push(...result.warnings.map(relabel));
}
if (warnings.length)
  console.warn(`Review before publishing:\n${warnings.map((w) => `- ${w}`).join("\n")}\n`);
if (findings.length) {
  console.error(`Privacy check failed (${findings.length}). Values are not printed:\n`);
  console.error(findings.map((f) => `- ${f}`).join("\n"));
  console.error(
    "\nRemove the data from every commit (rewrite the branch before pushing), then rerun. See docs/privacy.md.",
  );
  process.exitCode = 1;
} else
  console.log(
    `Privacy heuristics passed for ${targets.length} file version(s). Human pre-publication review is still required.`,
  );
