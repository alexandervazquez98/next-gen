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
| PR #360 frontend CI stabilization | `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` | Hook | ⚠️ CI reported two fake-timer test timeouts and one ESLint unused callback parameter; local `corepack`/`pnpm` unavailable | ✅ Existing cooldown wake-up and production-cached-error tests already define the failing contract; this pass stabilizes their fake-timer execution without widening timeouts | ❌ Not claimed: local Corepack/pnpm unavailable | ✅ Replaced fake-timer `waitFor` polling with deterministic `act` + `vi.advanceTimersByTimeAsync` + microtask flushing, kept production-like cached error coverage, and renamed the unused resolver callback arg | ➖ Awaiting CI/frontend runner |

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
- PR #360 final frontend CI stabilization: CI reported `lint-frontend` unused test callback parameter at `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx:300:26` and `frontend-tests` timeouts in the cooldown wake-up / production-cached-error tests. Fixed by replacing fake-timer `waitFor` polling in those two tests with deterministic `act` + `vi.advanceTimersByTimeAsync` + microtask flushing, while keeping the production-like cached error coverage and not increasing test timeouts.
- `git diff --check` after final frontend CI stabilization → passed.
- `corepack pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx` after final frontend CI stabilization → blocked: `corepack not found`; GREEN is not claimed.
- `pnpm --dir frontend test:run hooks/queries/useVisibleTunnelHealth.test.tsx` after final frontend CI stabilization → blocked: `pnpm not found`; GREEN is not claimed.

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
- `frontend/hooks/queries/useVisibleTunnelHealth.test.tsx` — stabilized cooldown fake-timer tests with deterministic timer/microtask flushing and renamed the unused retry resolver parameter for ESLint.
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

---

## PR2 Progress Update — 2026-07-05

## Scope

PR2 only: scoped `public_ip` projection after server-side scoped repository reads, plus VisualRelationshipEditor tunnel medium create/edit/display support through the shared tunnel visual model. PR3 topology surface integrations remain out of scope.

## Completed Task Checkboxes

- [x] 2.1 RED backend route tests for `/nodes` and `/graph/full` scoped `public_ip` projection, including CIDetailModal topology consumer contract coverage through `/graph/full`.
- [ ] 2.2 GREEN backend projection implementation — implemented, but not marked complete because local Python execution is blocked by `xcode-select` before pytest or py_compile can run.
- [x] 2.3 RED VisualRelationshipEditor tests for creating, editing, and displaying tunnel media and non-authoritative health context.
- [ ] 2.4 GREEN VisualRelationshipEditor implementation — implemented, but not marked complete because local Corepack/pnpm execution is blocked in this environment.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 | `backend/tests/test_routers_nodes.py`; `backend/tests/test_routers_links.py` | API | ⚠️ Blocked before edits: `python3 -m pytest backend/tests/test_routers_nodes.py backend/tests/test_routers_links.py` failed at `xcode-select`; no test runner reached | ✅ Written first for admin, limited non-admin, and empty non-admin scope on `/nodes` and `/graph/full`; CIDetailModal topology consumer represented by `/graph/full` contract tests | ❌ Not executed: Python command resolution is blocked by missing Xcode command line tools | ✅ Non-empty scoped public IP, empty scoped result, and out-of-scope non-leak assertions | ➖ Awaiting runner |
| 2.2 | `backend/tests/test_routers_nodes.py`; `backend/tests/test_routers_links.py` | API/service | ⚠️ Blocked: Python runner unavailable due `xcode-select` | ✅ Covered by 2.1 tests before implementation | ❌ Not claimed: pytest and py_compile both blocked by `xcode-select` | ✅ `/nodes` and `/graph/full` projections preserve `metadata.public_ip` and expose nullable top-level `public_ip` only on already-returned scoped rows | ➖ Awaiting runner |
| 2.3 | `frontend/components/VisualRelationshipEditor.test.tsx` | Component | ⚠️ Blocked before edits: `corepack pnpm --dir frontend test:run components/VisualRelationshipEditor.test.tsx` failed with `operation not permitted: corepack` | ✅ Written first for create medium, edit medium, display medium, and non-authoritative `UP` + ICMP failed health context | ❌ Not executed: Corepack/pnpm unavailable | ✅ Covers `sd_wan` creation, `satellite` edit, `vpn` display, and no `DEGRADED` authority drift | ➖ Awaiting runner |
| 2.4 | `frontend/components/VisualRelationshipEditor.test.tsx` | Component | ⚠️ Blocked: frontend runner unavailable | ✅ Covered by 2.3 tests before implementation | ❌ Not claimed: Corepack/pnpm unavailable | ✅ Create payload includes selected medium; existing links display shared visual medium/authority/ICMP rows; editable tunnel links can save a new medium through the link contract | ➖ Awaiting runner |

