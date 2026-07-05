# Apply Progress: feat-324-tunnel-visualization

## Scope

PR1 only: shared helpers, query/bounds, and aggregate telemetry for the feature-branch-chain child PR.

## Completed Task Checkboxes

- [x] 1.1 RED tests for `frontend/utils/tunnelVisuals.ts`
- [ ] 1.2 GREEN implementation for `frontend/utils/tunnelVisuals.ts` and `frontend/types.ts` — implemented, but not marked complete because the frontend runner is unavailable in this environment.
- [x] 1.3 RED service/hook tests for tunnel health query bounds
- [ ] 1.4 GREEN service/query key/hook implementation — implemented, but not marked complete because the frontend runner is unavailable in this environment.
- [x] 1.5 RED frontend/backend telemetry tests
- [ ] 1.6 GREEN telemetry implementation — implemented and Python syntax-checked, but not marked complete because frontend/backend test runners are unavailable in this environment.
- [ ] Blocker fixes — implemented RED tests and production changes for rotating bounded health polling, QueryClientProvider hook test wrapping, failure classification/cooldown/stale fallback, cooldown wakeup recovery after all visible queries are suppressed, production-like cached-error cooldown retry recovery, frontend telemetry emission, backend aggregate observability, nested telemetry count validation, fail-open telemetry flush behavior, removed the dead request scheduler helper, named telemetry thresholds, diagnostic telemetry escalation after scheduled-only flushes, and cooldown-only telemetry escalation after failure diagnostics; not marked complete because local test runners remain unavailable.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `frontend/utils/tunnelVisuals.test.ts` | Unit | ⚠️ Blocked: `corepack`/`pnpm` unavailable before edits | ✅ Written first | ❌ Not executed: `corepack: command not found` | ✅ Multiple fixtures: ASCII, UTF-8, authority, fallback, tooltip/icon separation | ➖ Awaiting runner |
| 1.2 | `frontend/utils/tunnelVisuals.test.ts` | Unit | ⚠️ Blocked: `corepack`/`pnpm` unavailable | ✅ Covered by 1.1 tests | ❌ Not claimed: runner unavailable | ✅ Implemented against multiple test paths | ➖ Awaiting runner |
| 1.3 | `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` | Unit/Hook | ⚠️ Blocked: `corepack`/`pnpm` unavailable before edits | ✅ Written first | ❌ Not executed: `corepack: command not found` | ✅ Dedupe, cap, cooldown, kill switch, jitter, retry, concurrency, budget | ➖ Awaiting runner |
| 1.4 | `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` | Unit/Hook | ⚠️ Blocked: `corepack`/`pnpm` unavailable | ✅ Covered by 1.3 tests | ❌ Not claimed: runner unavailable | ✅ Implemented service, key, and planning/scheduling hook helpers | ➖ Awaiting runner |
| 1.5 | `frontend/utils/tunnelHealthTelemetry.test.ts`; `backend/tests/test_routers_tunnels.py` | Unit/API | ⚠️ Blocked: `corepack`/`pnpm` unavailable; `python3 -m pytest` unavailable (`No module named pytest`) | ✅ Written first | ❌ Not executed by test runners | ✅ Aggregate-only, rate limit, auth, forbidden sensitive fields | ➖ Awaiting runners |
| 1.6 | `frontend/utils/tunnelHealthTelemetry.test.ts`; `backend/tests/test_routers_tunnels.py` | Unit/API | ⚠️ Blocked by unavailable runners | ✅ Covered by 1.5 tests | ❌ Not claimed: runners unavailable; `python3 -m py_compile backend/routers/tunnels.py` passed | ✅ Frontend batcher and backend redaction/rate logic implemented | ➖ Awaiting runners |
| Blocker fixes | `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx`; `frontend/utils/tunnelHealthTelemetry.test.ts`; `backend/tests/test_routers_tunnels.py` | Unit/Hook/API | ⚠️ Blocked: `corepack` unavailable and `pytest` unavailable before blocker edits | ✅ Added/updated tests first for rotation beyond first 4, QueryClientProvider wrapping, failure classification/fallback/cooldown, cooldown wakeup after all links are suppressed, hook telemetry emission, fail-open telemetry flush, backend aggregate stats, invalid nested counts, scheduled-only telemetry not hiding later failure/cooldown diagnostics, and cooldown-only telemetry posting after a failed health query | ❌ Not claimed: frontend/backend runners unavailable; Python syntax check passed | ✅ Multiple cases across bounded rotation, stale/no-cache fallback, cooldown recovery, telemetry failure/rate/nested validation, and per-diagnostic-kind escalation within the telemetry window | ➖ Awaiting runners |
| PR #360 cooldown cache bug | `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` | Hook | ⚠️ Blocked: `corepack`/`pnpm` unavailable before edits; production-like QueryClient test added first | ✅ Added RED regression using a production-like QueryClient without `gcTime: 0`, proving a cached failed query must not immediately re-enter cooldown after expiry before the fresh retry resolves | ❌ Not claimed: local Corepack/pnpm unavailable | ✅ Hook now records the React Query `errorUpdatedAt` for each cooldown-triggering failure and only re-enters cooldown/telemetry failure accounting for a new failed fetch transition, not an already-accounted cached error | ➖ Awaiting runner |

