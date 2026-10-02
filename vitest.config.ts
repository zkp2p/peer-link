import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    include: ["banks/**/*.test.ts", "lib/**/*.test.ts", "scripts/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["banks/**/transformer.js", "lib/**/*.ts", "scripts/*-rules.ts"],
      exclude: ["**/*.test.ts"],
      thresholds: { perFile: true, lines: 95, functions: 100, branches: 90, statements: 95 },
    },
  },
});
