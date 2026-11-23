import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  timeout: 35000,
  workers: 1,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.LOCALPAY_E2E_DASHBOARD_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
});
