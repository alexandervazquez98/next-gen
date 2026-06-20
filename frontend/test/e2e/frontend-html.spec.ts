// frontend-html.spec.ts — PR5 smoke lane, R7 acceptance.
//
// Spec scenario (openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md):
//   "Smoke validates serving paths" — GIVEN the compose stack is healthy
//   WHEN Playwright smoke tests run THEN the frontend serves HTML and one
//   backend endpoint returns HTTP 200.
//
// This file proves the FIRST half of that scenario: the frontend (Vite
// dev on :3000 or nginx:alpine on :80, both reached via the same
// `baseURL` from playwright.config.ts) actually serves a runnable React
// shell.
//
// REAL assertions (not placeholders) per strict-tdd.md:
//   1. The served HTML has a non-empty <title> derived from
//      frontend/index.html ("NEX-GEN ITSM | AI-Powered ITIL 4"). An
//      empty title would mean a wrong page or a misrouted SPA proxy.
//   2. The served HTML contains a <div id="root"> mount point that
//      React mounts into (see frontend/index.tsx line 17). If the
//      container isn't there the SPA cannot hydrate — proven by the
//      `toBeAttached()` semantic assertion.
//
// What this test does NOT do (deferred / out of scope for PR5 smoke):
//   - It does not exercise login or full navigation (covered by Vitest
//     component tests + future E2E PR). The smoke lane is the deployment
//     gate per spec R7 + rollback policy v1 — it must answer "is the
//     stack up?", not "do the workflows work?".

import { test, expect } from "@playwright/test";

test.describe("PR5 smoke: frontend serves HTML", () => {
  test("frontend root returns HTML with title and React mount point", async ({ page }) => {
    const response = await page.goto("/", { waitUntil: "domcontentloaded" });
    expect(response, "page.goto must return a Response").not.toBeNull();
    expect(response!.status(), "frontend must return 2xx").toBeLessThan(400);

    // REAL assertion #1: the served HTML carries the product title from
    // frontend/index.html. If the page is misrouted, blank, or served
    // by the wrong service, this title check fails.
    await expect(page).toHaveTitle(/NEX-GEN ITSM/);

    // REAL assertion #2: the React mount point exists in the DOM and is
    // attached. Without this div, frontend/index.tsx throws
    // `Could not find root element to mount to` and the SPA never
    // hydrates.
    const root = page.locator("#root");
    await expect(root).toBeAttached();
    await expect(root).toHaveCount(1);
  });
});
