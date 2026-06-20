// frontend-html.spec.ts — PR5 smoke lane, R7 acceptance.
//
// Spec scenario (openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md):
//   "Smoke validates serving paths" — frontend serves HTML.
//
// REAL assertions per strict-tdd.md:
//   1. <title> from frontend/index.html ("NEX-GEN ITSM ...").
//   2. <div id="root"> mount point exists (see frontend/index.tsx:17).

import { test, expect } from "@playwright/test";

test.describe("PR5 smoke: frontend serves HTML", () => {
  test("frontend root returns HTML with title and React mount point", async ({ page }) => {
    const response = await page.goto("/", { waitUntil: "domcontentloaded" });
    expect(response, "page.goto must return a Response").not.toBeNull();
    expect(response!.status(), "frontend must return 2xx").toBeLessThan(400);

    await expect(page).toHaveTitle(/NEX-GEN ITSM/);

    const root = page.locator("#root");
    await expect(root).toBeAttached();
    await expect(root).toHaveCount(1);
  });
});

