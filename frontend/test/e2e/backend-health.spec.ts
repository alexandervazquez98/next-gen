// backend-health.spec.ts — PR5 smoke lane, R7 acceptance.
//
// Spec scenario (openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md):
//   "Smoke validates serving paths" — backend endpoint must return HTTP 200
//   when the compose stack is healthy.
//
// Endpoint under test:
//   GET http://localhost:${BACKEND_PORT:-8000}/
//   (default BACKEND_PORT=8000, set in playwright.config.ts).
//
// Why GET / and not /api/health:
//   The backend (FastAPI, see backend/main.py) exposes a root handler
//   at line 346:
//       @app.get("/")
//       def read_root():
//           return {"status": "System Operational",
//                   "module": "Backend API v1.4 (Refactored)"}
//   This handler is the SIMPLEST live indicator that the FastAPI app
//   booted, middleware wired up, and the process is reachable on the
//   network — without depending on any specific business router
//   (/api/auth/token requires JWT setup, /api/system/status requires
//   a live neo4j/postgres query). The spec scenario only requires
//   "one backend endpoint returns HTTP 200", and the root endpoint
//   is the canonical answer for that.
//
// REAL assertions (not placeholders) per strict-tdd.md:
//   1. The response status is exactly 200 — anything else (500, 502,
//      503) means the backend crashed or is unhealthy, and the smoke
//      lane must fail loudly (R7 unhealthy-stack scenario).
//   2. The body parses as JSON with `status === "System Operational"`.
//      This catches a 200 served by a stale process, an HTML error
//      page returned by a reverse proxy, or a fastapi 200 returned
//      without the new module name after a regression.
//
// What this test does NOT do (deferred / out of scope for PR5 smoke):
//   - It does not exercise auth, business routers, or DB-backed
//     endpoints. Those are covered by the backend Vitest/pytest suites
//     (PR2 + backend tests). Smoke is the gate, not the test suite.

import { test, expect } from "@playwright/test";

const BACKEND_BASE_URL =
  process.env.BACKEND_BASE_URL ?? "http://localhost:8000";

test.describe("PR5 smoke: backend health responds 200", () => {
  test("backend root returns 200 with operational status payload", async ({ request }) => {
    const response = await request.get(`${BACKEND_BASE_URL}/`);

    // REAL assertion #1: exact 200, not just "2xx". 500/502 must surface.
    expect(
      response.status(),
      `backend root must return HTTP 200, got ${response.status()} from ${BACKEND_BASE_URL}/`,
    ).toBe(200);

    // REAL assertion #2: the body is the JSON contract documented in
    // backend/main.py line 346-349. A 200 with the wrong body is a
    // smell (e.g., reverse-proxy default page, stale image) and must
    // fail the smoke lane.
    const body = await response.json();
    expect(body).toEqual(
      expect.objectContaining({
        status: "System Operational",
      }),
    );
  });
});
