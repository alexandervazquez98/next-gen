// playwright.config.ts — PR5 smoke lane runner.
//
// PR5 of ci-cd-pipeline (feature-branch-chain). The smoke lane
// (.github/workflows/smoke.yml) is the deployment gate in v1 — see
// openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md (R7) and
// the v1 rollback policy.
//
// CI vs local:
//   - CI:    smoke.yml owns the stack lifecycle (compose up + 120s/90s
//            health waits + Playwright + always tear down with
//            `docker compose down` — never `-v`). webServer is
//            undefined here so we don't double-manage compose.
//   - Local: webServer brings the dev compose stack up; reuseExistingServer
//            makes re-runs fast.
//
// Defaults:
//   - BASE_URL = http://localhost:3000   (dev compose frontend)
//   - BACKEND_BASE_URL = http://localhost:8000 (FastAPI root is the
//     smoke contract — see backend/main.py:346 and the
//     backend-health.spec.ts assertion set).

import { defineConfig, devices } from "@playwright/test";

const isCI = !!process.env.CI;
const FRONTEND_PORT = process.env.FRONTEND_PORT ?? "3000";
const BACKEND_PORT = process.env.BACKEND_PORT ?? "8000";

const defaultBaseURL = `http://localhost:${FRONTEND_PORT}`;
const defaultBackendBaseURL = `http://localhost:${BACKEND_PORT}`;

export default defineConfig({
  // E2E specs live under frontend/test/e2e/ — separate from Vitest's
  // `frontend/test/**/*.test.{ts,tsx}` (jsdom) collection.
  testDir: "./test/e2e",
  fullyParallel: !isCI,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: isCI ? 1 : undefined,
  reporter: isCI ? "github" : "list",
  // Per-test/assertion timeouts here are SHORT — the real 90s/120s
  // health budgets live in smoke.yml's curl loops, not here.
  timeout: isCI ? 60_000 : 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: process.env.BASE_URL ?? defaultBaseURL,
    trace: "on-first-retry",
    ignoreHTTPSErrors: true,
    navigationTimeout: 15_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  // Local-only: CI leaves this undefined so the workflow owns
  // teardown (always `docker compose down`, never `-v`).
  webServer: isCI
    ? undefined
    : {
        command: "docker compose -f ../docker-compose.yml up -d postgres neo4j backend frontend",
        url: defaultBaseURL,
        reuseExistingServer: true,
        timeout: 120 * 1000,
        stdout: "pipe",
        stderr: "pipe",
      },
});

