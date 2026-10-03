import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterAll, expect, it } from "vitest";

const roots: string[] = [];
const script = resolve("scripts/privacy.ts");
const loader = createRequire(import.meta.url).resolve("tsx");
afterAll(() => {
  for (const root of roots) rmSync(root, { recursive: true, force: true });
});

function repository() {
  const root = mkdtempSync(join(tmpdir(), "peer-link-privacy-"));
  roots.push(root);
  const git = (...args: string[]) =>
    execFileSync("git", ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", ...args], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  git("init", "-b", "main");
  git("config", "user.name", "Synthetic Test");
  git("config", "user.email", "test@example.com");
  const commit = (file: string, contents: string) => {
    writeFileSync(join(root, file), contents);
    git("add", file);
    git("commit", "-m", "Synthetic fixture");
    return git("rev-parse", "HEAD");
  };
  const base = commit("README.md", "Synthetic repository\n");
  const scan = (range?: string) =>
    spawnSync(
      process.execPath,
      ["--import", loader, script, ...(range ? ["--range", range] : [])],
      { cwd: root, encoding: "utf8" },
    );
  return { root, git, commit, base, scan };
}

it("finds a forbidden capture removed by a later commit without printing its contents", () => {
  const r = repository();
  const revision = r.commit("private.har", "SYNTHETIC_CAPTURE_CONTENT_DO_NOT_PRINT");
  r.git("rm", "private.har");
  r.git("commit", "-m", "Remove synthetic capture");
  expect(r.scan().status).toBe(0);
  const scan = r.scan(`${r.base}..HEAD`);
  expect(scan.status).toBe(1);
  expect(scan.stderr).toContain(`${revision.slice(0, 12)}:private.har`);
  expect(scan.stderr + scan.stdout).not.toContain("SYNTHETIC_CAPTURE_CONTENT_DO_NOT_PRINT");
});

it("scans files introduced only in a merge commit even when later removed", () => {
  const r = repository();
  r.git("switch", "-c", "side");
  r.commit("side.md", "Synthetic side\n");
  r.git("switch", "main");
  r.commit("main.md", "Synthetic main\n");
  r.git("merge", "--no-commit", "--no-ff", "side");
  const merge = r.commit("private.har", "SYNTHETIC_MERGE_CAPTURE");
  r.git("rm", "private.har");
  r.git("commit", "-m", "Remove synthetic capture");
  expect(r.scan().status).toBe(0);
  const scan = r.scan(`${r.base}..HEAD`);
  expect(scan.status).toBe(1);
  expect(scan.stderr).toContain(`${merge.slice(0, 12)}:private.har`);
});

it("does not rescan an unchanged capture inherited from an excluded base", () => {
  const r = repository();
  const base = r.commit("private.har", "SYNTHETIC_OLD_CAPTURE");
  r.git("switch", "-c", "side");
  r.commit("side.md", "Synthetic side\n");
  r.git("switch", "main");
  r.commit("main.md", "Synthetic main\n");
  r.git("merge", "--no-ff", "-m", "Merge synthetic branches", "side");
  expect(r.scan(`${base}..HEAD`).status).toBe(0);
});
