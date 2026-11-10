import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests: the real web app against the real backend (synthetic prices,
 * offline answer writer). Uses the installed Chrome, so no browser download.
 * Run from apps/web:  npx playwright test   (CI: E2E_BROWSER_CHANNEL="" uses bundled Chromium)
 */
const API_PORT = 8010;
const WEB_PORT = 5174;
const channel = process.env.E2E_BROWSER_CHANNEL ?? "chrome";
const python = process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    // 360 px wide: the low-end Android size from the plan.
    { name: "phone", use: { ...devices["Pixel 5"], viewport: { width: 360, height: 740 }, channel: channel || undefined } },
  ],
  webServer: [
    {
      command: `${python} e2e/backend.py`,
      url: `http://localhost:${API_PORT}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: { E2E_API_PORT: String(API_PORT), E2E_WEB_ORIGIN: `http://localhost:${WEB_PORT}` },
    },
    {
      command: `node ../../node_modules/vite/bin/vite.js --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { VITE_API_BASE: `http://localhost:${API_PORT}` },
    },
  ],
});