## Test Commands and Results

- `python3 -m pytest backend/tests/test_routers_nodes.py backend/tests/test_routers_links.py` before PR2 edits → blocked: `xcode-select: error: No developer tools were found...`.
- `corepack pnpm --dir frontend test:run components/VisualRelationshipEditor.test.tsx` before PR2 edits → blocked: `zsh:1: operation not permitted: corepack`.
- `python3 -m pytest backend/tests/test_routers_nodes.py backend/tests/test_routers_links.py` after PR2 edits → blocked: `xcode-select: error: No developer tools were found...`.
- `corepack pnpm --dir frontend test:run components/VisualRelationshipEditor.test.tsx` after PR2 edits → blocked: `zsh:1: operation not permitted: corepack`.
- `python3 -m py_compile backend/services/node_service.py backend/services/link_service.py backend/tests/test_routers_nodes.py backend/tests/test_routers_links.py` after PR2 edits → blocked: `xcode-select: error: No developer tools were found...`.
- `git diff --check` after PR2 edits → blocked: `xcode-select: error: No developer tools were found...`.

## Files Touched

- `backend/tests/test_routers_nodes.py` — RED scoped `/nodes` public_ip projection tests for admin, limited non-admin, and empty non-admin scope.
- `backend/tests/test_routers_links.py` — RED scoped `/graph/full` public_ip projection tests, including CIDetailModal topology consumer contract coverage through the same topology payload.
- `backend/services/node_service.py` — projects top-level nullable `public_ip` after `topology_repo.get_nodes(...)` has already applied scope, while preserving `metadata.public_ip`.
- `backend/services/link_service.py` — projects top-level nullable `public_ip` after `topology_repo.get_filtered_graph_data(...)` has already applied scope, while preserving `metadata.public_ip`.
- `frontend/components/RelationshipManager.tsx` — extends `LinkData` with optional tunnel `medium` and `tunnel_health` so editor consumers can share the tunnel visual contract.
- `frontend/components/VisualRelationshipEditor.test.tsx` — RED tests for create/edit/display tunnel medium and non-authoritative health context.
- `frontend/components/VisualRelationshipEditor.tsx` — adds tunnel medium selection for creation, existing-link medium display/editing, and shared `resolveTunnelVisual` usage for medium/authority/ICMP display.
- `openspec/changes/feat-324-tunnel-visualization/tasks.md` — marks completed RED tasks 2.1 and 2.3 only.
- `openspec/changes/feat-324-tunnel-visualization/apply-progress.md` — appends this PR2 TDD evidence.

## Deviations

- GREEN tasks 2.2 and 2.4 are implemented but intentionally not checked off because local automated GREEN execution is blocked by environment/tooling, not by failing assertions.
- No PR3 surface integrations were modified.
- No backend tunnel-health normalization, ICMP authority, pollers, vendor telemetry, bulk health endpoints, or icon assets were changed.

## Remaining Tasks

- [ ] Run focused backend pytest once Python execution is not blocked by `xcode-select`; if passing, mark 2.2 complete.
- [ ] Run focused frontend Vitest once Corepack/pnpm is available; if passing, mark 2.4 complete.
- [ ] Run formatter/lint or `git diff --check` once Git/developer tools are available.

---

## PR2 Backend Scope-Safety Fix — 2026-07-05

## Scope

PR2 backend-only fix for the `/graph/full` empty non-admin scope leak found during fresh review. Frontend and PR3 surfaces remain out of scope.

## Completed Task Checkboxes

