import { expect, test } from "@playwright/test";

import { LIVE_URL } from "../playwright.live.config";

// Visitor A is the suite's shared session (page.request carries its cookie). Visitor B is a
// fresh session that owns one document; loading a sample makes no AI calls.
// Request contexts made inside tests inherit the config's storageState, so start them empty.
const NO_COOKIES = { cookies: [], origins: [] };

test("visitors can't see each other's documents", async ({ page, playwright }) => {
  const b = await playwright.request.newContext({ baseURL: LIVE_URL, storageState: NO_COOKIES });
  try {
    const session = await b.post("/demo/session");
    expect(session.status(), "new session for visitor B (429 means the per-IP hourly limit)").toBe(200);
    expect((await session.json()).created, "visitor B must not reuse visitor A's session").toBe(true);
    const loaded = await b.post("/demo/samples/clean-invoice");
    expect(loaded.status()).toBe(201);
    const id: string = (await loaded.json()).document.document_id;
    expect((await b.get(`/documents/${id}`)).status(), "owner can read it").toBe(200);

    const a = page.request;
    expect((await a.post("/demo/session")).ok()).toBe(true);
    for (const path of [`/documents/${id}`, `/documents/${id}/extractions`, `/documents/${id}/audit`]) {
      expect((await a.get(path)).status(), path).toBe(404);
    }
    expect((await a.post(`/documents/${id}/ask`, { data: { question: "What is the total?" } })).status()).toBe(404);
    const listed = await a.get("/documents");
    expect(listed.status()).toBe(200);
    expect(await listed.text()).not.toContain(id);
  } finally {
    await b.dispose();
  }
});

test("a tampered session cookie is rejected", async ({ page, playwright }) => {
  expect((await page.request.post("/demo/session")).ok()).toBe(true);
  const cookie = (await page.context().cookies()).find((c) => c.name === "docintel_demo");
  expect(cookie, "visitor session cookie").toBeTruthy();
  const [ws, issued, sig] = (cookie?.value ?? "").split(".");
  expect(sig?.length ?? 0).toBeGreaterThan(0);

  for (const forged of [`${ws}.${issued}.${"0".repeat(sig?.length ?? 1)}`, `ws_${"a".repeat(24)}.${issued}.${sig}`]) {
    const ctx = await playwright.request.newContext({
      baseURL: LIVE_URL,
      storageState: NO_COOKIES,
      extraHTTPHeaders: { cookie: `docintel_demo=${forged}` },
    });
    try {
      expect((await ctx.get("/documents")).status()).toBe(401);
    } finally {
      await ctx.dispose();
    }
  }
});

test("operator endpoints are closed to visitors", async ({ page }) => {
  const a = page.request;
  expect((await a.post("/demo/session")).ok()).toBe(true);
  for (const [method, path] of [
    ["GET", "/metrics"],
    ["GET", "/drift/report"],
    ["GET", "/evaluations"],
    ["POST", "/evaluations/run"],
    ["GET", "/audit/verify"],
  ] as const) {
    expect((await a.fetch(path, { method })).status(), `${method} ${path}`).toBe(403);
  }
});
