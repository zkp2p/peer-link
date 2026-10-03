import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const workflow = readFileSync(".github/workflows/ci.yml", "utf8");
const gate = /^ {2}verify:\n([\s\S]*?)(?=^ {2}[\w-]+:|$(?![\s\S]))/m.exec(workflow)?.[1] ?? "";
const shell = / {8}run: \|\n((?: {10}.*\n)+)/.exec(gate)?.[1].replace(/^ {10}/gm, "");

describe("required verify gate", () => {
  it("always includes repository and trusted-fork checks under the existing required name", () => {
    expect(gate).toContain("needs: [repository-checks, trusted-contribution-checks]");
    expect(gate).toMatch(/if: \$\{\{ always\(\) }}/);
    expect(shell).toBeTruthy();
  });
  for (const fork of [true, false]) {
    for (const repository of ["success", "failure", "cancelled", "skipped"]) {
      for (const trusted of ["success", "failure", "cancelled", "skipped"]) {
        it(`fork=${fork}, repository=${repository}, trusted=${trusted}`, () => {
          if (!shell) throw new Error("Missing required-check gate");
          const result = spawnSync("bash", ["-e", "-c", shell], {
            env: {
              PATH: process.env.PATH,
              REPOSITORY_RESULT: repository,
              TRUSTED_RESULT: trusted,
              IS_FORK: String(fork),
            },
          });
          expect(result.status === 0).toBe(
            repository === "success" && trusted === (fork ? "success" : "skipped"),
          );
        });
      }
    }
  }
});
