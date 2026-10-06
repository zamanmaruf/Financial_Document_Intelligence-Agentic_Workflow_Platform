import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// The suite runs against the real FastAPI app in demo mode with the offline (mock) engine,
// serving the production build from web/dist. Run `npm run build` first.
const PORT = 8765;
const repoRoot = resolve(import.meta.dirname, "..");
const venvPython = join(repoRoot, ".venv", "bin", "python");
const python = process.env.PYTHON ?? (existsSync(venvPython) ? venvPython : "python");

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
    // Safari engine, run locally: WEBKIT=1 npx playwright install webkit && WEBKIT=1 npx playwright test --project=webkit
    ...(process.env.WEBKIT
      ? [{ name: "webkit", use: { ...devices["Desktop Safari"] }, testMatch: /(tour|a11y)\.spec\.ts/ }]
      : []),
  ],
  webServer: {
    command: `"${python}" -m uvicorn app.api.main:app --host 127.0.0.1 --port ${PORT}`,
    cwd: repoRoot,
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      // Explicit values override anything in a developer's .env: no paid providers in tests.
      DOCINTEL_LLM_PROVIDER: "mock",
      DOCINTEL_EMBEDDING_PROVIDER: "hashing",
      DOCINTEL_VECTOR_STORE: "memory",
      DOCINTEL_OCR_PROVIDER: "none",
      DOCINTEL_AUTH_ENABLED: "false",
      DOCINTEL_DEMO_MODE: "true",
      DOCINTEL_DEMO_SECRET: randomBytes(32).toString("hex"),
      DOCINTEL_DEMO_COOKIE_SECURE: "false",
      DOCINTEL_DEMO_SESSIONS_PER_IP_HOUR: "1000",
      DOCINTEL_DEMO_REQUESTS_PER_IP_MINUTE: "2000",
      DOCINTEL_DEMO_DOCS_PER_SESSION_DAY: "50",
      DOCINTEL_DATA_DIR: mkdtempSync(join(tmpdir(), "docintel-e2e-")),
      DOCINTEL_SITE_DIR: join(repoRoot, "web", "dist"),
      DOCINTEL_LOG_LEVEL: "WARNING",
      DOCINTEL_LOG_JSON: "false",
    },
  },
});
