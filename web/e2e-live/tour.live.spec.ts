import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

// The full guided tour against real Claude: 3 documents and 2 questions, about $0.02.
// Model output varies, so this asserts on statuses and structure rather than exact wording.

async function next(page: Page) {
  await page.getByRole("button", { name: "Continue" }).click();
}

test("the guided tour runs end to end on live AI", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Live AI" }), "badge should read Live AI").toBeVisible();
  await page.getByRole("link", { name: /Take the 3-minute tour/ }).first().click();

  // 1. Clean invoice.
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await next(page);

  // 2. Fields with evidence.
  await expect(page).toHaveURL(/step=2/);
  const amount = page.getByRole("button", { name: /Amount due \d/ });
  await expect(amount).toBeVisible();
  await amount.click();
  await expect(page.getByText(/Amount Due:/).first()).toBeVisible();
  await next(page);

  // 3. A cited answer, then a refusal.
  const answers = page.getByTestId("answer");
  await page.getByRole("button", { name: "What is the total amount due?" }).click();
  await expect(answers.first()).toContainText("backed by the document");
  await expect(answers.first()).toContainText("Sources");
  await expect(answers.first()).not.toContainText("Offline engine");
  await page.getByRole("button", { name: "What is the CEO's favourite colour?" }).click();
  await expect(answers).toHaveCount(2);
  await expect(answers.first()).toContainText(/No answer given/i);
  await next(page);

  // 4. Conflicting totals go to a person.
  await page.getByRole("button", { name: "Process the balance sheet" }).click();
  await expect(page.getByText("Waiting for a person to check").first()).toBeVisible();
  await next(page);

  // 5. Resolve the review: pick a different value the document contains, or approve as is.
  const panel = page.getByTestId("review-panel");
  await expect(panel.getByText("Why a person is needed")).toBeVisible();
  const choices = panel.getByRole("button", { name: /^Use / });
  if ((await choices.count()) > 1) await choices.last().click();
  const save = panel.getByRole("button", { name: "Save correction and approve" });
  await ((await save.isVisible()) ? save : panel.getByRole("button", { name: "Approve as is" })).click();
  await expect(page.getByText(/You (corrected and approved|approved) this document\./)).toBeVisible();
  await next(page);

  // 6. Hidden instructions are flagged, not followed.
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Text in the document aimed at AI systems")).toBeVisible();
  await expect(page.getByText(/ignore all previous instructions/i).first()).toBeVisible();
  await next(page);

  // 7. Audit trail with the visitor's decision and a passing tamper check.
  await expect(page.getByText("Tamper check passed")).toBeVisible();
  await expect(page.getByText(/(Corrected|Approved) by you \(as reviewer\)/).first()).toBeVisible();
  await next(page);

  // 8. Wrap-up, still on live AI.
  await expect(page.getByRole("link", { name: "Try your own document" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Live AI" })).toBeVisible();
});

test("a scanned upload is read with OCR and its values are boxed on the page", async ({ page }) => {
  // One upload, about $0.01. The page has no text layer, so boxes come from text recognition.
  const scanned = resolve(import.meta.dirname, "../../sample_data/pdfs/edge_scanned_invoice.pdf");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/try");
  const located = page.waitForResponse(
    (r) => r.url().includes("/locate") && r.request().method() === "POST",
    { timeout: 120_000 },
  );
  await page.locator('input[type="file"]').setInputFiles(scanned);
  await expect(page.getByRole("tab", { name: /Results/ })).toBeVisible({ timeout: 120_000 });
  const body = (await (await located).json()) as {
    positions: string;
    results: { matches: { rects: unknown[] }[] }[];
  };
  expect(body.positions).toBe("ocr");
  expect(body.results.some((r) => r.matches.some((m) => m.rects.length > 0))).toBe(true);
  await expect(page.getByText("Boxes on scanned pages come from text recognition")).toBeVisible();
});
