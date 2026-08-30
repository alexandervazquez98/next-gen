# Tasks: Stale Event Review Reminders (Issue #154)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 600–800 (PR1 ~350–450; PR2 ~250–350) |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR1 (backend) → PR2 (frontend) |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|----|----------------------|-----------------|-------------------|
| WU1 | Service scaffold (`stale_event_reminders.py`) + dataclasses + schema id | PR1 | `cd backend && pytest backend/tests/test_stale_event_reminders.py -k scaffold` | `python -c "from backend.services.stale_event_reminders import RECOMMENDATION_SCHEMA_VERSION"` | Delete module; no DB writes |
| WU2 | Detection Cypher: 3 reason codes + bounded `LIMIT` + filter predicate | PR1 | `cd backend && pytest backend/tests/test_stale_event_reminders.py -k reason_code` | Run query vs Neo4j fixture (10k Event rows) | Cypher lives in WU1; remove via WU1 rollback |
| WU3 | `StaleEventReminderSettings` + `from_env` + cached accessor + `.env.example` | PR1 | `cd backend && pytest backend/tests/test_stale_event_reminders.py -k settings` | `python -c "from backend.config import get_stale_event_reminder_settings"` | Revert `backend/config.py` block + `.env.example` |
| WU4 | Router `GET /api/events/recommendations` + `main.py` registration | PR1 | `cd backend && pytest backend/tests/test_stale_event_reminders.py -k router_get` | `curl /api/events/recommendations` returns schema-versioned JSON | Unmount router line; drop `backend/routers/event_recommendations.py` |
| WU5 | Quick-action endpoints + `record_critical_change` allow-list extension + 3 new `event_type` strings | PR1 | `cd backend && pytest backend/tests/test_audit_router.py -k stale_reminder` | Toggle kill-switch; verify `audit_events` row in Postgres | Allow-list edit additive; revert removes new keys only |
| WU6 | Pytest backend suite (3 reason codes, kill-switch, audit, no-mutation, scan guards) | PR1 | `cd backend && pytest backend/tests/test_stale_event_reminders.py backend/tests/test_audit_router.py` | `pytest --maxfail=1` green | Tests revert with code |
| WU7 | `StaleRemindersPanel` + query hook + mutation hooks + `queryKeys` + API wrappers | PR2 | `cd frontend && corepack pnpm test:run -- StaleRemindersPanel` | `pnpm dev`; panel renders empty state | Delete panel + 2 hooks; revert `queryKeys.ts` + `queryResources.ts` |
| WU8 | Mount in `MonitoringConsole` + Vitest panel tests + Playwright Snooze E2E | PR2 | `cd frontend && corepack pnpm test:run && corepack pnpm exec playwright test e2e/stale-reminders.spec.ts` | `pnpm dev`; force-create stale event; verify panel + audit row | Remove `MonitoringConsole.tsx` import; delete spec |

**PR relationship (feature-branch-chain).** PR1 targets `feat-154-stale-event-reminders` tracker; PR2 targets PR1's branch. Rebase PR2 onto PR1 tip before opening; PR2's diff vs `main` must stay isolated. PR2 frontend tests stub the 503 — no live backend dependency.

## Phase 1: Backend Foundation (PR1)

- [ ] 1.1 **[PR1][WU1]** Create `backend/services/stale_event_reminders.py` — frozen dataclasses `StaleEventRecommendation`/`StaleEventDetection`, `to_dict`/`from_mapping`, `RECOMMENDATION_SCHEMA_VERSION = "stale-event-reminder-recommendation.v1"`, `_open_read_session`/`_execute_read_query` mirroring `legacy_event_discriminator_audit.py`.
- [ ] 1.2 **[PR1][WU1][RED-first]** RED: `backend/tests/test_stale_event_reminders.py` asserts `RECOMMENDATION_SCHEMA_VERSION` constant + `from_mapping` round-trip; `cd backend && pytest -k scaffold` (red → green).

## Phase 2: Detection Cypher + Config (PR1)

- [ ] 2.1 **[PR1][WU2]** Implement `READ_ONLY_DETECTION_QUERY` — `OPTIONAL MATCH` on `:HAS_EVENT`/`:TRIGGERED_BY`, `LIMIT $limit`, three `reason_code` branches (`link_missing`/`older_than_threshold`/`no_refresh_in_window`); filter `(status IN ['OPEN','ACK'] AND event_type='COLLECTION_FAILURE' AND failure_family='SNMP_NO_RESPONSE')`.
- [ ] 2.2 **[PR1][WU2][RED-first]** RED: limit clamps (`limit=0`/`limit>500` → 422); Cypher contains no `MERGE`/`SET`/`DELETE`/`CREATE` (threat: scan size + accidental mutation).
- [ ] 2.3 **[PR1][WU3]** Add `StaleEventReminderSettings(BaseModel)` + `from_env` + `_stale_event_reminder_settings` + `get_stale_event_reminder_settings()` to `backend/config.py` after `EventPruneSettings`; defaults `enabled=True`, `age_hours=24`, `refresh_window_hours=6`, `snooze_ttl_hours=24`.
- [ ] 2.4 **[PR1][WU3]** Document `STALE_EVENT_REMINDER_*` envs in `.env.example` after prune settings.
- [ ] 2.5 **[PR1][WU3][RED-first]** RED: `from_env` reads overrides; defaults applied when env absent.

