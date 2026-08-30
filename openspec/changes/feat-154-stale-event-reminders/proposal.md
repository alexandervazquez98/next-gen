# Proposal: Stale Event Review Reminders (Issue #154)

## Intent

Operators have no visibility into events that linger `OPEN`/`ACK` after their condition changed (e.g. SNMP no-response events from before issue #152). Business rule: events MUST NOT be silently closed without operator review, but forgotten events age indefinitely. Add an advisory recommendation surface for stale events. **No auto-close, ever.** First slice targets SNMP `COLLECTION_FAILURE` + `failure_family = SNMP_NO_RESPONSE`; extensible to other families later.

## Scope

### In Scope

- Read-only detection of stale `OPEN`/`ACK` events (configurable age threshold).
- `GET /api/events/recommendations`: event id/title/severity/status, CI/metric when resolvable, age, `last_seen`, refresh status, `reason_code` ∈ `{older_than_threshold, no_refresh_in_window, link_missing}`.
- Frontend `StaleRemindersPanel` (collapsible) inside `MonitoringConsole`.
- Quick actions: `dismiss`, `snooze` (TTL), `escalate` (audit-only handoff). All write audit rows via `record_critical_change()`.
- New `StaleEventReminderSettings` config class mirroring `EventPruneSettings` (`STALE_EVENT_REMINDER_*` env, kill-switch default true).
- Schema-versioned output `stale-event-reminder-recommendation.v1`.

### Out of Scope

- No auto-close, auto-prune, auto-ACK, or any Event mutation from this surface.
- No Slack/email/ITSM side effects; no `THRESHOLD_BREACH`/`AVAILABILITY` expansion; durable snooze deferred (in-memory first slice).

## Capabilities

### New Capabilities

- `stale-event-reminders`: read-only detection, recommendation engine, API, UI for stale `OPEN`/`ACK` reminders.

### Modified Capabilities

- `audit-logging`: three new `event_type` strings (`stale_reminder.dismissed|snoozed|escalated`) under existing `EVENT_*` domain. No schema change.

## Approach

- `backend/services/stale_event_reminders.py` mirrors `legacy_event_discriminator_audit.py`: dataclasses, `STALE_REMINDER_SCHEMA_VERSION`, read-only Cypher via `READ_ACCESS`, Markdown+JSON renderers, `build_stale_event_recommendations()`.
- Detection Cypher: `OPTIONAL MATCH` on `(:Event)-[:HAS_EVENT]?->(:CI)` and `(:Event)-[:TRIGGERED_BY]?->(:MetricDef)` so missing CI/MetricDef becomes `link_missing`. Filter: `status IN ['OPEN','ACK'] AND event_type='COLLECTION_FAILURE' AND failure_family='SNMP_NO_RESPONSE' AND (now - coalesce(last_seen, created_at)) > threshold` (defaults: 24h age, 6h no-refresh).
- `backend/routers/event_recommendations.py`: `GET /recommendations` (`EVENT_VIEW` gated) + three quick-action `POST`s. Each calls `audit_service.record_critical_change()` with `target_type="Event"`; allowlisted context keys only (`event_id`, `reason_code`, `snooze_until`).
- Frontend: `StaleRemindersPanel.tsx` mounted in `MonitoringConsole`; `useStaleEventRemindersQuery.ts` polls every 30s using existing React Query defaults.
- Strict TDD: failing-first unit tests for classifier, dataclass round-trip, Markdown/JSON parity, Cypher arg shape, no-mutation guarantee, audit-event shape. Mirror `test_legacy_event_discriminator_audit.py` + `test_audit_router.py`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/services/stale_event_reminders.py` + `backend/routers/event_recommendations.py` | New | Classifier/renderers + `GET /recommendations` + 3 quick-action endpoints. |
| `backend/config.py` + `backend/main.py` + `backend/services/audit_service.py` | Modified | `StaleEventReminderSettings` + router registration + 3 new `event_type` strings. |
| `backend/tests/test_stale_event_reminders.py` + `backend/tests/test_audit_router.py` | New/Modified | Classifier/threshold + audit-row assertions. |
| `frontend/components/StaleRemindersPanel.tsx` + `frontend/components/__tests__/StaleRemindersPanel.test.tsx` | New | Collapsible panel + component tests. |
| `MonitoringConsole.tsx` + `useStaleEventRemindersQuery.ts` + `queryKeys.ts` + `services/api.ts` | Modified | Mount panel + polling hook + query key + 4 endpoint wrappers. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Detection query scans too many rows | Medium | Bounded `limit`; env kill-switch; `(status, event_type, failure_family)` filter. |
| Operator mistakes reminder for auto-close | Medium | UI + audit wording say "advisory only"; mutation impossible; reuse Slice 1 text. |
| Snooze lost on restart / sensitive context | Low | In-memory TTL (documented); `sanitize_context` + allowlisted keys. |
| Spec drift with legacy-event-backfill sibling | Low | Same renderer + `v1` versioning. |
| Review budget exceeded (800 lines) | Medium | `work-unit-commits`: PR1 backend, PR2 frontend; ≤400-line first slice. |

## Rollback Plan

- Revert new module/router + config class. Audit writes non-destructive — no compensating cleanup.
- Frontend: revert panel import + remove hook. Event feed untouched.
- DB: no schema changes.
- `STALE_EVENT_REMINDER_ENABLED=false` returns empty list + 503 on quick actions for in-prod disable without redeploy.

## Dependencies

- `backend/services/legacy_event_discriminator_audit.py` pattern (dataclasses + READ_ACCESS + Markdown/JSON + `RECOMMENDATION_SCHEMA_VERSION`).
- `backend/services/audit_service.py:record_critical_change()` + `backend/config.py` settings pattern (`EventPruneSettings`, `EventLockSettings`).
- React Query defaults + existing polling hooks.

## Success Criteria

- [ ] `GET /api/events/recommendations` returns schema-versioned JSON; no Event mutation possible from endpoint family.
- [ ] `StaleRemindersPanel` renders in `MonitoringConsole`; quick actions POST and invalidate query.
- [ ] All three quick actions write audit rows visible in Audit Log UI under `stale_reminder.{action}`.
- [ ] `STALE_EVENT_REMINDER_ENABLED=false` → empty list + 503 on quick actions.
- [ ] Unit tests pass: classifier, threshold, link-missing, schema version, Markdown/JSON parity, no-mutation, audit shape. `corepack pnpm test:run` and `python -m pytest` green.
