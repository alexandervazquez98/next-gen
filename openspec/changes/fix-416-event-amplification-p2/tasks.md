# Tasks: fix-416-event-amplification-p2

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 612 (backend 305 / frontend 112 / tests 195) |
| 400-line budget risk | Medium |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Delivery strategy | ask-always |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | PR | Focused test | Harness | Rollback |
|------|------|----|--------------|---------|----------|
| 1 | Pydantic + allowlist | PR 1 | `cd backend && python -m pytest -q tests/test_event_service.py -k allowlist` | N/A — pure | `models/core.py` + `_public_event_summary` |
| 2 | `include_children` filter | PR 1 | `cd backend && python -m pytest -q tests/test_routers_events.py -k include_children` | N/A — mocked | router param + `get_events` |
| 3 | Drill-down endpoint | PR 1 | `cd backend && python -m pytest -q tests/test_routers_events.py -k affected` | N/A — mocked | new router + `get_affected_siblings` |
| 4 | AI chat raw opt-in | PR 1 | `cd backend && python -m pytest -q tests/test_ai_chat_service.py -k raw` | N/A — harness | `ai_chat_service.py:422` |
| 5 | Query key + resource | PR 1 | `cd frontend && corepack pnpm test:run -t activeEvents` | Vitest | `queryKeys.ts` + `queryResources.ts` + `useActiveEventsQuery.ts` |
| 6 | `CONNECTS_TO` correlation | PR 1 | `cd frontend && corepack pnpm test:run -t useEventCorrelation` | Vitest | `useEventCorrelation.ts` |
| 7 | KPI root filter + modal | PR 1 | `cd frontend && corepack pnpm test:run -t MonitoringConsole` | Vitest | `MonitoringConsole.tsx` + `useAffectedCIsQuery.ts` |
| 8 | Compat mocks (3 files) | PR 1 | `cd frontend && corepack pnpm test:run -t 'MonitoringConsole.smoke\|EventDetailModal.acceptance\|MonitoringConsole.forcedClose'` | Vitest | 3 test files |
| 9 | E2E drill-down | PR 1 | `cd frontend && corepack pnpm exec playwright test test/e2e/monitoring-event-kpi.spec.ts` | Playwright dev | new spec file |
| 10 | Changelog entry | PR 1 | `cd backend && python -m pytest -q && cd frontend && corepack pnpm test:run` | N/A — docs | `CHANGELOG.md` |

## Phase 1 — Backend Surface (3 commits)

- [x] 1. **RED** — `backend/tests/test_event_service.py`: allowlist + `EventFeedSummary.affected_*` cases (REQ-001/002; SCN-006/010). Pair with Task 2.
- [x] 2. Extend `backend/models/core.py` `EventFeedSummary` w/ `affected_ci_ids`+`affected_count` + exclude-empty serializer; admit keys in `_public_event_summary` (REQ-001/002). Commit: `feat(api): expose affected_ci_ids and affected_count on EventFeedSummary`.
- [x] 3. **RED** — `tests/test_routers_events.py`: matrix default/`true`/`false` `include_children` + order (REQ-003; SCN-001/002/003). Pair with Task 4.
- [x] 4. Add `include_children: bool = Query(False)` on `GET /api/events`; thread to `event_service.get_events`; append `coalesce(e.correlation_type,'ROOT')='ROOT'` only when false; preserve `ORDER BY e.created_at DESC` (REQ-003). Commit: `feat(api): filter get_events by include_children flag`.
- [x] 5. **RED** — Drill-down tests: 200 ordered entries, 404 unknown, 403 no `EVENT_VIEW`, empty `[]` (REQ-004; SCN-004/005/010). Pair with Task 6.
- [x] 6. Implement `event_service.get_affected_siblings(event_id)` (`UNWIND`+`MATCH CI`); add `GET /api/events/{event_id}/affected` before `/{event_id}`; reuse `EVENT_VIEW` + `_raise_event_not_found` (REQ-004). Commit: `feat(api): add affected-CI drill-down endpoint`.

## Phase 2 — Consumer Migration (1 commit)

- [x] 7. Add explicit `include_children=True` to harness boundary at `backend/services/ai_chat_service.py:422`; preserve scope filters (REQ-009). Commit: `fix(ai-chat): preserve raw event rows in chat context`.

## Phase 3 — Frontend Surface (4 commits)

- [x] 8. **RED** — `queryKeys.test.ts` + `resourceQueries.test.tsx`: distinct cache keys for `includeChildren: false` vs `true` (REQ-006; SCN-007). Pair with Task 9.
- [x] 9. Add `includeChildren` discriminator to `queryKeys.activeEvents`; thread `include_children: boolean` through `fetchActiveEvents`; default `false` in `useActiveEventsQuery.ts` (REQ-006/008). Commit: `feat(queries): thread include_children through event query keys`.
- [x] 10. **RED** — `useEventCorrelation.test.ts`: `CONNECTS_TO` regression — consumer folds under provider ROOT, `isRoot=false` (REQ-007; SCN-009). Pair with Task 11.
- [x] 11. Extend topology branch in `frontend/hooks/useEventCorrelation.ts:89` to include `CONNECTS_TO` (REQ-007). Commit: `feat(correlation): include CONNECTS_TO in upstream grouping`.
- [x] 12. **RED** — New `useAffectedCIsQuery.test.ts`; KPI root filter + "affecting N CIs" in `MonitoringConsole.test.tsx` (REQ-005; SCN-008). Pair with Task 13.
- [x] 13. Create `frontend/hooks/queries/useAffectedCIsQuery.ts`; reshape KPI block in `MonitoringConsole.tsx` (root filter, sub-label, drill-down modal w/ per-root `useQueries`) (REQ-005). Commit: `feat(monitoring): surface root events and affecting-CIs count`.

## Phase 4 — Compat Updates (1 commit)

- [x] 14. Update `MonitoringConsole.smoke.test.tsx`, `EventDetailModal.acceptance.test.tsx`, `MonitoringConsole.forcedClose.test.tsx` to mock root-only (or `?include_children=true`); add `/events/{id}/affected` mock (REQ-009; SCN-008). Commit: `test(monitoring): align smoke mocks with root-only api contract`.

## Phase 5 — E2E + Changelog (1 commit)

- [x] 15. **RED + impl** — Create `frontend/test/e2e/monitoring-event-kpi.spec.ts`: stub root feed (2 root + 1 propagated), intercept `/events/{root_id}/affected`, click Total Active, assert modal + "affecting N CIs" (REQ-005; SCN-008). Commit: `test(e2e): add monitoring KPI drill-down playwright spec`.
- [x] 16. `[Unreleased]` `BREAKING` entry in `CHANGELOG.md` flagging `GET /api/events` default → root-only; mitigation = opt-in `?include_children=true`. Commit: `docs(changelog): note p2 event root exposure breaking default`.

## Verification

- [x] 17. Run `cd backend && python -m pytest -q` (expect 1760+ pass), `cd backend && python -m pytest -q -m event`, `cd frontend && corepack pnpm test:run`; plus `pre-commit run --all-files`, `cd backend && ruff check .`, `cd backend && black --check .`. No commit unless a unit changes.

## Notes

- `delivery_strategy = ask-always` → orchestrator MUST prompt user (single PR vs chained) before `sdd-apply`. Forecast = 612 lines, under 800 → single PR recommended.
- Do NOT touch `backend/engines/snmp_worker.py` (P0 contract); no P1/P3 tasks.
- All applicable threat-matrix rows have explicit RED tests; N/A row omitted.