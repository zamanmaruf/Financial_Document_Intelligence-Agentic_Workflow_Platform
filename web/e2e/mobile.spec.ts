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
