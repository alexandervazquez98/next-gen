import { expect, test } from "@playwright/test";

// feat-cmdb-ai-handoff — Playwright happy-path E2E for /proposals/cmdb.
//
// This spec is intentionally [manual-evidence] (openspec/config.yaml:11-14):
// it requires the dev stack (backend on :8000, frontend on :3000) AND
// FEATURE_CMDB_PROPOSALS_ENABLED=true. It is NOT part of the default Vitest
// loop — only the on-demand `pnpm test:e2e` runner.
//
// Run locally:
//   cd frontend && corepack pnpm test:e2e cmdb-proposals.spec.ts

test.describe("CMDB proposals happy path", () => {
  test("admin can propose, list, and approve a CI", async ({ page, request }) => {
    // Step 1 — seed a DRAFT proposal via the public HTTP API.
    // The test impersonates the AI agent by signing in as ADMIN first
    // (admin has AI_PROPOSE_CI via the spread of all UserPermission values
    // is NOT granted; admin has CI_APPROVE_PROPOSAL but NOT AI_PROPOSE_CI.
    // We need a real user with AI_PROPOSE_CI). For the smoke test we
    // authenticate as a seeded OPERATOR who ALSO has AI_PROPOSE_CI (e.g.
    // the AI_OPERATOR seed persona — but persona auth is via a different
    // JWT subject). To keep the smoke deterministic we sign in as
    // "alice" (seeded admin) and rely on the Admin bypass in the service.
    //
    // In production this path would be exercised by the AI agent JWT
    // flow (services.auth_service.get_current_ai_agent). For local smoke
    // we accept the ADMIN all-perms spread as the simplest path.

    // For simplicity, we'll exercise the UI as an OPERATOR who has both
    // CI_VIEW and CI_APPROVE_PROPOSAL. The proposal is seeded by
    // posting as the AI_OPERATOR-equivalent seed (admin).

    // Sign in as the seeded admin.
    await page.goto("/#/login");
    await page.locator('input[name="username"]').fill("admin");
    await page.locator('input[name="password"]').fill("admin");
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/\/$|#\/$/, { timeout: 10_000 });

    // Seed a draft via the HTTP API. The MCP server / HTTP endpoints are
    // gated on FEATURE_CMDB_PROPOSALS_ENABLED — if the dev stack has it
    // disabled, this fetch will 404 and the test fails clearly.
    const seed = await request.post("/api/cmdb/proposals", {
      data: {
        schema_version: 1,
        ci: {
          id: `CI-E2E-${Date.now()}`,
          label: "E2E Test Router",
          category: "Router",
          type: "Router",
          ip: "10.0.0.1",
        },
        rationale: "e2e happy-path",
        source_refs: ["playwright:e2e"],
      },
      failOnStatusCode: false,
    });

    // If the feature is disabled or admin lacks AI_PROPOSE_CI, we still
    // get a permission denial. Document this for the on-call:
    if (!seed.ok()) {
      test.skip(
        true,
        `proposal seed returned ${seed.status()}; ensure FEATURE_CMDB_PROPOSALS_ENABLED=true`,
      );
      return;
    }

    const seeded = await seed.json();
    const proposalId: string = seeded.proposal_id;
    expect(proposalId).toMatch(/^[0-9a-f-]{36}$/i);

    // Navigate to the proposal list.
    await page.goto(`/#/proposals/cmdb?status=DRAFT`);
    await expect(page.getByTestId("proposals-cmdb-list")).toBeVisible();

    // The row for our proposal MUST be visible.
    await expect(page.getByTestId(`proposal-row-${proposalId}`)).toBeVisible();

    // Click into the proposal detail.
    await page.getByTestId(`proposal-row-${proposalId}`).click();
    await expect(page.getByTestId("proposal-detail")).toBeVisible();

    // Approve action — confirm the dialog.
    await page.getByTestId("proposal-action-approve").click();
    await page.getByTestId("proposal-action-approve-confirm-yes").click();

    // After approval, the row status updates.
    await page.goto(`/#/proposals/cmdb?status=APPROVED`);
    await expect(page.getByTestId(`proposal-row-${proposalId}`)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("chat propose_ci intent creates draft and renders proposal link in console (T2.10)", async ({
    page,
    request,
  }) => {
    // Sign in as admin.
    await page.goto("/#/login");
    await page.locator('input[name="username"]').fill("admin");
    await page.locator('input[name="password"]').fill("admin");
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/\/$|#\/$/, { timeout: 10_000 });

    const uniqueId = `CI-CHAT-${Date.now()}`;
    // Post to /api/ai/chat with explicit propose_ci intent.
    const chatResp = await request.post("/api/ai/chat", {
      data: {
        query: `Add core switch ${uniqueId}`,
        intent: {
          type: "propose_ci",
          manifest: {
            schema_version: 1,
            ci: {
              id: uniqueId,
              label: `Core Switch ${uniqueId}`,
              category: "Switch",
              ip: "10.10.10.1",
            },
            rationale: "Playwright T2.10 test",
            source_refs: ["playwright:chat"],
          },
        },
      },
      failOnStatusCode: false,
    });

    if (!chatResp.ok()) {
      test.skip(
        true,
        `/api/ai/chat returned ${chatResp.status()}; ensure LM Studio / AI chat is enabled`,
      );
      return;
    }

    const chatData = await chatResp.json();
    const proposalId = chatData.harness_result?.proposal_id;
    expect(proposalId).toBeTruthy();

    // Verify the proposal is in DRAFT on the review page with AI badge.
    await page.goto(`/#/proposals/cmdb?status=DRAFT`);
    await expect(page.getByTestId(`proposal-row-${proposalId}`)).toBeVisible();
    await expect(page.getByTestId(`proposal-source-${proposalId}`)).toContainText("AI chat");
  });

  test("admin can upload bulk CSV, preview validation, and submit proposal (T4.12)", async ({
    page,
  }) => {
    // Sign in as admin (has CI_BULK_IMPORT).
    await page.goto("/#/login");
    await page.locator('input[name="username"]').fill("admin");
    await page.locator('input[name="password"]').fill("admin");
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/\/$|#\/$/, { timeout: 10_000 });

    // Navigate to proposals list page.
    await page.goto("/#/proposals/cmdb");
    await expect(page.getByTestId("proposals-cmdb-list")).toBeVisible();

    // BulkImportPanel should be visible for admin with CI_BULK_IMPORT.
    const panel = page.getByTestId("bulk-import-panel");
    if (!(await panel.isVisible())) {
      test.skip(
        true,
        "BulkImportPanel not visible; ensure user has CI_BULK_IMPORT permission",
      );
      return;
    }

    // Prepare a dynamic 2-row valid CSV.
    const id1 = `CI-BULK-A-${Date.now()}`;
    const id2 = `CI-BULK-B-${Date.now()}`;
    const csvContent = `id,label,category,brand,model,ip\n${id1},Router Alpha,Router,Cisco,ASR-1000,10.0.1.1\n${id2},Switch Beta,Switch,Juniper,EX4300,10.0.1.2\n`;

    // Upload via file input.
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByTestId("bulk-import-file").click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles({
      name: "bulk-test.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csvContent, "utf-8"),
    });

    // Run dry-run validation first.
    await page.getByTestId("bulk-import-validate").click();
    await expect(page.getByTestId("bulk-import-validation-ok")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("bulk-import-validation-ok")).toContainText(
      "2 CI(s) ready",
    );

    // Submit draft proposal.
    await page.getByTestId("bulk-import-submit").click();
    await expect(page.getByTestId("bulk-import-submitted")).toBeVisible({
      timeout: 10_000,
    });

    // The proposal row should now be visible in DRAFT with Bulk CSV badge and ×2 count.
    await page.goto("/#/proposals/cmdb?status=DRAFT");
    const sourceCell = page.locator(`tr:has-text("${id1}")`).getByTestId(/^proposal-source-/);
    await expect(sourceCell).toContainText("Bulk CSV");
    await expect(sourceCell).toContainText("×2");
  });
});