## Phase 3: Router + Quick Actions + Audit (PR1)

- [ ] 3.1 **[PR1][WU4]** Create `backend/routers/event_recommendations.py` — `APIRouter(prefix="/events/recommendations")`, `GET ""` (gated `EVENT_VIEW`) returns schema-versioned JSON; kill-switch → `{"rows": []}`.
- [ ] 3.2 **[PR1][WU4]** Register router in `backend/main.py` (`app.include_router(event_recommendations.router, prefix="/api")`).
- [ ] 3.3 **[PR1][WU4][RED-first]** RED: GET 403 without `EVENT_VIEW`; kill-switch off returns empty rows.
- [ ] 3.4 **[PR1][WU5]** Add three POST `/dismiss`/`/snooze`/`/escalate` calling `audit_service.record_critical_change()` with `event_type` ∈ {`STALE_EVENT_REMINDER_DISMISS`,`STALE_EVENT_REMINDER_SNOOZE`,`STALE_EVENT_REMINDER_ESCALATE`}; kill-switch off → 503 BEFORE audit emission.
- [ ] 3.5 **[PR1][WU5]** Extend `AUDIT_CONTEXT_ALLOWED_KEYS` in `backend/services/audit_service.py` with `"event_id"`, `"reason_code"`, `"snooze_until"` (threat: snooze-TTL bypass + sensitive-context leak).
- [ ] 3.6 **[PR1][WU5][RED-first]** RED: snooze ignores request-body `snooze_until` (threat: snooze-TTL bypass); `snooze_until == now + settings.snooze_ttl_hours`; no `Event` mutation; audit context contains only allow-listed keys, never `token`/`cookie`/`authorization`/`body`.

## Phase 4: Backend Test Suite (PR1)

- [ ] 4.1 **[PR1][WU6]** Extend `backend/tests/test_audit_router.py` — dismiss/snooze/escalate audit rows include new context keys; kill-switch off returns 503 and writes no audit row (spec: audit-logging delta).
- [ ] 4.2 **[PR1][WU6]** Final backend: `cd backend && pytest backend/tests/test_stale_event_reminders.py backend/tests/test_audit_router.py` green.

## Phase 5: Frontend Scaffold (PR2)

- [ ] 5.1 **[PR2][WU7]** Add query keys `staleReminders`/`staleReminderAction(id,action)` in `frontend/services/queryKeys.ts` + API wrappers in `frontend/services/queryResources.ts`.
- [ ] 5.2 **[PR2][WU7]** Create `frontend/hooks/queries/useStaleEventRemindersQuery.ts` (`refetchInterval: 60_000`, gated `EVENT_VIEW`) + `useStaleReminderMutations.ts` returning `{dismiss,snooze,escalate}` invalidating `queryKeys.staleReminders()`.
- [ ] 5.3 **[PR2][WU7]** Create `frontend/components/StaleRemindersPanel.tsx` — collapsible card, reason-code badges, CI/MetricDef chips, confirm modals, "Advisory only — does not close events" header copy (threat: operator misinterprets advisory).
- [ ] 5.4 **[PR2][WU7][RED-first]** Vitest `frontend/components/__tests__/StaleRemindersPanel.test.tsx` — empty state, reason badge per code, confirm modal opens, mutation called on confirm, hidden without `EVENT_VIEW`, loading skeleton.

## Phase 6: Frontend Mount + E2E (PR2)

- [ ] 6.1 **[PR2][WU8]** Mount `<StaleRemindersPanel />` in `frontend/components/MonitoringConsole.tsx` below KPI grid (DASHBOARD branch, ~line 1336) with `canViewEventDetail` guard.
- [ ] 6.2 **[PR2][WU8][RED-first]** Add Playwright `frontend/playwright/e2e/stale-reminders.spec.ts` — panel renders, Snooze confirm modal opens, audit row visible in Audit Log UI under `STALE_EVENT_REMINDER_SNOOZE`.
- [ ] 6.3 **[PR2][WU8]** Final frontend: `cd frontend && corepack pnpm test:run && corepack pnpm exec playwright test e2e/stale-reminders.spec.ts` green.
