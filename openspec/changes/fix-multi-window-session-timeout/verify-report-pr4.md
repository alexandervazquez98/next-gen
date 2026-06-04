# Verify Report PR4 — fix-multi-window-session-timeout

Status: PASS
Date: 2026-06-03
Scope: PR4 frontend singleflight, bounded refresh retry, cross-tab session convergence, and inactivity UX.

## Summary

PR4 implements the frontend side of issue #188 on top of the PR3 `/auth/users/me` contract. The client now deduplicates per-tab refresh attempts, retries each original 401 once, avoids recursive refresh/logout handling, preserves SSE no-redirect behavior, broadcasts logout/session-expired events across tabs without duplicate remote delivery, ignores stale session-scoped events for previous sessions, and arms local inactivity logout only for non-persistent session policies.

## Changed files

- `frontend/services/api.ts`
- `frontend/services/api.test.ts`
- `frontend/services/sessionBus.ts`
- `frontend/services/sessionBus.test.ts`
- `frontend/context/AuthContext.tsx`
- `frontend/context/AuthContext.test.tsx`
- `openspec/changes/fix-multi-window-session-timeout/apply-progress.md`
- `openspec/changes/fix-multi-window-session-timeout/verify-report-pr4.md`

## Strict TDD evidence

RED command: `corepack pnpm --dir frontend run test:run -- api.test.ts AuthContext.test.tsx sessionBus.test.ts`

Result: failed as expected before implementation. Evidence included missing `sessionBus` module failures plus API refresh orchestration assertion failures: parallel 401s made two refresh calls, terminal refresh detail was collapsed to `Session expired`, and `skipAuthRefresh` did not prevent recursive refresh.

GREEN/TRIANGULATE command: `corepack pnpm --dir frontend run test:run`

Result: PASS — `43 passed`, `403 tests passed` after review fixes.

Review-fix validation command: `corepack pnpm --dir frontend run test:run -- AuthContext.test.tsx sessionBus.test.ts`

Result: PASS — `43 passed`, `403 tests passed`; added coverage for cross-channel event dedupe, stale session-id filtering, and fake-timer inactivity expiry.

Note: jsdom printed `Not implemented: navigation to another Document` while tests exercised redirect paths; assertions still passed.

## Risk review

- Cross-tab refresh locking remains intentionally backend-authoritative; frontend coordinates logout/session-expired convergence only.
- Inactivity timer is UX assist, not security authority; backend idle/session expiry remains decisive.
- Browser-level manual two-tab behavior still merits reviewer/manual smoke before merge.
