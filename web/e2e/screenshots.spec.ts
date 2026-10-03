import { mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Regenerates the README screenshots and the frames for the tour GIF:
//   SCREENSHOTS=1 npx playwright test screenshots --project=desktop
//   python scripts/make_tour_gif.py web/test-results/tour-frames docs/images/site-tour.gif
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to regenerate docs/images/site-*.png");

const OUT = resolve(import.meta.dirname, "..", "..", "docs", "images");
const FRAMES = resolve(import.meta.dirname, "..", "test-results", "tour-frames");
let frameNo = 0;

async function shot(page: Page, name: string) {
  await page.screenshot({ path: resolve(OUT, `site-${name}.png`) });
}

async function frame(page: Page) {
  frameNo += 1;
  await page.screenshot({ path: resolve(FRAMES, `${String(frameNo).padStart(2, "0")}.png`) });
}

test.use({ viewport: { width: 1280, height: 860 } });

test("capture README screenshots", async ({ page }) => {
  rmSync(FRAMES, { recursive: true, force: true });
  mkdirSync(FRAMES, { recursive: true });
  const next = () => page.getByRole("button", { name: "Next" }).click();

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shot(page, "landing");
  await frame(page);

  await page.goto("/tour");
  await expect(page.getByRole("button", { name: "Process the invoice" })).toBeVisible();
  await frame(page);
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await frame(page);

  await next();
  await page.getByRole("button", { name: /Amount due 5,238/ }).click();
  await page.getByText("Amount Due: 5,238.00").first().scrollIntoViewIfNeeded();
  await shot(page, "tour-evidence");
  await frame(page);

  await next();
  await page.getByRole("button", { name: "What is the CEO's favourite colour?" }).click();
  await expect(page.getByText(/could not find enough supporting evidence/)).toBeVisible();
  await page.getByRole("button", { name: "What is the total amount due?" }).click();
  await expect(page.getByText("backed by the document").first()).toBeVisible();
  await shot(page, "tour-ask");
  await frame(page);

  await next();
  await page.getByRole("button", { name: "Process the balance sheet" }).click();
  await expect(page.getByText("Waiting for a person to check").first()).toBeVisible();
  await frame(page);

  await next();
  await expect(page.getByText("Why a person is needed")).toBeVisible();
  await page.getByRole("button", { name: "Use 9,570,000" }).click();
  await shot(page, "tour-review");
  await frame(page);

  await page.getByRole("button", { name: "Save correction and approve" }).click();
  await expect(page.getByText("You corrected and approved this document.")).toBeVisible();
  await frame(page);

  await next();
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Text in the document aimed at AI systems")).toBeVisible();
  await page.getByText("Text in the document aimed at AI systems").scrollIntoViewIfNeeded();
  await shot(page, "tour-injection");
  await frame(page);

  await next();
  await expect(page.getByText("Tamper check passed")).toBeVisible();
  await shot(page, "tour-audit");
  await frame(page);

  await next();
  await expect(page.getByRole("link", { name: "Try your own document" })).toBeVisible();
  await frame(page);
});
