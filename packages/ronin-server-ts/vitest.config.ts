import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: false,
    include: ["tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.ts"],
      exclude: ["src/server.ts"],
      // Only enforced when coverage is run (`npm run test:coverage`, which needs the sidecar so the
      // delta tests execute). Set below the current full-suite numbers (~76% stmts / 80% lines /
      // 65% branch) to catch regressions without being brittle. NOT applied to unit-only runs.
      thresholds: { statements: 70, lines: 72, functions: 68, branches: 58 },
    },
    pool: "forks",
  },
});
