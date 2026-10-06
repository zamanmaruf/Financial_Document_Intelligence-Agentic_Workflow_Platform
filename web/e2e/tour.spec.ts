import { expect, test, type Page } from "@playwright/test";

function highlightChip(page: Page, name: RegExp) {
  return page.getByRole("group", { name: "Highlights on the page" }).getByRole("button", { name });
}

async function next(page: Page) {
  await page.getByRole("button", { name: "Continue" }).click();
}

test("the guided tour runs end to end against the real API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("financial PDFs");
  await expect(page.getByRole("button", { name: /Offline engine/ })).toBeVisible();
  await page.getByRole("link", { name: /Take the 3-minute tour/ }).first().click();

  // 1. Clean invoice: Continue stays locked until the run completes.
  await expect(page.getByRole("heading", { name: "Process a clean invoice" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await next(page);

  // 2. Fields with evidence.
  await expect(page).toHaveURL(/step=2/);
  const amount = page.getByRole("button", { name: /Amount due 5,238/ });
  await expect(amount).toBeVisible();
  await amount.click();
  await expect(page.getByText("Amount Due: 5,238.00").first()).toBeVisible();
  await expect(highlightChip(page, /Amount due/)).toHaveAttribute("aria-pressed", "true");
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

  // 6. Hidden instructions are flagged, not followed, and boxed in red on the page.
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Text in the document aimed at AI systems")).toBeVisible();
  await expect(page.getByText(/ignore all previous instructions/).first()).toBeVisible();
  await expect(highlightChip(page, /Instruction aimed at AI/)).toBeVisible();
  await expect(page.locator('[data-highlight="injection:0"] > div').first()).toBeVisible();
  await next(page);

  // 7. Audit trail with a passing tamper check, including the visitor's correction.
  await expect(page.getByText("Tamper check passed")).toBeVisible();
  await expect(page.getByText("Corrected by you (as reviewer)")).toBeVisible();
  await next(page);

  // 8. Wrap-up.
  await expect(page.getByRole("link", { name: "Try your own document" })).toBeVisible();
});

test("selecting a value boxes its evidence on the page, and the boxes are keyboard reachable", async ({ page }) => {
  await page.goto("/tour");
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await next(page);

  const viewer = page.getByTestId("document-viewer");
  await expect(viewer.getByRole("img", { name: /Page 1 of 1/ })).toBeVisible();
  await page.getByRole("button", { name: /Vendor Acme Office Supplies/ }).click();
  await expect(highlightChip(page, /Vendor/)).toHaveAttribute("aria-pressed", "true");
  await expect(viewer.locator('[data-highlight="field:vendor"][data-active] > div').first()).toBeVisible();

  // Roving focus: arrow keys move between highlight chips and box the focused one.
  await highlightChip(page, /Vendor/).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(":focus")).toHaveText(/Customer/);
  await expect(highlightChip(page, /Customer/)).toHaveAttribute("aria-pressed", "true");
  await expect(viewer.locator('[data-highlight="field:customer"][data-active] > div').first()).toBeVisible();
});

test("the page zooms to the selected box and opens full screen with the same selection", async ({ page }) => {
  await page.goto("/tour");
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await next(page);

  const viewer = page.getByTestId("document-viewer");
  await expect(viewer.getByRole("img", { name: /Page 1 of 1/ })).toBeVisible();
  const zoomToBox = viewer.getByRole("button", { name: "Zoom to the selected box" });
  const zoomLevel = viewer.getByTestId("zoom-level");
  await expect(zoomToBox).toBeDisabled();

  await page.getByRole("button", { name: /Amount due 5,238/ }).click();
  await zoomToBox.click();
  await expect(zoomLevel).not.toHaveText("100%");
  const box = viewer.locator('[data-highlight="field:amount_due"][data-active] > div').first();
  await expect(box).toBeInViewport();

  // Fit, then double-click the box to zoom back in on it.
  await viewer.getByRole("button", { name: "Fit" }).click();
  await expect(zoomLevel).toHaveText("100%");
  await box.dblclick();
  await expect(zoomLevel).not.toHaveText("100%");
  await viewer.getByRole("button", { name: "Fit" }).click();

  // Full screen: same boxes and selection; Esc closes and returns focus to the button.
  const expand = viewer.getByRole("button", { name: "Expand to full screen" });
  await expand.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const big = dialog.getByTestId("document-viewer-expanded");
  await expect(big.locator('[data-highlight="field:amount_due"][data-active] > div').first()).toBeVisible();
  await highlightChip(page, /Vendor/).click();
  await expect(big.locator('[data-highlight="field:vendor"][data-active] > div').first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(expand).toBeFocused();
  await expect(highlightChip(page, /Vendor/)).toHaveAttribute("aria-pressed", "true");
});

test("arrow keys move between tour steps once a step's action is done", async ({ page }) => {
  await page.goto("/tour");
  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toHaveText("Process a clean invoice");
  await page.keyboard.press("ArrowRight");
  await expect(page).not.toHaveURL(/step=2/);

  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await heading.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/step=2/);
  await expect(heading).toHaveText("See what it found");
  await expect(heading).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(heading).toHaveText("Process a clean invoice");
  await page.keyboard.press("Enter");
  await expect(heading).toHaveText("See what it found");
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
