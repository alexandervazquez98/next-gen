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