## Test Commands and Results

- `corepack pnpm --dir frontend test:run services/queryResources.test.ts services/queryKeys.test.ts types.test.ts` → blocked: `zsh:1: command not found: corepack`
- `pnpm --dir frontend test:run services/queryResources.test.ts services/queryKeys.test.ts types.test.ts` → blocked: `zsh:1: command not found: pnpm`
- `corepack pnpm --dir frontend test:run utils/tunnelVisuals.test.ts hooks/queries/useVisibleTunnelHealth.test.tsx utils/tunnelHealthTelemetry.test.ts` → blocked: `zsh:1: command not found: corepack`
- `python3 -m pytest backend/tests/test_routers_tunnels.py` → blocked: `/Library/Developer/CommandLineTools/usr/bin/python3: No module named pytest`
- `python3 -m py_compile backend/routers/tunnels.py` → passed syntax check.
- `corepack pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx utils/tunnelHealthTelemetry.test.ts backend/tests/test_routers_tunnels.py` → blocked: `zsh:1: command not found: corepack`
- `python3 -m pytest backend/tests/test_routers_tunnels.py` → blocked: `/Library/Developer/CommandLineTools/usr/bin/python3: No module named pytest`
- `python3 -m py_compile backend/routers/tunnels.py` → passed syntax check after blocker fixes.
- `corepack pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx` → blocked: `zsh:1: command not found: corepack`
- `pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx` → blocked: `zsh:1: command not found: pnpm`
- `python3 -m pytest backend/tests/test_routers_tunnels.py` → blocked: `/Library/Developer/CommandLineTools/usr/bin/python3: No module named pytest`
- `python3 -m py_compile backend/routers/tunnels.py backend/tests/test_routers_tunnels.py` → passed syntax check after follow-up fixes.
- `corepack pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx utils/tunnelHealthTelemetry.test.ts` → blocked: `zsh:1: command not found: corepack`
- `pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx utils/tunnelHealthTelemetry.test.ts` → blocked: `zsh:1: command not found: pnpm`
- `corepack pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx utils/tunnelHealthTelemetry.test.ts` after cooldown-only blocker fix → blocked: `zsh:1: command not found: corepack`; GREEN is not claimed.
- CI `lint-backend` reported Black formatting failures in `backend/routers/tunnels.py` and `backend/tests/test_routers_tunnels.py` → fixed by wrapping the long `HTTPException` and `client.post(...)` calls.
- CI `lint-frontend` reported ESLint failures for undefined `DOMException`, unstable `failureByKind`, missing `failedQueries` effect dependency, mutable `now`, and undefined `TextEncoder`/`btoa` → fixed with lint-only-safe code changes; frontend GREEN is not claimed because local Node/Corepack/pnpm remain unavailable.
- `python3 -m py_compile backend/routers/tunnels.py backend/tests/test_routers_tunnels.py` after CI lint fixes → passed syntax check.
- PR #360 readability cleanup: named the local UTF-8/base64url bit masks, byte prefixes, chunk shifts, and padding behavior; documented why failed-query cooldowns depend on a stable signature while reading the latest ref; added a deterministic supplementary-plane emoji tunnel ID fixture.
- `corepack pnpm --dir frontend test:run utils/tunnelVisuals.test.ts hooks/queries/useVisibleTunnelHealth.test.tsx` after readability cleanup → blocked: `zsh:1: command not found: corepack`; GREEN is not claimed locally.
- PR #360 frontend CI fix pass: latest CI reported `lint-frontend` Prettier failures in PR1 frontend files and `frontend-tests` failures around the `ApiError` mock dependency, hook telemetry POSTs not being observed, cooldown payload rendering, and cooldown wake-up timing. Fixed by formatting the listed PR1 frontend files, classifying errors structurally from `error.status`/`error.name` instead of importing `ApiError`, giving each `useVisibleTunnelHealth` hook instance its own telemetry batcher so tests/surfaces are not suppressed by a module-level rate window, and flushing fake-timer cooldown wake-up microtasks in the regression test.
- `git diff --check` after PR #360 frontend CI fixes → passed.
- `corepack pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx utils/tunnelHealthTelemetry.test.ts` after PR #360 frontend CI fixes → blocked: `zsh:1: command not found: corepack`; GREEN is not claimed locally.
- `pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx utils/tunnelHealthTelemetry.test.ts` after PR #360 frontend CI fixes → blocked: `zsh:1: command not found: pnpm`; GREEN is not claimed locally.
- `corepack pnpm --dir frontend format:check hooks/queries/useVisibleTunnelHealth.test.tsx hooks/queries/useVisibleTunnelHealth.ts utils/tunnelHealthTelemetry.test.ts utils/tunnelHealthTelemetry.ts utils/tunnelVisuals.test.ts utils/tunnelVisuals.ts services/queryKeys.ts services/queryResources.ts types.ts` after PR #360 frontend CI fixes → blocked: `zsh:1: command not found: corepack`; formatter GREEN is not claimed locally.
- PR #360 cooldown cache bug fix: `git diff --check` → passed.
- `command -v corepack` and `command -v pnpm` before focused frontend rerun → both unavailable in this worktree environment; focused Vitest was not run and GREEN is not claimed.

