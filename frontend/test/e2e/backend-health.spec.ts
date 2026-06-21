// backend-health.spec.ts — PR5 smoke lane, R7 acceptance.
//
// Spec scenario: backend endpoint returns HTTP 200. We hit `GET /`
// (backend/main.py:346) because it is the simplest live indicator that
// FastAPI booted, middleware wired up, and the process is reachable
// — without depending on any specific business router.
//
// REAL assertions per strict-tdd.md:
//   1. Exact 200 (not just 2xx — 500/502 must surface).
//   2. JSON body `status === "System Operational"` (catches stale
//      process, reverse-proxy default page, regression).

import { test, expect } from "@playwright/test";

const BACKEND_BASE_URL =
  process.env.BACKEND_BASE_URL ?? "http://localhost:8000";

test.describe("PR5 smoke: backend health responds 200", () => {
  test("backend root returns 200 with operational status payload", async ({ request }) => {
    const response = await request.get(`${BACKEND_BASE_URL}/`);

    expect(
      response.status(),
      `backend root must return HTTP 200, got ${response.status()} from ${BACKEND_BASE_URL}/`,
    ).toBe(200);

    const body = await response.json();
    expect(body).toEqual(
      expect.objectContaining({
        status: "System Operational",
      }),
    );
  });
});

