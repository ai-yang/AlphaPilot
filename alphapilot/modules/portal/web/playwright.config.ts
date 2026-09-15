import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";

const port = Number(process.env.ALPHAPILOT_PLAYWRIGHT_PORT || 19911);
const baseURL = `http://127.0.0.1:${port}`;
const runId = process.env.ALPHAPILOT_PORTAL_INTERACTION_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");
const artifacts = path.resolve(process.cwd(), `../../../../git_ignore_folder/qa/portal_interaction/${runId}/playwright-artifacts`);
const smokePython = process.env.CONDA_PREFIX ? path.join(process.env.CONDA_PREFIX, "envs", "alphapilot-smoke", "bin", "python") : "";
const python = process.env.ALPHAPILOT_TEST_PYTHON || (smokePython && fs.existsSync(smokePython) ? smokePython : "python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { outputFolder: path.join(artifacts, "report"), open: "never" }]],
  outputDir: path.join(artifacts, "results"),
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: process.env.ALPHAPILOT_PLAYWRIGHT_VIDEO === "off" ? "off" : "retain-on-failure",
  },
  webServer: {
    command: `"${python}" ../../../../tests/portal_interaction_server.py`,
    url: `${baseURL}/__test__/credentials`,
    timeout: 120_000,
    reuseExistingServer: false,
    env: {
      ...process.env,
      ALPHAPILOT_PLAYWRIGHT_PORT: String(port),
      ALPHAPILOT_PORTAL_INTERACTION_RUN_ID: runId,
    },
  },
  projects: [
    { name: "chromium", grepInvert: /@mobile|@cross-browser/, use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1600, height: 1200 } } },
    { name: "mobile-chromium", grep: /@mobile/, use: { ...devices["Pixel 7"], channel: "chrome" } },
    { name: "firefox", grep: /@cross-browser/, use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", grep: /@cross-browser/, use: { ...devices["Desktop Safari"] } },
  ],
});