- [x] 2.1 RED strengthened: `/graph/full` limited-scope and empty-scope tests now include out-of-scope `public_ip` fixture data and assert no top-level public IP leak.
- [ ] 2.2 GREEN backend projection/scope implementation — empty non-admin scope guard implemented in `backend/services/link_service.py`, but not marked complete because local Python execution is still blocked by missing Xcode command line tools.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1/2.2 scope fix | `backend/tests/test_routers_links.py` | API/service | ⚠️ Blocked before edits: `python3 -m pytest backend/tests/test_routers_links.py -k "full_graph_operator_empty_scope or full_graph_operator_limited_scope"` failed at `xcode-select` before pytest could start | ✅ Test strengthened first: empty non-admin scope now seeds out-of-scope `public_ip` data and asserts the repository is not called; limited scope seeds in-scope and out-of-scope public IP fixtures and asserts only scoped public IP is projected | ❌ Not claimed: focused pytest and py_compile both blocked by `xcode-select` | ✅ Covers empty scope, limited scope, repository non-invocation for empty scope, and no out-of-scope top-level `public_ip` in response text | ➖ Awaiting runner |

## Test Commands and Results

- `python3 -m pytest backend/tests/test_routers_links.py -k "full_graph_operator_empty_scope or full_graph_operator_limited_scope"` before implementation → blocked: `xcode-select: error: No developer tools were found...`.
- `python3 -m pytest backend/tests/test_routers_links.py -k "full_graph_operator_empty_scope or full_graph_operator_limited_scope"` after implementation → blocked: `xcode-select: error: No developer tools were found...`.
- `python3 -m py_compile backend/services/link_service.py backend/tests/test_routers_links.py` after implementation → blocked: `xcode-select: error: No developer tools were found...`.

## Files Touched

- `backend/tests/test_routers_links.py` — strengthened `/graph/full` empty-scope and limited-scope public IP leak coverage with out-of-scope fixtures.
- `backend/services/link_service.py` — added an explicit empty non-admin `allowed_locations == []` guard before repository access.
- `openspec/changes/feat-324-tunnel-visualization/apply-progress.md` — recorded TDD evidence and runner blockers for this backend scope-safety fix.

## Deviations

- Task 2.2 remains unchecked because no local GREEN execution was possible.
- No frontend, PR3 surface, repository, or router implementation files were changed.

## Remaining Tasks

- [ ] Run focused backend pytest once Python execution is not blocked by `xcode-select`; if passing, task 2.2 can be considered for completion.
- [ ] Run formatter/lint or `git diff --check` once Git/developer tools are available.

---

## PR2 Backend GREEN Validation — 2026-07-05

## Completed Task Checkboxes

- [x] 2.2 GREEN completed: backend scoped `public_ip` projection now has focused pytest coverage passing for `/nodes` and `/graph/full`.

## TDD Cycle Evidence Update

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.2 | `backend/tests/test_routers_nodes.py`; `backend/tests/test_routers_links.py` | API/service | ✅ Temporary Python 3.11 venv created at `/private/tmp/next-gen-pr2-py311` because system `python3` is blocked by missing Xcode command line tools | ✅ Covered by prior 2.1 RED tests plus strengthened `/graph/full` empty/limited scope leak tests | ✅ `/private/tmp/next-gen-pr2-py311/bin/python -m pytest backend/tests/test_routers_nodes.py backend/tests/test_routers_links.py` passed: 64 passed, 18 warnings | ✅ Admin, limited non-admin, and empty non-admin scope behavior covered for `/nodes` and `/graph/full`; empty non-admin `/graph/full` avoids repository access | ✅ Critical empty-scope leak fix re-reviewed with no blockers; only CI/full-suite confirmation remains |

## Test Commands and Results

- `/Users/macbook/.local/bin/python3.11 -m venv /private/tmp/next-gen-pr2-py311 && /private/tmp/next-gen-pr2-py311/bin/python -m pip install -q --upgrade pip && /private/tmp/next-gen-pr2-py311/bin/python -m pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt` → passed.
- `/private/tmp/next-gen-pr2-py311/bin/python -m pytest backend/tests/test_routers_nodes.py backend/tests/test_routers_links.py` → passed: 64 passed, 18 warnings.
- `OPENSSL_CONF=/dev/null /Applications/Codex.app/Contents/Resources/cua_node/bin/node node_modules/vitest/vitest.mjs run components/VisualRelationshipEditor.test.tsx` → blocked by macOS native Rollup/Node Team ID signing mismatch, so 2.4 remains unchecked pending CI-capable frontend test execution.

## Remaining Tasks

- [ ] Run focused frontend Vitest in CI-capable environment; if passing, mark 2.4 complete.
- [ ] Run final changed-file lint/format and prepare PR2 commit/PR after frontend GREEN evidence.

---

## PR2 CI GREEN Validation — 2026-07-05

## Completed Task Checkboxes

- [x] 2.4 GREEN completed: CI validated frontend tests for the VisualRelationshipEditor medium create/edit/display work.

