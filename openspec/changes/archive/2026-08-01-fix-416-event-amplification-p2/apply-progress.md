# Apply Progress: fix-416-event-amplification-p2

## Branch
`fix/416-event-amplification-p2` (based on `origin/main` @ 3e8a6ec with P0 already merged)

## Status
Completed — all 11 work-unit commits (A → J + black formatting) landed on the branch.

## Workload Budget Tracking

- `changed_lines_total`: 1375 insertions + 35 deletions across 23 files (`git diff --stat origin/main..HEAD`).
- `within_budget`: **FALSE** — exceeds the 800-line review budget by ~1.7×.
  Forecast was 612 lines; the actual growth is explained by:
  - Strict-TDD matrix covering SCN-001..010 with full mock coverage in `test_event_service.py` (326 lines).
  - Drill-down modal in `MonitoringConsole.tsx` (198 lines) for per-root `useQueries` + sub-label.
  - Three new test classes in `test_routers_events.py` (108 lines).
  - Playwright spec with full assertion set (128 lines).
  Production code (services + components) is ~400 lines; tests + docs account for the rest.

## Per-Commit Tally

| Commit | Subject | Files | Insertions | Deletions |
|--------|---------|-------|-----------:|----------:|
| `beb01c7` | feat(api): expose affected_ci_ids and affected_count on EventFeedSummary | 4 | 413 | 0 |
| `5c0c304` | feat(api): filter get_events by include_children flag | 4 | 102 | 118 |
| `af70db2` | feat(api): add affected-CI drill-down endpoint | 4 | 241 | 0 |
| `92d6f80` | fix(ai-chat): preserve raw event rows in chat context | 1 | 14 | 1 |
| `18f4d23` | feat(queries): thread include_children through event query keys | 8 | 138 | 10 |
| `5ac6f3d` | feat(correlation): include CONNECTS_TO in upstream grouping | 2 | 33 | 3 |
| `e9add77` | feat(monitoring): surface root events and affecting-CIs count | 2 | 335 | 7 |
| `032ec0e` | test(monitoring): align smoke mocks with root-only api contract | 2 | 72 | 0 |
| `411d90a` | test(e2e): add monitoring KPI drill-down playwright spec | 1 | 128 | 0 |
| `f361ca4` | docs(changelog): note p2 event root exposure breaking default | 1 | 10 | 0 |
| `4feef87` | style(backend): apply black formatting | 3 | 25 | 32 |

## TDD Cycle Evidence

| Task | RED test | GREEN impl | REFACTOR | Commit |
|------|----------|------------|----------|--------|
| 1-2 | `test_event_service.py::TestPublicEventSummaryAffectedExposure` (4 cases) | `models/core.py` + `_public_event_summary` | empty/zero filter | `beb01c7` |
| 3-4 | `test_event_service.py::TestGetEventsIncludeChildren` (4 cases) + `test_routers_events.py::TestGetEventsIncludeChildren` (3 cases) | `get_events` + router `Query` param | — | `5c0c304` |
| 5-6 | `test_event_service.py::TestGetAffectedSiblings` (4 cases) + `test_routers_events.py::TestGetEventAffected` (3 cases) | `get_affected_siblings` + `/events/{id}/affected` route | — | `af70db2` |
| 7 | — (existing `test_ai_chat_service.py` passes) | `ai_chat_service.list_events_for_harness` `include_children=True` | — | `92d6f80` |
| 8-9 | `resourceQueries.test.tsx` SCN-007 + `queryKeys.test.ts` | `queryKeys.activeEvents` + `useActiveEventsQuery` + `fetchActiveEvents` | — | `18f4d23` |
| 10-11 | `useEventCorrelation.test.ts` SCN-009 | `useEventCorrelation.ts` `CONNECTS_TO` branch | — | `5ac6f3d` |
| 12-13 | `MonitoringConsole.test.tsx` SCN-008 | `DrillDownModal` + KPI root filter + sub-label | — | `e9add77` |
| 14 | `MonitoringConsole.smoke.test.tsx` SCN-008 + `EventDetailModal.acceptance.test.tsx` affected mock | (mock updates only) | — | `032ec0e` |
| 15 | `monitoring-event-kpi.spec.ts` | (Playwright spec, RED by construction) | — | `411d90a` |
| 16 | — | `CHANGELOG.md` BREAKING entry | — | `f361ca4` |
| 17 | `pytest` + `vitest` + `ruff` + `black` | — | black formatting | `4feef87` |

## Final Validation

- **Backend tests**: 1725 passed, 1 skipped (excluding 2 pre-existing Docker-dependent files: `test_auth_router_refresh.py` cookie secure-flag, `test_writer_advisory_lock.py` testcontainers). New `test_event_service.py` adds 14 RED tests × 4 classes (SCN-001..005, 006, 010).
- **Backend -m "event or api"**: 65 passed, 1718 deselected.
- **Frontend tests**: 575 passed (69 files). New tests: SCN-007 (query key discriminator), SCN-008 (KPI root filter + sub-label), SCN-009 (`CONNECTS_TO` correlation).
- **Lint**: `ruff check` clean on all 6 touched backend files.
- **Format**: `black --check` clean after `black` pass (1 corrective commit).
- **Playwright**: cannot run locally — Docker daemon not available. The spec file is shipped intact and will run in CI's smoke lane.

## Notes and Known Limitations

- **`within_budget` is false**: 1410 lines vs 800 budget. Driver is the strict-TDD test matrix (~600 lines of new tests), which is by design. The production code is ~400 lines and matches the design forecast (~305 backend + ~112 frontend ≈ 417 lines).
- **Pre-existing pre-P0 PROPAGATED rows**: not in scope; the `recommend-legacy-event-backfill` change (archived) handles them separately.
- **No edits to the writer path** (`backend/engines/snmp_worker.py`), `services/snmp_service.py`, `polling/`, or canonical specs. P0 contract is preserved.
- **No push, no PR, no Co-Authored-By AI.**
- **No size-exception requested**: budget breach is reported in the apply summary as a risk; orchestrator/verify may decide on a chained-PR split.
