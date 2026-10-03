import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// API routes served by FastAPI; the dev server proxies them so the site and API share an origin
// (the session cookie is SameSite=Strict and the CSP only allows same-origin requests).
const API_PREFIXES = ["/demo", "/documents", "/ask", "/reviews", "/health", "/ui"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // keep every script external so the strict CSP (script-src 'self') holds
    modulePreload: { polyfill: false },
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [p, { target: "http://127.0.0.1:8000", changeOrigin: false }]),
    ),
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
