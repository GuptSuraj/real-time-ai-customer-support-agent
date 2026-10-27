import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:3000", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        "cd ../.. && DATABASE_URL=sqlite:////tmp/northstar-e2e.db APP_ORIGIN=http://127.0.0.1:3000 PYTHONPATH=services/api:services/agent uv run python scripts/e2e_server.py",
      url: "http://127.0.0.1:8001/health",
      reuseExistingServer: false,
    },
    {
      command: "INTERNAL_API_URL=http://127.0.0.1:8001 pnpm dev",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
});
