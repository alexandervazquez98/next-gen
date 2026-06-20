// playwright.config.ts — PR5 smoke lane runner.
//
// PR5 of ci-cd-pipeline (feature-branch-chain: PR1 → PR2 → PR3 → PR4 → PR5
// → PR6). The smoke lane (`/.github/workflows/smoke.yml`) is the deployment
// gate in v1 — see openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md
// "Smoke Lane and Playwright Gate" (R7) and the v1 rollback policy.
//
// How this runner fits together with the workflow:
//   - CI:    `smoke.yml` spins up the full compose stack via
//            `docker compose up -d ...` and waits for backend 120s and
//            frontend 90s. Once the stack is healthy, the workflow runs
//            `pnpm --dir frontend run test:e2e`, which lands here. We set
//            `webServer: undefined` in CI because the workflow owns the
//            stack lifecycle (`if: always() → docker compose down`).
//   - Local: `webServer.command` brings up the dev compose stack on
//            `pnpm --dir frontend run test:e2e`, with `reuseExistingServer`
//            so re-runs are fast. Override via `BASE_URL` /
//            `BACKEND_BASE_URL` if you point at a running stack.
//
// Why these defaults:
//   - BASE_URL  defaults to the **dev compose** frontend port (3000). The
//               production overlay (`docker-compose.prod.yml`) maps 3010,
//               but PR5 smoke targets the dev stack because that is what
//               PR6's CD lane will boot on the endpoint host before
//               swapping to the prod profile.
//   - BACKEND_BASE_URL defaults to 8000 (FastAPI default from
//               `docker-compose.yml`). The backend exposes `GET /` which
//               returns `{ "status": "System Operational", ... }` — that
//               is the smoke contract we assert in
//               `backend-health.spec.ts`.
//   - `workers: 1` in CI because GitHub-hosted runners get flaky parallel
//     Chrome instances; locally we let Playwright pick.
//
// Atomic commits this file lives in:
//   - test(frontend): add Playwright smoke tests for frontend and backend
//     health  (T5.2 + T5.3).

import { defineConfig, devices } from "@playwright/test";

const isCI = !!process.env.CI;
const FRONTEND_PORT = process.env.FRONTEND_PORT ?? "3000";
const BACKEND_PORT = process.env.BACKEND_PORT ?? "8000";

const defaultBaseURL = `http://localhost:${FRONTEND_PORT}`;
const defaultBackendBaseURL = `http://localhost:${BACKEND_PORT}`;

export default defineConfig({
  // E2E specs live under frontend/test/e2e/ (separate from Vitest's
  // `frontend/test/**/*.test.{ts,tsx}` collection, which uses jsdom).
  testDir: "./test/e2e",
  // Fully parallel locally; CI runs serially for flake resistance.
  fullyParallel: !isCI,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: isCI ? 1 : undefined,
  reporter: isCI ? "github" : "list",
  // Per-test timeout (30s) plus per-assertion timeout (5s) — both short
  // enough to fail fast on a hung stack, generous enough for first-paint
  // dev-compile latency. The real 90s/120s health budgets live in the
  // smoke workflow's `docker compose up` + curl wait loops, not here.
  timeout: isCI ? 60_000 : 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: process.env.BASE_URL ?? defaultBaseURL,
    trace: "on-first-retry",
    // Mirror common CI-side browser defaults so local runs feel close to
    // what CI sees.
    ignoreHTTPSErrors: true,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Only used for local dev (`pnpm --dir frontend run test:e2e` against
  // a machine that does NOT already have compose running). CI must
  // leave this undefined — the workflow spins the stack up itself so
  // it can tear it down with `docker compose down` (NEVER `-v`, see
  // design.md R7 + scripts/safe-rebuild.sh convention).
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
