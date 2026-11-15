import { defineConfig } from "@playwright/test";

// Runs against the production build, served by `vite preview`, using the
// Chrome already installed on the machine: no browser download, and the site is
// checked in a shipping browser rather than a bundled snapshot.
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    channel: "chrome",
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
