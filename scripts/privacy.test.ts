import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterAll, expect, it, vi } from "vitest";

const roots: string[] = [];
const script = resolve("scripts/privacy.ts");
const loader = createRequire(import.meta.url).resolve("tsx");
afterAll(() => {
  for (const root of roots) rmSync(root, { recursive: true, force: true });
});

function repository() {
  const root = mkdtempSync(join(tmpdir(), "peer-link-privacy-"));
  roots.push(root);
  // Hooks and linked-worktree commands may export Git context that overrides cwd.
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([key]) => !key.startsWith("GIT_")),
  );
  const git = (...args: string[]) =>
    execFileSync("git", ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", ...args], {
      cwd: root,
      env,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  git("init", "-b", "main");
  git("config", "user.name", "Synthetic Test");
  git("config", "user.email", "test@example.com");
  const commit = (file: string, contents: string) => {
    mkdirSync(dirname(join(root, file)), { recursive: true });
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
      { cwd: root, env, encoding: "utf8" },
    );
  return { root, git, commit, base, scan };
}

it("isolates temporary repositories from inherited Git context", () => {
  const foreign = repository();
  const before = foreign.git("rev-parse", "HEAD");
  foreign.git("config", "user.name", "Original Synthetic Identity");
  try {
    vi.stubEnv("GIT_DIR", join(foreign.root, ".git"));
    vi.stubEnv("GIT_WORK_TREE", foreign.root);
    vi.stubEnv("GIT_INDEX_FILE", join(foreign.root, ".git/index"));
    const isolated = repository();
    isolated.commit("private.har", "SYNTHETIC_CAPTURE");
    expect(isolated.scan().status).toBe(1);
    expect(isolated.scan(`${isolated.base}..HEAD`).status).toBe(1);
    expect(foreign.git("rev-parse", "HEAD")).toBe(before);
    expect(foreign.git("status", "--porcelain")).toBe("");
    expect(foreign.git("config", "user.name")).toBe("Original Synthetic Identity");
  } finally {
    vi.unstubAllEnvs();
  }
});

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

it("does not attribute upstream-only files to a contributor merging main", () => {
  const r = repository();
  r.git("switch", "-c", "contrib");
  r.commit("README.md", "Synthetic contribution\n");
  r.git("switch", "main");
  const upstream = r.commit("private.har", "SYNTHETIC_UPSTREAM_CAPTURE");
  r.git("switch", "contrib");
  r.git("merge", "--no-ff", "-m", "Merge synthetic upstream", "main");
  const scan = r.scan(`${upstream}..HEAD`);
  expect(scan.status).toBe(0);
  expect(scan.stderr).not.toContain("private.har");
});

it.each(["capture.json", "screenshot.png", "docs/statement.pdf"])(
  "warns about historical files outside the layout after %s is removed",
  (file) => {
    const r = repository();
    const contents = file.endsWith(".json")
      ? '{"record":"SYNTHETIC_CONTENT_DO_NOT_PRINT"}'
      : "\0SYNTHETIC_CONTENT_DO_NOT_PRINT";
    const revision = r.commit(file, contents);
    r.git("rm", file);
    r.git("commit", "-m", "Remove synthetic file");
    expect(r.scan().status).toBe(0);
    const scan = r.scan(`${r.base}..HEAD`);
    expect(scan.status).toBe(0);
    expect(scan.stderr).toContain("Review before publishing");
    expect(scan.stderr).toContain(`${revision.slice(0, 12)}:${file}`);
    expect(scan.stderr).toContain("historical file outside the current repository layout");
    expect(scan.stderr + scan.stdout).not.toContain("SYNTHETIC_CONTENT_DO_NOT_PRINT");
  },
);

it("keeps permitted historical assets free of layout warnings", () => {
  const r = repository();
  r.commit("app/public/logos/synthetic.png", "\0SYNTHETIC_LOGO");
  const scan = r.scan(`${r.base}..HEAD`);
  expect(scan.status).toBe(0);
  expect(scan.stderr).toBe("");
});