## Files Touched

- `frontend/utils/tunnelVisuals.test.ts` — RED fixtures for canonical encoding, visual authority semantics, fallback, tooltip, and icon-health separation.
- `frontend/utils/tunnelVisuals.test.ts` — added supplementary-plane/emoji encoding fixture for deterministic local UTF-8 coverage.
- `frontend/utils/tunnelVisuals.ts` — shared tunnel encoder and visual model helper.
- `frontend/utils/tunnelVisuals.ts` — replaced browser-global `TextEncoder`/`btoa` use with deterministic local UTF-8/base64url encoding for ESLint-safe tunnel IDs.
- `frontend/utils/tunnelVisuals.ts` — added named constants and an unpadded-base64url comment to make the manual encoder reviewable without changing behavior.
- `frontend/types.ts` — tunnel health/model/telemetry types and `GraphNode.public_ip`.
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — RED service/hook/planning tests for bounds and kill switch.
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — added blocker regression tests for QueryClientProvider wrapping, rotating IDs beyond the first 4, failure classification, stale/no-cache fallback, cooldown, and hook telemetry emission.
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — added RED cooldown recovery regression proving polling wakes after every visible link is suppressed and the cooldown expires; removed scheduler-only test coverage for the deleted helper.
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — added RED telemetry regression proving failed health-query telemetry posts after an earlier scheduled-only telemetry flush.
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — added RED telemetry regression asserting an external telemetry POST with `suppressed_cooldown: 1` after a failed health query enters cooldown.
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — replaced `DOMException` construction with a plain abort-shaped object so ESLint does not require a browser global.
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — updated cooldown wake-up regression to flush timer-driven microtasks after advancing fake timers.
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — added RED production-like cached error regression using a QueryClient without `gcTime: 0` so cooldown expiry must allow a fresh retry instead of re-suppressing stale cached failure state.
- `frontend/hooks/queries/useVisibleTunnelHealth.ts` — visible tunnel filtering, dedupe, cap/cooldown/jitter/retry plan, rotating max-4 active query window across up to 50 IDs, failure classification/fallback, cooldown updates with timeout wakeup recovery, telemetry emission, and hook shell; removed dead/test-only request scheduler helper.
- `frontend/hooks/queries/useVisibleTunnelHealth.ts` — made abort classification avoid `DOMException`, memoized health/error derived state, and moved failed-query effect input through a ref keyed by `failedSignature` to satisfy hook dependency lint without creating cooldown render loops.
- `frontend/hooks/queries/useVisibleTunnelHealth.ts` — clarified the failed-query signature/ref pattern so future reviewers know it prevents dependency churn from repeatedly extending cooldowns.
- `frontend/hooks/queries/useVisibleTunnelHealth.ts` — removed the `ApiError` import/class dependency from error classification and scoped telemetry batching to each hook instance to avoid cross-test/page suppression from a module-level singleton.
- `frontend/hooks/queries/useVisibleTunnelHealth.ts` — tracks accounted query failure timestamps via React Query `errorUpdatedAt` so stale cached errors already used to enter cooldown do not immediately re-enter cooldown after recovery wake-up; fresh failed fetch transitions still enter cooldown and aggregate telemetry remains fail-open.
- `frontend/services/queryResources.ts` — `fetchTunnelHealth`.
- `frontend/services/queryKeys.ts` — per-link tunnel health query key.
- `frontend/utils/tunnelHealthTelemetry.test.ts` — RED frontend aggregate telemetry tests.
- `frontend/utils/tunnelHealthTelemetry.test.ts` — RED frontend aggregate telemetry tests plus fail-open failed-flush behavior.
- `frontend/utils/tunnelHealthTelemetry.test.ts` — added RED batcher regression proving scheduled-only flushes do not hide later failure/cooldown diagnostics inside the one-minute window.
- `frontend/utils/tunnelHealthTelemetry.test.ts` — added RED batcher regression proving a prior failure diagnostic does not hide later cooldown-only telemetry inside the one-minute window.
- `frontend/utils/tunnelHealthTelemetry.test.ts` — changed non-mutated failed-flush clock fixture from `let` to `const` for ESLint.
- `frontend/utils/tunnelHealthTelemetry.test.ts` — manually formatted to match Prettier-style spacing while local Corepack/pnpm remain unavailable.
- `frontend/utils/tunnelHealthTelemetry.ts` — aggregate payload, named telemetry thresholds, once/minute batcher, backend post helper with failed-flush isolation, and per-diagnostic-kind escalation so cooldown telemetry can post after prior failure diagnostics.
- `frontend/utils/tunnelHealthTelemetry.ts` — manually formatted to match Prettier-style spacing while preserving aggregate-only fail-open telemetry behavior.
- `backend/tests/test_routers_tunnels.py` — RED backend telemetry API tests.
- `backend/tests/test_routers_tunnels.py` — added backend aggregate observability and invalid nested count validation tests.
- `backend/tests/test_routers_tunnels.py` — wrapped invalid nested-count telemetry POST call per Black formatting.
- `backend/routers/tunnels.py` — authenticated redacted aggregate telemetry ingest with in-memory per-user rate limit, aggregate stats/log signal, and nested count validation using named telemetry bounds constants.
- `backend/routers/tunnels.py` — wrapped aggregate-only redaction `HTTPException` per Black formatting.

## Deviations

- No PR2/PR3 surface integrations were modified.
- GREEN tasks are intentionally not checked off because automated GREEN execution is blocked by missing local runners.

## Remaining Tasks

- [ ] Re-run focused frontend Vitest once Corepack/pnpm is available and check off GREEN tasks if passing.
- [ ] Re-run backend pytest once pytest dependencies are available and check off task 1.6 if passing.
- [ ] Continue PR2/PR3 only after PR1 verification.
