import { expect, test, type Page } from "@playwright/test";

async function next(page: Page) {
  await page.getByRole("button", { name: "Next" }).click();
}

test("the guided tour runs end to end against the real API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("financial PDFs");
  await expect(page.getByRole("button", { name: /Offline engine/ })).toBeVisible();
  await page.getByRole("link", { name: /Start the 3-minute tour/ }).click();

  // 1. Clean invoice: Next stays locked until the run completes.
  await expect(page.getByRole("heading", { name: "Process a clean invoice" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await next(page);

  // 2. Fields with evidence.
  await expect(page).toHaveURL(/step=2/);
  const amount = page.getByRole("button", { name: /Amount due 5,238/ });
  await expect(amount).toBeVisible();
  await amount.click();
  await expect(page.getByText("Amount Due: 5,238.00").first()).toBeVisible();
  await next(page);

  // 3. A cited answer, then a refusal.
  await page.getByRole("button", { name: "What is the total amount due?" }).click();
  await expect(page.getByText("backed by the document").first()).toBeVisible();
  await page.getByRole("button", { name: "What is the CEO's favourite colour?" }).click();
  await expect(page.getByText(/could not find enough supporting evidence/)).toBeVisible();
  await next(page);

  // 4. Conflicting totals go to a person.
  await page.getByRole("button", { name: "Process the balance sheet" }).click();
  await expect(page.getByText("Waiting for a person to check").first()).toBeVisible();
  await expect(page.getByText("Document shows different values").first()).toBeVisible();
  await next(page);

  // 5. The visitor corrects the total and approves.
  await expect(page.getByText("The document shows different values for the same figure.")).toBeVisible();
  await page.getByRole("button", { name: "Use 9,570,000" }).click();
  await page.getByRole("button", { name: "Save correction and approve" }).click();
  await expect(page.getByText("You corrected and approved this document.")).toBeVisible();
  await next(page);

  // 6. Hidden instructions are flagged, not followed.
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Text in the document aimed at AI systems")).toBeVisible();
  await expect(page.getByText(/ignore all previous instructions/).first()).toBeVisible();
  await next(page);

  // 7. Audit trail with a passing tamper check, including the visitor's correction.
  await expect(page.getByText("Tamper check passed")).toBeVisible();
  await expect(page.getByText("Corrected by you (as reviewer)")).toBeVisible();
  await next(page);

  // 8. Wrap-up.
  await expect(page.getByRole("link", { name: "Try your own document" })).toBeVisible();
});

test("deep links to a step that needs an earlier run explain what to do", async ({ page }) => {
  await page.goto("/tour?step=5");
  await expect(page.getByText("Process the balance sheet first.")).toBeVisible();
  await page.getByRole("button", { name: "Go to that step" }).click();
  await expect(page).toHaveURL(/step=4/);
});

test("unknown pages show a friendly not-found page", async ({ page }) => {
  const response = await page.goto("/no-such-page");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("link", { name: /home|start/i }).first()).toBeVisible();
});