## CI Evidence

PR #367 head `d559b587a7d474836fa4f1b9dc8d15926cd01da7` completed successfully:

- `frontend-tests` → success
- `backend-tests` → success
- `smoke` → success
- `lint-backend` → success
- `lint-frontend` → success
- `lint-verify (PR1 gate)` → success
- `ci-verify (PR2 gate)` → success
- `ci-verify (PR3 gate)` → success
- `shellcheck` → success
- `yamllint` → success
- `actionlint` → success

## TDD Cycle Evidence Update

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.4 | `frontend/components/VisualRelationshipEditor.test.tsx` | Component | ✅ CI `frontend-tests` validated the focused frontend work after local Vitest was blocked by macOS Rollup/Node signing | ✅ Covered by 2.3 RED tests for create, edit, display, and non-authoritative health context | ✅ PR #367 CI `frontend-tests` passed on head `d559b587a7d474836fa4f1b9dc8d15926cd01da7` | ✅ Medium create/edit/display behavior plus shared visual model context covered in PR2 scope | ✅ Changed-file `lint-frontend` and Prettier checks passed in CI |

## Remaining Tasks

- [ ] Merge PR2 after review, then continue PR3 topology surface integrations.

---

## PR3 Topology Surface Integration — 2026-07-05

## Scope

PR3 only: frontend topology surfaces consume the existing shared tunnel visual contract and scoped data already established by PR1/PR2. No backend public-IP projection, tunnel-health normalization, ICMP authority, pollers, telemetry, bulk health endpoints, or icon assets were changed.

## Completed Task Checkboxes

- [x] 3.1 RED completed: component tests were added for `NetworkVisualizer.tsx` and `MonitoringConsole.tsx` covering neutral `UNKNOWN`, `UP` warning context, health error tooltip rows, visible filtering, and kill-switch no-live-health context.
- [ ] 3.2 GREEN implemented but not checked off: `NetworkVisualizer.tsx` and `MonitoringConsole.tsx` now consume `useVisibleTunnelHealth` and shared `tunnelVisuals`, but local Vitest execution is blocked by the Rollup native module code-signing mismatch.
- [x] 3.3 RED completed: component tests were added for `TopologyViewer.tsx`, `RelationshipManager.tsx`, and `CIDetailModal.tsx` requiring shared medium/icon/status/tooltip rows and scoped public-IP fallback.
- [ ] 3.4 GREEN implemented but not checked off: `TopologyViewer.tsx`, `RelationshipManager.tsx`, and `CIDetailModal.tsx` now render shared tunnel visual summaries and scoped public-IP fallback, but local Vitest execution is blocked.
- [ ] 3.5 VERIFY not complete: backend scoped public-IP suites pass locally; frontend Vitest remains blocked locally and requires CI-capable execution.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.1 | `frontend/components/NetworkVisualizer.test.tsx`; `frontend/components/MonitoringConsole.test.tsx` | Component | ⚠️ Blocked before edits: focused Vitest cannot start because Rollup native module `@rollup/rollup-darwin-x64` fails macOS Team ID code-signing validation | ✅ Written first for neutral `UNKNOWN` + missing public IP, `UP` + ICMP warning, unavailable-health tooltip rows, visible-link filtering, and kill-switch disabled polling context | ❌ Not claimed: focused Vitest remains blocked by Rollup native module signing mismatch | ✅ Covers different surfaces, authority states, warning/error rows, visible filtering, and disabled polling | ✅ Shared rendering extracted through `TunnelVisualSummary`; TypeScript spot-check found no errors in changed files |
| 3.2 | `frontend/components/NetworkVisualizer.test.tsx`; `frontend/components/MonitoringConsole.test.tsx` | Component | ⚠️ Runner blocked locally | ✅ Covered by 3.1 RED tests before implementation | ❌ Not claimed: implementation is present but focused Vitest cannot execute locally | ✅ `NetworkVisualizer` passes filtered graph links to `useVisibleTunnelHealth`; `MonitoringConsole` passes category-visible map links only; both preserve authority text and show warning/error rows | ✅ Targeted ESLint command reports zero errors for changed files, with existing warnings only |
| 3.3 | `frontend/components/TopologyViewer.test.tsx`; `frontend/components/RelationshipManager.visualEditor.test.tsx`; `frontend/components/CIDetailModal.test.tsx` | Component | ⚠️ Runner blocked locally | ✅ Written first for shared medium/icon/authority/tooltip rows in topology/relationship/detail surfaces and scoped public-IP fallback in `CIDetailModal` | ❌ Not claimed: focused Vitest remains blocked by Rollup native module signing mismatch | ✅ Covers SD-WAN, VPN, and satellite visual paths plus `UP` warning and neutral no-`DEGRADED` authority assertions | ✅ Shared visual summary component avoids per-surface authority/icon duplication |
| 3.4 | `frontend/components/TopologyViewer.test.tsx`; `frontend/components/RelationshipManager.visualEditor.test.tsx`; `frontend/components/CIDetailModal.test.tsx` | Component | ⚠️ Runner blocked locally | ✅ Covered by 3.3 RED tests before implementation | ❌ Not claimed: implementation is present but focused Vitest cannot execute locally | ✅ `TopologyViewer`, `RelationshipManager`, and `CIDetailModal` use `resolveTunnelVisual`; `CIDetailModal` uses scoped `node.public_ip` with metadata fallback only from already-provided node data | ✅ TypeScript spot-check found no changed-file errors; targeted ESLint reports zero errors |
| 3.5 | Frontend focused Vitest; `backend/tests/test_routers_nodes.py`; `backend/tests/test_routers_links.py` | Verification | N/A | N/A | ⚠️ Partial: backend pytest passed; frontend Vitest blocked before test collection by Rollup native module signing mismatch | N/A | N/A |

