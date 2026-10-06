import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const PAGES = [
  { path: "/", ready: "financial PDFs" },
  { path: "/tour", ready: "Process a clean invoice" },
  { path: "/try", ready: "Try it yourself" },
  { path: "/how-it-works", ready: "How it works" },
];

// Entrance animations start from transparent; scan the settled page, as a reader sees it.
test.use({ contextOptions: { reducedMotion: "reduce" } });

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.target.join(" ")} ${n.failureSummary ?? ""}`));
}

for (const { path, ready } of PAGES) {
  test(`${path} has no serious accessibility violations`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(ready);
    expect(await seriousViolations(page)).toEqual([]);
  });
}

test("processed results have no serious accessibility violations", async ({ page }) => {
  await page.goto("/try");
  await page.getByRole("button", { name: /A balance sheet with conflicting totals/ }).click();
  await expect(page.getByRole("tab", { name: /Results/ })).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
  await page.getByRole("tab", { name: /Review/ }).click();
  await expect(page.getByText("Why a person is needed")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("the tour stage with the document viewer has no serious accessibility violations", async ({ page }) => {
  await page.goto("/tour");
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /Amount due 5,238/ }).click();
  await expect(page.getByTestId("document-viewer").getByRole("img")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);

  await page.getByRole("button", { name: "Expand to full screen" }).click();
  await expect(page.getByRole("dialog").getByRole("img", { name: /Page 1 of 1/ })).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("the not-found page has no serious accessibility violations", async ({ page }) => {
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("the site loads without CSP violations or console errors", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(m.text());
  });
  page.on("pageerror", (e) => problems.push(e.message));
  for (const { path, ready } of PAGES) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(ready);
  }
  expect(problems).toEqual([]);
});
