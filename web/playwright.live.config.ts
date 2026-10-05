import { defineConfig, devices } from "@playwright/test";

// Smoke tests against a deployed demo site, with real AI behind it. Not run in CI.
//   LIVE_URL=https://example.cloudfront.net npx playwright test -c playwright.live.config.ts
// Production allows 5 new visitor sessions per IP per hour; one run uses 2 of them.
export const LIVE_URL = (process.env.LIVE_URL ?? "https://d1cpufi9ii8q1y.cloudfront.net").replace(/\/$/, "");
export const VISITOR_STATE = "test-results/live/visitor.json";

export default defineConfig({
  testDir: "e2e-live",
  outputDir: "test-results/live/artifacts",
  globalSetup: "./e2e-live/global-setup.ts",
  timeout: 120_000,
  expect: { timeout: 45_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: LIVE_URL,
    storageState: VISITOR_STATE,
    trace: "retain-on-failure",
  },
});