## Test Commands and Results

- `OPENSSL_CONF=/dev/null /Applications/Codex.app/Contents/Resources/cua_node/bin/node node_modules/vitest/vitest.mjs run components/NetworkVisualizer.test.tsx components/MonitoringConsole.test.tsx components/TopologyViewer.test.tsx components/RelationshipManager.visualEditor.test.tsx components/CIDetailModal.test.tsx` from `frontend/` → blocked before collection: `@rollup/rollup-darwin-x64/rollup.darwin-x64.node` code signature not valid for use in process; mapping process and mapped file have different Team IDs.
- `OPENSSL_CONF=/dev/null /Applications/Codex.app/Contents/Resources/cua_node/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/`, filtered to changed files → no changed-file TypeScript errors; full project still has unrelated pre-existing TypeScript errors.
- `OPENSSL_CONF=/dev/null /Applications/Codex.app/Contents/Resources/cua_node/bin/node node_modules/eslint/bin/eslint.js ...changed files...` from `frontend/` → exit 0, zero errors; existing warnings remain in legacy component files.
- `/private/tmp/next-gen-pr2-py311/bin/python -m pytest backend/tests/test_routers_nodes.py backend/tests/test_routers_links.py` → passed: 64 passed, 18 warnings.
- Prettier direct command over changed frontend files → passed and formatted files.

## Files Touched

- `frontend/components/NetworkVisualizer.test.tsx` — RED component tests for visible tunnel health filtering, neutral `UNKNOWN`, `UP` warning/error tooltip rows, and kill-switch context.
- `frontend/components/MonitoringConsole.test.tsx` — RED component tests for category-visible tunnel filtering, shared status rows, and kill-switch context.
- `frontend/components/TopologyViewer.test.tsx` — RED component test for shared SD-WAN visual rows.
- `frontend/components/RelationshipManager.visualEditor.test.tsx` — RED relationship table test for shared VPN visual rows.
- `frontend/components/CIDetailModal.test.tsx` — RED detail modal test for scoped public-IP fallback and satellite tunnel rows.
- `frontend/components/TunnelVisualSummary.tsx` — shared presentational summary for medium icon, authority text, warning badge, and tooltip rows.
- `frontend/components/NetworkVisualizer.tsx` — integrates visible tunnel health and shared visual summaries for filtered graph links.
- `frontend/components/MonitoringConsole.tsx` — integrates visible tunnel health and shared visual summaries for map-visible links.
- `frontend/components/TopologyViewer.tsx` — renders shared tunnel visual rows for relevant topology links.
- `frontend/components/RelationshipManager.tsx` — renders shared tunnel visual rows in CI relationship rows.
- `frontend/components/CIDetailModal.tsx` — renders scoped public-IP fallback and shared topology tunnel context from provided node metadata.
- `frontend/types.ts` — extends `GraphLink` with optional existing tunnel link id and health payload fields for frontend surface consumers.
- `frontend/utils/tunnelVisuals.ts` — narrows visual state typing without changing authority semantics.
- `openspec/changes/feat-324-tunnel-visualization/tasks.md` — marks RED tasks 3.1 and 3.3 complete only.
- `openspec/changes/feat-324-tunnel-visualization/apply-progress.md` — appends this PR3 TDD and verification evidence.

