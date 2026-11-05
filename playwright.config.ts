import { defineConfig, devices } from "@playwright/test";
import { randomUUID } from "node:crypto";
process.env.E2E_ADMIN_API_KEY ??= randomUUID() + randomUUID();
export default defineConfig({
  testDir: "./e2e", fullyParallel: false, workers: 1, timeout: 90000,
  expect: { timeout: 15000 }, retries: 0, reporter: process.env.CI ? "github" : "list",
  use: { baseURL: "http://127.0.0.1:3101", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], launchOptions: { args: ["--use-fake-device-for-media-stream"] } } }],
  webServer: { command: "node scripts/dev.mjs --web-port 3101 --api-port 8101", url: "http://127.0.0.1:3101/api/health",
    timeout: 90000, reuseExistingServer: false,
    env: { LLM_PROVIDER: "fake", STT_PROVIDER: "auto", STT_BASE_URL: "", STT_MODEL: "", STT_API_KEY: "", TTS_PROVIDER: "local", TTS_ALLOW_EXTERNAL: "false", DEMO_MODE: "true", DB_DRIVER: "sqlite", ADMIN_API_KEY: process.env.E2E_ADMIN_API_KEY, SQLITE_PATH: ".data/python-e2e/interviews.sqlite3", APP_BASE_URL: "http://127.0.0.1:3101", NEXT_DIST_DIR: ".next-e2e" },
  },
});
