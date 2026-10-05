// Render the social card (og.html) to public/og.png. Needs `npx vite` running on port 5173.
import { chromium } from "@playwright/test";

const base = process.env.OG_BASE_URL ?? "http://127.0.0.1:5173";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
await page.emulateMedia({ reducedMotion: "reduce" });
await page.goto(`${base}/og.html`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await page.screenshot({ path: "public/og.png" });
await browser.close();
console.log("wrote public/og.png");
