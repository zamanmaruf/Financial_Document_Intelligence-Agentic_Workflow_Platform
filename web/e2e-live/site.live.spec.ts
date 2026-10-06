import AxeBuilder from "@axe-core/playwright";
import { devices, expect, test, type Page } from "@playwright/test";

import { VISITOR_STATE } from "../playwright.live.config";

const PAGES = [
  { path: "/", ready: "financial PDFs" },
  { path: "/tour", ready: "Process a clean invoice" },
  { path: "/try", ready: "Try it yourself" },
  { path: "/how-it-works", ready: "How it works" },
];

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.target.join(" ")}`));
}

test("every page and the engineer console load; unknown paths get proper 404s", async ({ request }) => {
  for (const path of [...PAGES.map((p) => p.path), "/ui/"]) {
    expect((await request.get(path)).status(), path).toBe(200);
  }
  const og = await request.get("/og.png");
  expect(og.status()).toBe(200);
  expect(og.headers()["content-type"]).toContain("image/png");

  const page404 = await request.get("/no-such-page");
  expect(page404.status()).toBe(404);
  expect(page404.headers()["content-type"]).toContain("text/html");

  const api404 = await request.get("/documents/no/such/route");
  expect(api404.status()).toBe(404);
  expect(api404.headers()["content-type"]).toContain("application/json");
});

test("security and caching headers are set", async ({ request }) => {
  const shell = await request.get("/tour");
  const h = shell.headers();
  expect(h["content-security-policy"]).toContain("script-src 'self'");
  expect(h["content-security-policy"]).not.toContain("unsafe-inline");
  expect(h["strict-transport-security"]).toContain("max-age=");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["cache-control"]).toContain("no-cache");

  const asset = (await shell.text()).match(/\/assets\/[\w.-]+\.js/)?.[0];
  expect(asset, "index.html references a bundled script").toBeTruthy();
  const assetRes = await request.get(asset ?? "");
  expect(assetRes.status()).toBe(200);
  expect(assetRes.headers()["cache-control"]).toContain("immutable");
});

test("the deployment runs real models and semantic search, not the offline engine", async ({ request }) => {
  const health = await (await request.get("/health")).json();
  expect(health.status).toBe("ok");
  expect(health.mock_mode).toBe(false);
  expect(health.providers.llm).toMatch(/^bedrock:/);
  expect(health.providers.embeddings).toMatch(/^bedrock:amazon\.titan-embed/);
  expect(health.checks).toEqual({ database: true, vector_store: true });

  const status = await (await request.get("/demo/status")).json();
  expect(status.offline_reason, "today's live-AI budget is already used up").toBeNull();
  expect(status.ai_mode).toBe("live");
  expect(status.model_provider).toBe("bedrock");
});

test("landing and how-it-works have no serious accessibility violations", async ({ page }) => {
  for (const { path, ready } of PAGES.filter((p) => p.path === "/" || p.path === "/how-it-works")) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(ready);
    expect(await seriousViolations(page), path).toEqual([]);
  }
});

test("pages load without CSP violations or console errors", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`${page.url()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`${page.url()}: ${e.message}`));
  for (const { path, ready } of PAGES) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(ready);
  }
  expect(problems).toEqual([]);
});

test("phone-sized screens don't scroll sideways", async ({ browser }) => {
  const context = await browser.newContext({ ...devices["Pixel 7"], storageState: VISITOR_STATE });
  const page = await context.newPage();
  try {
    for (const { path } of PAGES) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} scrolls sideways`).toBeLessThanOrEqual(0);
    }
  } finally {
    await context.close();
  }
});
