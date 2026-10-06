import { expect, test } from "@playwright/test";

test("navigation works on a phone-sized screen without horizontal scrolling", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /menu/i }).click();
  await page.locator("#mobile-menu").getByRole("link", { name: "Try it yourself" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Try it yourself");

  for (const path of ["/", "/tour", "/try", "/how-it-works"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${path} scrolls sideways`).toBeLessThanOrEqual(0);
  }
});

test("on a phone, showing a value on the page opens the full-screen viewer at that box", async ({ page }) => {
  await page.goto("/tour");
  await page.getByRole("button", { name: "Process the invoice" }).click();
  await expect(page.getByText("Ready: all checks passed")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  const amount = page.getByRole("button", { name: /Amount due 5,238/ });
  await amount.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("zoom-level")).not.toHaveText("100%");
  await expect(dialog.locator('[data-highlight="field:amount_due"][data-active] > div').first()).toBeInViewport();
  await dialog.getByRole("button", { name: "Close full screen" }).click();
  await expect(dialog).toBeHidden();
  await expect(amount).toBeFocused();
  // The inline viewer is still behind its toggle.
  await expect(page.getByRole("button", { name: "Show the document" })).toBeVisible();
});

test("the playground tabs use short labels on a phone and keep their full names", async ({ page }) => {
  await page.goto("/try");
  await page.getByRole("button", { name: /A balance sheet with conflicting totals/ }).click();
  for (const [name, short] of [
    ["Ask questions", "Ask"],
    ["Audit trail", "Audit"],
  ] as const) {
    const tab = page.getByRole("tab", { name });
    await expect(tab.getByText(short, { exact: true })).toBeVisible();
    await expect(tab.getByText(name, { exact: true })).toBeHidden();
  }
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Try it yourself");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
