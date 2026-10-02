import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  type BankPath,
  CHECK_DEFINITIONS,
  CONTRIBUTION_SHAPE,
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

export type Repository = {
  files: string[];
  read(file: string): string;
  exists(file: string): boolean;
  revision(sha: string, bankFolder: string): "ok" | "missing-commit" | "missing-bank";
  now: number;
};

type Bank = BankPath & { files: Set<string> };

/** Validate every tracked or new file below banks/. Returns all errors, not just the first. */
export function validateRepository(repo: Repository) {
  const errors: string[] = checkRepositoryLayout(repo.files);
  const banks = new Map<string, Bank>();
  for (const file of repo.files) {
    const kind = classifyBankPath(file);
    if (!kind) continue;
    if ("error" in kind) {
      errors.push(kind.error);
      continue;
    }
    const bank = banks.get(kind.bank) ?? { ...kind, files: new Set<string>() };
    bank.files.add(kind.rest);
    banks.set(kind.bank, bank);
  }
  const counts = { adapters: 0, fixtures: 0, reports: 0 };
  for (const bank of [...banks.values()].sort((a, b) => a.bank.localeCompare(b.bank))) {
    const at = (rest: string) => `${bank.bank}/${rest}`;
    const json = (rest: string) => {
      const parsed = parseJson(at(rest), repo.read(at(rest)));
      if (parsed.error) errors.push(parsed.error);
      return parsed.value;
    };
    const has = (rest: string) => bank.files.has(rest);
    const fixtures = [...bank.files].filter((f) => f.startsWith("fixtures/")).sort();
    const tests = [...bank.files].filter((f) => f.endsWith(".test.ts"));
    if (!has("README.md"))
      errors.push(`${at("README.md")}: missing; document scope, semantics and acquisition`);
    if (!fixtures.length)
      errors.push(`${bank.bank}: add at least one fixtures/<case>.synthetic.json`);
    let manifest: Record<string, unknown> | undefined;
    if (has("manifest.json")) {
      counts.adapters++;
      if (has("README.md"))
        errors.push(...checkReadme(at("README.md"), repo.read(at("README.md"))));
      const value = json("manifest.json");
      if (value !== undefined) {
        errors.push(
          ...validateManifest(at("manifest.json"), value, bank, (logo) =>
            repo.exists(`app/public${logo}`),
          ),
        );
        manifest = value as Record<string, unknown>;
      }
      if (!has("transformer.js"))
        errors.push(`${at("transformer.js")}: missing; the manifest needs a pure transformer`);
      else
        errors.push(
          ...checkTransformerSource(
            at("transformer.js"),
            repo.read(at("transformer.js")),
            manifest?.entrypoint,
          ),
        );
      if (!tests.length)
        errors.push(`${bank.bank}: add transformer.test.ts with positive and negative cases`);
      for (const test of tests)
        if (!/from\s+["']\.\/transformer(\.js)?["']/.test(repo.read(at(test))))
          errors.push(`${at(test)}: must import the adapter from "./transformer.js"`);
    } else
      errors.push(
        `${bank.bank}: add manifest.json; every bank folder is an adapter (run npm run new-bank -- ${bank.id})`,
      );
    let supported = 0;
    for (const fixture of fixtures) {
      const value = json(fixture);
      if (value === undefined) continue;
      errors.push(...validateFixture(at(fixture), value));
      if ((value as { expected?: { outcome?: unknown } }).expected?.outcome === "supported")
        supported++;
      counts.fixtures++;
    }
    if (manifest && fixtures.length && !supported)
      errors.push(
        `${bank.bank}: adapters need at least one fixture whose expected.outcome is supported`,
      );
    for (const report of [...bank.files].filter((f) => f.startsWith("reports/")).sort()) {
      const value = json(report);
      if (value === undefined) continue;
      errors.push(
        ...validateReport(at(report), value, bank, {
          manifestSurface: typeof manifest?.surface === "string" ? manifest.surface : undefined,
          fixtureExists: (ref) => bank.files.has(ref),
          revision: (sha) => repo.revision(sha, bank.bank),
          now: repo.now,
        }),
      );
      counts.reports++;
    }
  }
  if (!counts.adapters || !counts.fixtures)
    errors.push("banks/: at least one adapter and one fixture are required");
  return { errors: [...new Set(errors)], counts };
}

function gitRevision(sha: string, bankFolder: string) {
  try {
    execFileSync("git", ["cat-file", "-e", `${sha}^{commit}`], { stdio: "ignore" });
  } catch {
    return "missing-commit" as const;
  }
  try {
    execFileSync("git", ["cat-file", "-e", `${sha}:${bankFolder}/manifest.json`], {
      stdio: "ignore",
    });
    return "ok" as const;
  } catch {
    return "missing-bank" as const;
  }
}

const git = (args: string[]) =>
  execFileSync("git", args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 })
    .split("\0")
    .filter(Boolean);

/**
 * The base to compare a contribution against: `--contribution-base <ref>` locally, or the
 * merge parent of a pull request from a fork in GitHub Actions (read from the event file the
 * runner provides; no token or network). Returns null for maintainer branches and pushes.
 */
function contributionBase(): string | null {
  const flag = process.argv.indexOf("--contribution-base");
  if (flag >= 0) {
    const ref = process.argv[flag + 1];
    if (!ref || ref.startsWith("-"))
      throw new Error("Usage: npm run validate -- --contribution-base origin/main");
    return execFileSync("git", ["merge-base", ref, "HEAD"], { encoding: "utf8" }).trim();
  }
  const eventPath = process.env.GITHUB_EVENT_PATH;
  if (process.env.GITHUB_EVENT_NAME !== "pull_request" || !eventPath || !existsSync(eventPath))
    return null;
  const pull = JSON.parse(readFileSync(eventPath, "utf8")).pull_request;
  if (!pull || pull.head?.repo?.full_name === pull.base?.repo?.full_name) return null;
  const parents = execFileSync("git", ["rev-list", "--parents", "-n", "1", "HEAD"], {
    encoding: "utf8",
  })
    .trim()
    .split(" ");
  return parents.length === 3
    ? parents[1]
    : execFileSync("git", ["merge-base", pull.base.sha, "HEAD"], { encoding: "utf8" }).trim();
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const files = git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"]).filter(
    (file) => existsSync(file),
  );
  const { errors, counts } = validateRepository({
    files,
    read: (file) => readFileSync(file, "utf8"),
    exists: (file) => existsSync(resolve(file)),
    revision: gitRevision,
    now: Date.now(),
  });
  const base = contributionBase();
  if (base) {
    const added = new Set([
      ...git(["diff", "--name-only", "--diff-filter=AR", "-z", base, "HEAD"]),
      ...git(["diff", "--cached", "--name-only", "--diff-filter=AR", "-z"]),
      ...git(["ls-files", "--others", "--exclude-standard", "-z"]),
    ]);
    errors.push(...checkContributorAdditions([...added].sort()));
    const changedChecks = git([
      "diff",
      "--name-only",
      "--diff-filter=M",
      "-z",
      base,
      "HEAD",
    ]).filter((file) => CHECK_DEFINITIONS.test(file));
    if (changedChecks.length)
      console.warn(
        `This contribution modifies files that define the checks themselves; reviewers rerun main's checks:\n${changedChecks.map((f) => `- ${f}`).join("\n")}\n`,
      );
  }
  if (errors.length) {
    console.error(`Validation failed with ${errors.length} problem(s):\n`);
    console.error(errors.map((e) => `- ${e}`).join("\n"));
    if (errors.some((e) => /repository layout|pull requests from forks/.test(e)))
      console.error(`\n${CONTRIBUTION_SHAPE}`);
    console.error(
      "\nSee skills/contribute-bank/SKILL.md for the folder contract. Run npm run new-bank -- <country>/<bank> for a template.",
    );
    process.exitCode = 1;
  } else
    console.log(
      `Validated ${counts.adapters} adapter(s), ${counts.fixtures} fixture(s) and ${counts.reports} report(s)${base ? `; contribution additions checked against ${base.slice(0, 12)}` : ""}.`,
    );
}
