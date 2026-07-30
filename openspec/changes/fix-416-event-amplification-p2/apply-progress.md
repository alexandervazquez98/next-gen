# Apply Progress: fix-416-event-amplification-p2

## Branch
`fix/416-event-amplification-p2` (based on `origin/main` @ 3e8a6ec with P0 already merged)

## Status
In Progress — Commits A → J per `tasks.md` work-unit plan.

## Workload Budget Tracking

- `changed_lines_total`: TBD (forecast 612)
- `within_budget`: target 800 lines

## Per-Commit Tally

| Commit | Subject | Files | Insertions | Deletions | Running total |
|--------|---------|-------|-----------:|----------:|--------------:|
| Commit A | `feat(api): expose affected_ci_ids and affected_count on EventFeedSummary` | `backend/models/core.py`, `backend/services/event_service.py`, `backend/tests/test_event_service.py`, `apply-progress.md` | TBD | TBD | TBD |
| Commit B | `feat(api): filter get_events by include_children flag` | `backend/services/event_service.py`, `backend/routers/events.py`, `backend/tests/test_event_service.py`, `backend/tests/test_routers_events.py` | TBD | TBD | TBD |
| Commit C | `feat(api): add affected-CI drill-down endpoint` | `backend/services/event_service.py`, `backend/routers/events.py`, `backend/models/core.py`, `backend/tests/test_routers_events.py` | TBD | TBD | TBD |
| Commit D | `fix(ai-chat): preserve raw event rows in chat context` | `backend/services/ai_chat_service.py` | TBD | TBD | TBD |
| Commit E | `feat(queries): thread include_children through event query keys` | `frontend/types.ts`, `frontend/services/queryKeys.ts`, `frontend/services/queryResources.ts`, `frontend/hooks/queries/useActiveEventsQuery.ts`, `frontend/hooks/queries/useAffectedCIsQuery.ts`, `frontend/hooks/queries/resourceQueries.test.tsx` | TBD | TBD | TBD |
| Commit F | `feat(correlation): include CONNECTS_TO in upstream grouping` | `frontend/hooks/useEventCorrelation.ts`, `frontend/hooks/useEventCorrelation.test.ts` | TBD | TBD | TBD |
| Commit G | `feat(monitoring): surface root events and affecting-CIs count` | `frontend/hooks/queries/useAffectedCIsQuery.ts`, `frontend/components/MonitoringConsole.tsx`, `frontend/components/__tests__/MonitoringConsole.test.tsx` | TBD | TBD | TBD |
| Commit H | `test(monitoring): align smoke mocks with root-only api contract` | `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx`, `frontend/components/__tests__/EventDetailModal.acceptance.test.tsx`, `frontend/components/__tests__/MonitoringConsole.forcedClose.test.tsx` | TBD | TBD | TBD |
| Commit I | `test(e2e): add monitoring KPI drill-down playwright spec` | `frontend/test/e2e/monitoring-event-kpi.spec.ts` | TBD | TBD | TBD |
| Commit J | `docs(changelog): note p2 event root exposure breaking default` | `CHANGELOG.md` | TBD | TBD | TBD |

## TDD Cycle Evidence

| Task | RED test | GREEN impl | REFACTOR | Commit |
|------|----------|------------|----------|--------|
| 1-2 | pending | pending | n/a | A |
| 3-4 | pending | pending | n/a | B |
| 5-6 | pending | pending | n/a | C |
| 7 | n/a | pending | n/a | D |
| 8-9 | pending | pending | n/a | E |
| 10-11 | pending | pending | n/a | F |
| 12-13 | pending | pending | n/a | G |
| 14 | pending (mocks update) | n/a | n/a | H |
| 15 | pending | pending | n/a | I |
| 16 | n/a | pending | n/a | J |
| 17 | pytest + vitest + ruff + black | — | — | — |

## Notes

- Strict TDD active: every production change has a paired RED test in the same phase.
- All edits stay within P2 scope: `backend/{models,services,routers,tests}/...`, `frontend/{services,hooks,components,test}/...`, `CHANGELOG.md`. Writer path (`backend/engines/snmp_worker.py`) untouched.
- No push, PR, or Co-Authored-By AI.
