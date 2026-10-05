import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import { request } from "@playwright/test";

import { LIVE_URL, VISITOR_STATE } from "../playwright.live.config";

/** Start one visitor session and share it across the suite, to stay inside the per-IP session limit. */
export default async function globalSetup(): Promise<void> {
  const ctx = await request.newContext({ baseURL: LIVE_URL });
  try {
    const res = await ctx.post("/demo/session");
    if (res.status() === 429) {
      const wait = res.headers()["retry-after"] ?? "unknown";
      throw new Error(`${LIVE_URL} refused a new visitor session (429, limit is per IP per hour). Retry after ${wait} s.`);
    }
    if (!res.ok()) throw new Error(`POST /demo/session on ${LIVE_URL} returned ${res.status()}: ${await res.text()}`);
    mkdirSync(dirname(VISITOR_STATE), { recursive: true });
    await ctx.storageState({ path: VISITOR_STATE });
  } finally {
    await ctx.dispose();
  }
}
