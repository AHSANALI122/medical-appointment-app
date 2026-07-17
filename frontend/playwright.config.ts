import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

/**
 * F30 — e2e suite. Two projects, so CI can run the critical path on every PR
 * and the whole suite nightly (spec.md F30) from one config:
 *
 *   npx playwright test --project=critical   # every PR
 *   npx playwright test                      # nightly / local
 *
 * Requires a running backend (uvicorn on :8000) with a seeded DB —
 * `uv run python scripts/seed_demo.py`. Playwright starts the frontend
 * itself via webServer below; the backend is not started here because it
 * needs migrations + seed against a real Postgres, which CI does as
 * explicit steps (see .github/workflows/e2e.yml).
 */
export default defineConfig({
  testDir: "./e2e",
  // Booking is inherently stateful — slots get consumed, and the state
  // machine caps active drafts per profile. Parallel workers racing for the
  // same demo doctor's slots would produce flaky 409s that look like bugs.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "critical",
      testMatch: /critical-path\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "full",
      testIgnore: /critical-path\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    // Production build, not `next dev`: dev-mode compile-on-first-request
    // makes the first navigation of each route take seconds, which reads as
    // a flaky timeout rather than a real failure.
    command: "npm run build && npm run start",
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