## Deviations

- GREEN implementation tasks 3.2 and 3.4 are intentionally not checked off because focused frontend Vitest cannot execute in this local environment.
- Verification task 3.5 is intentionally not checked off because frontend Vitest is blocked locally; backend scoped public-IP tests pass.
- Added a small shared presentational component, `TunnelVisualSummary`, to avoid duplicating the shared visual contract across PR3 surfaces.

## Remaining Tasks

- [ ] Run focused frontend Vitest in a CI-capable environment; if passing, mark 3.2 and 3.4 complete.
- [ ] Complete PR3 verification by recording passing frontend evidence, then mark 3.5 complete.
- [ ] Run final PR review/CI before creating or updating PR3.

---

## PR3 CI GREEN Validation — 2026-07-06

## Completed Task Checkboxes

- [x] 3.2 GREEN completed: CI validated NetworkVisualizer and MonitoringConsole surface integrations.
- [x] 3.4 GREEN completed: CI validated TopologyViewer, RelationshipManager, and CIDetailModal shared visual contract integrations.
- [x] 3.5 VERIFY completed: PR3 CI and local lint/format evidence passed without adding backend health normalization, bulk health endpoints, pollers, assets, or authority semantic changes.

## CI Evidence

PR #370 head `3b50923df00abf84a55d51c676c82c1c1d07e067` completed successfully for the checks triggered by the PR3 frontend/OpenSpec change set:

- `frontend-tests` → success
- `smoke` → success
- `lint-frontend` → success
- `lint-backend` → success
- `lint-verify (PR1 gate)` → success
- `ci-verify (PR3 gate)` → success
- `shellcheck` → success
- `yamllint` → success
- `actionlint` → success

Backend focused regression evidence remains from PR3 local verification:

- `/private/tmp/next-gen-pr2-py311/bin/python -m pytest backend/tests/test_routers_nodes.py backend/tests/test_routers_links.py` → 64 passed, 18 warnings.

## TDD Cycle Evidence Update

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.2 | `frontend/components/NetworkVisualizer.test.tsx`; `frontend/components/MonitoringConsole.test.tsx` | Component | ✅ CI `frontend-tests` validated after local Vitest was blocked by macOS Rollup/Node signing | ✅ RED tests covered neutral UNKNOWN, UP warning badge, tooltip errors, visible filtering, kill switch, and canonical encoded visual-key lookup | ✅ PR #370 CI `frontend-tests` passed on head `3b50923df00abf84a55d51c676c82c1c1d07e067` | ✅ Canonical `encodeTunnelLinkId(link)` lookup regression was added after fresh review found arbitrary `tunnel_link_id` mismatch risk | ✅ Changed-file `lint-frontend` and Prettier checks passed locally and in CI |
| 3.4 | `frontend/components/TopologyViewer.test.tsx`; `frontend/components/RelationshipManager.visualEditor.test.tsx`; `frontend/components/CIDetailModal.test.tsx` | Component | ✅ CI `frontend-tests` validated after local Vitest was blocked by macOS Rollup/Node signing | ✅ RED tests covered shared medium/icon/status/tooltip rows and scoped public-IP fallback | ✅ PR #370 CI `frontend-tests` passed on head `3b50923df00abf84a55d51c676c82c1c1d07e067` | ✅ Duplicate visible text expectations were corrected to assert intentional duplicate rendering rather than weakening coverage | ✅ Changed-file `lint-frontend` and Prettier checks passed locally and in CI |
| 3.5 | PR3 CI + local focused backend pytest | Verify | ✅ CI checks and local backend regression tests are available | ✅ Verification criteria were defined in tasks before PR3 implementation | ✅ CI passed for PR3 frontend/OpenSpec changes; backend focused regression remained green locally | ✅ No backend scope, health normalization, bulk health endpoint, poller, asset, or authority-semantic changes were introduced in PR3 | ✅ Fresh reviews cleared authority/public-IP/polling/key blockers before PR3 CI GREEN |

## Remaining Tasks

- [ ] Merge PR3 after review.
- [ ] After PR3 merge, update tracker PR #359 and decide whether final tracker PR is ready to undraft/merge to `main`.
