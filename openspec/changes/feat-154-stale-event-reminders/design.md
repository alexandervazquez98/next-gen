# Design: Stale Event Review Reminders (Issue #154)

## Technical Approach

Advisory-only surface that surfaces forgotten `OPEN`/`ACK` events without mutating them. Backend adds a read-only recommendation engine (`backend/services/stale_event_reminders.py`) mirroring `legacy_event_discriminator_audit.py`'s dataclass + `READ_ACCESS` + Markdown/JSON renderers shape, plus a router (`backend/routers/event_recommendations.py`) exposing `GET /api/events/recommendations` and three audit-emitting quick actions. Frontend adds `StaleRemindersPanel` (collapsible) mounted in `MonitoringConsole` next to the KPI cards, polled at 60s. Settings follow `EventPruneSettings` (`BaseModel` + `from_env()` + cached singleton). Scope is SNMP `COLLECTION_FAILURE` + `failure_family = SNMP_NO_RESPONSE` only.

## Context

Forgotten stale events age indefinitely once their root condition clears. Operators have no visibility into "should this still be open?" — only that the event exists. Per business rule, events MUST NOT be silently closed without operator review. Issue #154 asks for a **read-only** advisory surface plus audit-emitting quick actions (`dismiss`, `snooze`, `escalate`) that **never mutate `Event`**. First slice targets SNMP no-response, where the most accumulating back-catalog lives.

## Goals / Non-Goals

**Goals.** Detect stale `OPEN`/`ACK` events via three reason codes; expose paginated read-only recommendations; allow operators to record their decision via audit-emitting quick actions; provide a kill-switch.

**Non-Goals.** No auto-close, auto-prune, auto-ACK, or any `Event` mutation from this surface. No Slack/email/ITSM side effects. No `THRESHOLD_BREACH` / `AVAILABILITY` family expansion. No durable snooze state (in-memory TTL only, first slice).

## Architecture Decisions

### Decision: Mirror `legacy_event_discriminator_audit.py` for the service module

| Aspect | Choice | Tradeoff | Decision |
|---|---|---|---|
| Dataclass shape | `StaleEventRecommendation` + `StaleEventDetection` records (frozen dataclass, `to_dict()`, `from_mapping()`) | Matches Slice 1 precedent; serializer symmetry with renderer pair | Use same shape |
| Cypher access | `READ_ACCESS` via `neo4j.READ_ACCESS` (defensive fallback if neo4j missing) | Same defensive pattern; no write path possible | Use `READ_ACCESS` |
| Renderers | `recommendation_to_json_dict` + `recommendation_to_markdown` | Mirrors Slice 1; gives operators a copy-paste review artifact | Implement both |
| Schema id | `stale-event-reminder-recommendation.v1` | Distinct from `legacy-event-backfill-recommendation.v1`; explicit versioning for downstream | Use schema-versioned payload |

### Decision: Detection via single bounded Cypher with three reason codes

**Choice.** One parameterized Cypher that selects candidates matching `(status IN ['OPEN','ACK'] AND event_type = 'COLLECTION_FAILURE' AND failure_family = 'SNMP_NO_RESPONSE')`, computes age + refresh window in Cypher, and uses `OPTIONAL MATCH` on `:HAS_EVENT` / `:TRIGGERED_BY` to surface `link_missing`. Limit is enforced (default 100, env-bounded).

**Alternatives.** (a) Three separate queries per reason — rejected (3× round-trips, harder to keep a single bounded result set). (b) Python-side filtering — rejected (defeats index use, scans unbounded rows in app layer).

**Rationale.** Single bounded query is the lowest scan-size risk profile and produces a stable row shape for the renderer. `OPTIONAL MATCH` is the canonical pattern for "missing link" detection in Neo4j without write.

### Decision: Quick actions are audit-only (no Event write)

**Choice.** Three `POST /api/events/recommendations/{event_id}/{dismiss|snooze|escalate}` endpoints each call `audit_service.record_critical_change()` and return 200 with the audit row id. No Cypher write against `Event`. `snooze_until` lives only in audit context.

**Rationale.** Aligns with the business rule "events MUST NOT be silently closed without operator review". The audit row is the operator's recorded decision; lifecycle changes happen via existing event endpoints. Mirrors Slice 1's "no-mutation guarantee" pattern.

### Decision: Settings mirror `EventPruneSettings`

| Aspect | Choice | Tradeoff | Decision |
|---|---|---|---|
| Config class | `StaleEventReminderSettings(BaseModel)` with `enabled`, `age_hours`, `refresh_window_hours`, `snooze_ttl_hours` | Same `BaseModel` + `from_env()` shape | Mirror `EventPruneSettings` |
| Kill-switch | `STALE_EVENT_REMINDER_ENABLED` default `true` | Operators expect `true` default for a feature; `false` returns empty list and 503s quick actions | Default `true` |
| Singleton accessor | `_stale_event_reminder_settings` cached lazy | Same pattern as `_event_prune_settings` | Use module-level cached accessor |
| Env parsing | Same safe-fallback helpers (`_int`, `_bool`) | Mirrors `EventPruneSettings.from_env()` exactly | Reuse pattern |

### Decision: Frontend mount + polling cadence

**Choice.** `StaleRemindersPanel` mounts in `MonitoringConsole` DASHBOARD viewMode directly below the KPI cards grid (`MonitoringConsole.tsx` ~line 1336). Polled at 60s via `useStaleEventRemindersQuery` to balance freshness against Neo4j read load.

**Rationale.** 60s is consistent with the 60s advisory heartbeat for the existing `systemStatusHistory` and is half the 120s default for `useActiveEventsQuery` — appropriate because stale reminders change on a slower cadence than active events. Inline (not portal/absolute) so it scrolls with the dashboard and doesn't overlap the geo view Live Status panel.

### Decision: Quick action UX uses confirm modal

**Choice.** Each quick action opens a confirm modal with the event summary + reason text before posting. Mutation hooks call `queryClient.invalidateQueries({ queryKey: queryKeys.staleReminders() })` on success.

**Rationale.** Matches the existing modal pattern in `MonitoringConsole` (close flow, take case) and ensures the operator reads "advisory only — does not close the event" before clicking.

## PR Split (work-unit-commits, ≤400 lines each)

Per session preflight (`ask-on-risk` delivery strategy, 400-line review budget), the implementation is split into **two chained PRs**. The orchestrator must reject any apply run that ships both PRs in a single branch.

| PR | Slice | Work units (commits) | Approx. changed lines |
|---|---|---|---|
| **PR1 — backend** | Service + router + config + audit emissions + tests | (1) `feat(events): add StaleEventReminderSettings + from_env()`, (2) `feat(audit): register STALE_EVENT_REMINDER_* event_type keys`, (3) `feat(events): add read-only stale-event recommendation service`, (4) `feat(events): add /events/recommendations router + audit quick actions`, (5) `test(events): cover detection reasons, kill-switch, no-mutation, audit shape` | ≤400 |
| **PR2 — frontend** | Panel + hook + query key + API wrappers + MonitoringConsole mount + tests | (1) `feat(console): add stale-reminder query keys + api wrappers`, (2) `feat(console): add useStaleEventRemindersQuery + mutation hooks`, (3) `feat(console): add StaleRemindersPanel with quick-action confirm modals`, (4) `feat(console): mount StaleRemindersPanel in MonitoringConsole + invalidate on action`, (5) `test(console): cover panel render, action buttons, disabled states` | ≤400 |

**PR relationship.** PR2 targets the branch created by PR1. Rebase PR2 on PR1's tip before opening — the diff against `main` must stay isolated. The frontend test for "API returns 503 on kill-switch off" stubs the response and does NOT depend on backend code being live.

## File Changes

### PR1 — Backend (≤400 lines)

| File | Action | Description |
|---|---|---|
| `backend/services/stale_event_reminders.py` | Create | Frozen dataclasses (`StaleEventRecommendation`, `StaleEventDetection`), `READ_ONLY_DETECTION_QUERY` with `OPTIONAL MATCH`, `RECOMMENDATION_SCHEMA_VERSION = "stale-event-reminder-recommendation.v1"`, `build_stale_event_recommendations()`, `recommendation_to_json_dict()`, `recommendation_to_markdown()`, `_open_read_session` + `_execute_read_query` mirroring `legacy_event_discriminator_audit.py`. |
| `backend/routers/event_recommendations.py` | Create | `APIRouter(prefix="/events/recommendations", tags=["Events"])`. `GET ""` returns paginated recommendations (gated `EVENT_VIEW`); `POST "/{event_id}/dismiss"`, `/snooze`, `/escalate` each call `record_critical_change()` and return 200 with audit row id, or 503 when kill-switch off. |
| `backend/config.py` | Modify | Add `StaleEventReminderSettings(BaseModel)` + `from_env()` classmethod + module-level cached `_stale_event_reminder_settings` accessor + `get_stale_event_reminder_settings()` public helper. Insert after `EventPruneSettings` block. |
| `backend/main.py` | Modify | `app.include_router(event_recommendations.router, prefix="/api")` (single line near line 373). |
| `backend/services/audit_service.py` | Modify | Add `"event_id"`, `"reason_code"`, `"snooze_until"` to `AUDIT_CONTEXT_ALLOWED_KEYS` (allow-listed keys for the new quick-action audit rows). |
| `backend/tests/test_stale_event_reminders.py` | Create | Unit tests for classifier, three reason codes, schema version, Markdown/JSON parity, no-mutation guarantee (assert Cypher uses `READ_ACCESS` and contains no `MERGE`/`SET`/`DELETE`), kill-switch off path, audit context shape. |
| `backend/tests/test_audit_router.py` | Modify | Add three scenarios: dismiss/snooze/escalate audit rows include the new context keys and never contain `authorization`/`cookie`/`token`/`body`; kill-switch off returns 503 and writes no audit row. |
| `.env.example` | Modify | Document `STALE_EVENT_REMINDER_ENABLED=true`, `STALE_EVENT_REMINDER_AGE_HOURS=24`, `STALE_EVENT_REMINDER_REFRESH_WINDOW_HOURS=6`, `STALE_EVENT_REMINDER_SNOOZE_TTL_HOURS=24` in the section after the prune settings. |

### PR2 — Frontend (≤400 lines)

| File | Action | Description |
|---|---|---|
| `frontend/services/queryKeys.ts` | Modify | Add `staleReminders: () => ["events", "stale-reminders"] as const` and three mutation keys (`staleReminderAction: (id, action) => [...]`). |
| `frontend/services/queryResources.ts` | Modify | Add `fetchStaleEventReminders({ signal, limit? })`, `dismissStaleReminder(id, reason?)`, `snoozeStaleReminder(id, reason?)`, `escalateStaleReminder(id, reason?)` — all thin wrappers around `api.get/post`. |
| `frontend/hooks/queries/useStaleEventRemindersQuery.ts` | Create | `useStaleEventRemindersQuery` with `refetchInterval: 60_000`, gated on `EVENT_VIEW` permission. |
| `frontend/hooks/queries/useStaleReminderMutations.ts` | Create | `useStaleReminderMutations()` returns `{ dismiss, snooze, escalate }`. Each `useMutation` invalidates `queryKeys.staleReminders()` and returns the audit row id. |
| `frontend/components/StaleRemindersPanel.tsx` | Create | Collapsible card (`useState` for open/closed). Renders list of recommendations with `reason_code` badge + age + CI/MetricDef chips. Each row has three buttons (`Dismiss`, `Snooze 24h`, `Escalate`) opening a confirm modal. Empty state when kill-switch off. Loading skeleton when `isLoading`. |
| `frontend/components/__tests__/StaleRemindersPanel.test.tsx` | Create | Vitest + RTL: renders empty state when no rows, renders reason badge per reason code, opens confirm modal on action click, calls mutation on confirm, disabled state when permission missing. |
| `frontend/components/MonitoringConsole.tsx` | Modify | Import `StaleRemindersPanel` + `useStaleEventRemindersQuery`; mount panel directly below KPI grid (around line 1336, inside the DASHBOARD branch of `viewMode`). Adds `canViewEventDetail` guard so the panel is hidden when `EVENT_VIEW` is missing. |

## Data Flow

```
[Operator Monitoring Console]
    │
    ▼ useStaleEventRemindersQuery (60s poll)
[GET /api/events/recommendations]
    │
    ▼ Router (events.py-style EVENT_VIEW check)
[event_recommendations.router::get_recommendations]
    │
    ▼ StaleEventReminderSettings.from_env() (kill-switch + thresholds)
[build_stale_event_recommendations(driver, settings)]
    │
    ▼ READ_ONLY_DETECTION_QUERY (READ_ACCESS session)
    │    OPTIONAL MATCH on :HAS_EVENT / :TRIGGERED_BY
    │    Filter: status IN [OPEN,ACK], event_type = COLLECTION_FAILURE,
    │            failure_family = SNMP_NO_RESPONSE
    │    Compute: age_hours, last_seen, refresh_status, reason_code
    │    LIMIT $limit
    ▼
[StaleEventRecommendation list] → JSON (schema_version: stale-event-reminder-recommendation.v1)
    │
    ▼
[StaleRemindersPanel renders rows]

[Operator clicks "Snooze" → confirm modal]
    │
    ▼ useStaleReminderMutations.snooze
[POST /api/events/recommendations/{id}/snooze]
    │
    ▼ Router validates EVENT_VIEW + kill-switch on
[audit_service.record_critical_change(event_type=STALE_EVENT_REMINDER_SNOOZE, context={event_id, reason_code, snooze_until})]
    │
    ▼
[AuditEvent row in Postgres; Event untouched]
    │
    ▼ queryClient.invalidateQueries(staleReminders)
[Panel refetches; row still in list until operator closes via lifecycle endpoint]
```

## Interfaces / Contracts

### Backend — Cypher (READ_ONLY_DETECTION_QUERY)

```cypher
MATCH (e:Event)
WHERE e.status IN ['OPEN', 'ACK']
  AND e.event_type = 'COLLECTION_FAILURE'
  AND e.failure_family = 'SNMP_NO_RESPONSE'
OPTIONAL MATCH (ci:CI)-[:HAS_EVENT]->(e)
OPTIONAL MATCH (md:MetricDef)-[:TRIGGERED_BY]->(e)
WITH e, ci, md,
     duration({hours: $age_hours}).seconds AS age_threshold_s,
     duration({hours: $refresh_window_hours}).seconds AS refresh_window_s,
     coalesce(e.last_seen, e.created_at) AS reference_ts,
     timestamp() AS now_ts
WITH e, ci, md, age_threshold_s, refresh_window_s, reference_ts, now_ts,
     (now_ts.epochSeconds - reference_ts.epochSeconds) AS age_seconds
RETURN
  coalesce(e.id, elementId(e)) AS event_id,
  e.title AS title,
  e.severity AS severity,
  e.status AS status,
  ci.id AS ci_id,
  ci.name AS ci_name,
  md.id AS metricdef_id,
  md.name AS metricdef_name,
  age_seconds / 3600.0 AS age_hours,
  e.last_seen AS last_seen,
  CASE
    WHEN ci IS NULL OR md IS NULL THEN 'link_missing'
    WHEN age_seconds > age_threshold_s * 3600 THEN 'older_than_threshold'
    WHEN e.last_seen IS NOT NULL AND (now_ts.epochSeconds - e.last_seen.epochSeconds) > refresh_window_s THEN 'no_refresh_in_window'
    ELSE NULL
  END AS reason_code,
  CASE
    WHEN ci IS NULL OR md IS NULL THEN 'no_link'
    WHEN e.last_seen IS NULL THEN 'never_refreshed'
    WHEN (now_ts.epochSeconds - e.last_seen.epochSeconds) > refresh_window_s THEN 'stale_refresh'
    ELSE 'fresh'
  END AS refresh_status,
  ['dismiss', 'snooze', 'escalate'] AS quick_actions
ORDER BY age_seconds DESC
LIMIT $limit
```

### Backend — JSON response shape (`GET /api/events/recommendations`)

```json
{
  "schema_version": "stale-event-reminder-recommendation.v1",
  "generated_at": "2026-08-30T12:00:00Z",
  "settings": {
    "enabled": true,
    "age_hours": 24,
    "refresh_window_hours": 6,
    "snooze_ttl_hours": 24
  },
  "rows": [
    {
      "event_id": "evt-123",
      "title": "SNMP no-response on core-rtr-01",
      "severity": "CRITICAL",
      "status": "OPEN",
      "ci_id": "ci-core-rtr-01",
      "ci_name": "Core Router 01",
      "metricdef_id": "md-snmp-uptime",
      "metricdef_name": "SNMP Uptime",
      "age_hours": 28.4,
      "last_seen": "2026-08-29T07:36:00Z",
      "refresh_status": "stale_refresh",
      "reason_code": "no_refresh_in_window",
      "quick_actions": ["dismiss", "snooze", "escalate"]
    }
  ],
  "total": 1
}
```

### Backend — Quick-action response shape (200 OK)

```json
{
  "status": "recorded",
  "audit_event_id": 12345,
  "event_type": "STALE_EVENT_REMINDER_SNOOZE",
  "context": {
    "event_id": "evt-123",
    "reason_code": "no_refresh_in_window",
    "snooze_until": "2026-08-31T12:00:00Z"
  }
}
```

503 response when `STALE_EVENT_REMINDER_ENABLED=false`:

```json
{
  "detail": "Stale event reminders are disabled (STALE_EVENT_REMINDER_ENABLED=false)"
}
```

### Backend — Config (`backend/config.py`)

```python
STALE_EVENT_REMINDER_DEFAULT_AGE_HOURS = 24
STALE_EVENT_REMINDER_DEFAULT_REFRESH_WINDOW_HOURS = 6
STALE_EVENT_REMINDER_DEFAULT_SNOOZE_TTL_HOURS = 24

class StaleEventReminderSettings(BaseModel):
    enabled: bool = True
    age_hours: int = Field(default=STALE_EVENT_REMINDER_DEFAULT_AGE_HOURS, ge=1)
    refresh_window_hours: int = Field(default=STALE_EVENT_REMINDER_DEFAULT_REFRESH_WINDOW_HOURS, ge=1)
    snooze_ttl_hours: int = Field(default=STALE_EVENT_REMINDER_DEFAULT_SNOOZE_TTL_HOURS, ge=1)

    @classmethod
    def from_env(cls) -> StaleEventReminderSettings: ...

_stale_event_reminder_settings: StaleEventReminderSettings | None = None

def get_stale_event_reminder_settings() -> StaleEventReminderSettings:
    global _stale_event_reminder_settings
    if _stale_event_reminder_settings is None:
        _stale_event_reminder_settings = StaleEventReminderSettings.from_env()
    return _stale_event_reminder_settings
```

### Frontend — TypeScript contracts

```typescript
export type StaleReasonCode = "older_than_threshold" | "no_refresh_in_window" | "link_missing";
export type StaleRefreshStatus = "no_link" | "never_refreshed" | "stale_refresh" | "fresh";

export interface StaleEventReminderRow {
  event_id: string;
  title: string;
  severity: "CRITICAL" | "WARNING" | "INFO";
  status: "OPEN" | "ACK";
  ci_id: string | null;
  ci_name: string | null;
  metricdef_id: string | null;
  metricdef_name: string | null;
  age_hours: number;
  last_seen: string | null;
  refresh_status: StaleRefreshStatus;
  reason_code: StaleReasonCode;
  quick_actions: ("dismiss" | "snooze" | "escalate")[];
}

export interface StaleEventRemindersResponse {
  schema_version: "stale-event-reminder-recommendation.v1";
  generated_at: string;
  settings: { enabled: boolean; age_hours: number; refresh_window_hours: number; snooze_ttl_hours: number };
  rows: StaleEventReminderRow[];
  total: number;
}
```

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit (backend) | Classifier (3 reason codes), threshold math, schema version constant, Markdown/JSON parity, `from_mapping` round-trip, kill-switch off returns empty, no mutation guarantee (Cypher contains only `MATCH`/`OPTIONAL MATCH`/`RETURN`, never `MERGE`/`SET`/`DELETE`), audit context shape (3 keys present, no sensitive keys), `from_env` defaults and overrides | `pytest` in `backend/tests/test_stale_event_reminders.py`. Mirror `test_legacy_event_discriminator_audit.py` style: pure-function tests with mapping fixtures. |
| Integration (backend) | Router auth (`EVENT_VIEW` required, 403 without), router kill-switch off (503, no audit row), router each quick action persists audit row, `audit_service.record_critical_change()` is called with the right `event_type` and allow-listed context | `pytest` + `TestClient(app)` in `test_audit_router.py` additions. Reuse the `audit_db` fixture from `test_audit_router.py`. |
| Unit (frontend) | `StaleRemindersPanel` renders empty state, renders one row per reason code badge, opens confirm modal on action click, calls mutation on confirm, hides when `EVENT_VIEW` is missing, shows loading skeleton | Vitest + RTL in `frontend/components/__tests__/StaleRemindersPanel.test.tsx`. Use MSW to stub `fetchStaleEventReminders`. |
| Integration (frontend) | `useStaleEventRemindersQuery` polls every 60s, mutations invalidate the query key, 503 from kill-switch off surfaces as `ApiError` | Vitest + RTL in `frontend/hooks/queries/__tests__/useStaleEventRemindersQuery.test.tsx` (or co-located). |
| E2E | Operator sees panel in Monitoring Console, opens confirm modal on Snooze, audit row appears in Audit Log UI under `STALE_EVENT_REMINDER_SNOOZE` | Playwright in `frontend/playwright/e2e/stale-reminders.spec.ts`. Optional in first slice; document manual evidence if the harness can't be set up. |

Run commands: `cd backend && python -m pytest backend/tests/test_stale_event_reminders.py backend/tests/test_audit_router.py` and `cd frontend && corepack pnpm test:run -- --run StaleRemindersPanel`.

## Threat Matrix

The change does NOT touch routing (HTTP), shell commands, subprocesses, VCS/PR automation, executable-file classification, or process integration. The literal boundary rows from `references/threat-matrix.md` are not applicable. Instead, this change introduces a custom applicability matrix for the actual surface it touches (read-only Cypher + audit-emitting quick actions). Every applicable row below MUST propagate to `tasks.md` and the corresponding RED tests as design requirements.

| Boundary | Minimum adversarial cases | Applicability | Design response | Planned RED tests |
|---|---|---|---|---|
| Detection Cypher scan size | Unbounded `MATCH (e:Event)` returning millions of rows; missing `(status, event_type, failure_family)` index; limit unset | Applicable | Hard `LIMIT $limit` (default 100, max 500); required `(status, event_type, failure_family)` predicate; bounded Cypher params | RED test: handler accepts `limit=0` → 422; `limit>500` → 422; fixture with 10k Event rows returns ≤limit |
| Accidental Event mutation from quick-action path | `MERGE`/`SET`/`DELETE` on `:Event` from any code path this change introduces | Applicable | Static check: Cypher string contains only `MATCH`/`OPTIONAL MATCH`/`RETURN`; router module imports no `event_service` mutators (`ack_event`, `close_event`, `prune_recovered_events`, `add_event_comment`) | RED test: parse `_CYPHERS` module attribute and assert forbidden tokens absent; import audit on router module |
| Snooze-TTL bypass | Snooze with negative or zero `snooze_ttl_hours`; snooze persisted as durable Event property | Applicable | `snooze_until` is computed in handler from `STALE_EVENT_REMINDER_SNOOZE_TTL_HOURS`, NEVER read from request body; stored in audit context only (not on Event) | RED test: snooze handler ignores request body `snooze_until`; `snooze_until` value equals `now + ttl_hours`; Event properties unchanged after snooze |
| Kill-switch off path | Recommendations still served when `enabled=false`; quick actions still write audit rows when `enabled=false` | Applicable | Router short-circuits before Cypher when `settings.enabled is False`; returns empty list (200) and 503 (quick actions); kill-switch is checked BEFORE audit emission | RED test: `enabled=false` → GET returns `{"rows": []}`; POST returns 503; audit table row count unchanged |
| Operator misinterprets advisory as auto-close | UI wording suggests event will close; audit row ambiguous | Applicable (operator risk) | Panel header reads "Advisory only — does not close events"; each row tooltip explains `reason_code`; audit row `outcome=INFO` and `reason="advisory_only"` so Audit Log UI labels it clearly | RED test: panel copy contains "advisory only"; audit row `outcome == "INFO"`; `reason` starts with "advisory" |
| Documentation-like paths | `.env.example`, executable Markdown | N/A — `.env.example` is a config reference, not executable; no `.sh`/`.md`/CMake file changes | None | None |
| Git/PR commands | None | N/A — design does not introduce shell or git automation | None | None |

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Detection query scans too many rows | Medium | Hard `LIMIT $limit`; `(status, event_type, failure_family)` predicate; env kill-switch. RED test enforces limit. |
| Operator mistakes reminder for auto-close | Medium | UI copy + audit wording say "advisory only"; mutation impossible by static check; reuse Slice 1 wording. |
| Snooze lost on restart / sensitive context leaks | Low | In-memory TTL (documented; durable snooze deferred); `sanitize_context` + 3 allow-listed keys (`event_id`, `reason_code`, `snooze_until`) only. RED test asserts no `token`/`cookie`/`authorization`/`body` keys. |
| Spec drift with legacy-event-backfill sibling | Low | Same renderer shape + distinct `v1` schema id per feature. |
| Review budget exceeded (PR1 or PR2 > 400 lines) | Medium | Chained PR split (PR1 backend, PR2 frontend); per-PR test commands in tasks.md; orchestrator rejects un-split apply runs. |
| Audit allow-list pollutes other call sites | Low | New keys (`event_id`, `reason_code`, `snooze_until`) are scoped to this surface; existing call sites in `audit_service.py` use their existing key set. RED test asserts no leakage. |

## Migration / Rollout

No data migration required. No schema change in Postgres or Neo4j.

**Rollout.**

1. Land PR1 (backend) first. Smoke: `GET /api/events/recommendations` returns empty list on a fresh install; toggle `STALE_EVENT_REMINDER_ENABLED=false` and confirm 503 on quick actions.
2. Land PR2 (frontend) rebased on PR1. Smoke: panel renders empty state; force-create one stale event in dev, confirm it appears within 60s; click Snooze and confirm audit row lands in `/api/audit/events?event_type=STALE_EVENT_REMINDER_SNOOZE`.

**Rollback.**

- Code revert of PR1 + PR2 is sufficient. No DB changes. No audit rows require cleanup (audit retention is 90 days and rows are informational).
- For in-prod disable without redeploy: set `STALE_EVENT_REMINDER_ENABLED=false` → empty recommendations list + 503 on quick actions.

## Open Questions

- [ ] Should the panel auto-collapse after the first successful action, or stay open until the operator explicitly closes it? (Default: stay open; user can collapse via header toggle.)
- [ ] Should `escalate` trigger `notify_critical_event_escalation` like the existing close path does for `CRITICAL` events? **Default in this design: NO** — escalation is audit-only, no ITSM side effects in the first slice. Re-evaluate after operator feedback.
- [ ] Should `snooze_until` be persisted on the Event node in a follow-up slice for cross-restart continuity? **Default: deferred** to a later change; first slice is in-memory TTL only.

## Key Learnings

1. Read-only advisory surfaces can be retro-fitted onto existing audit infrastructure (`record_critical_change` + allow-listed context keys) without introducing a new persistence layer.
2. Schema-versioned payloads (`*-recommendation.v1`) let two related advisory features (legacy backfill + stale reminders) coexist without breaking each other's downstream consumers.
3. `OPTIONAL MATCH` is the canonical Cypher idiom for "missing-link" detection — using it avoids writing null-projection logic in Python.
4. Kill-switch by env var (`STALE_EVENT_REMINDER_ENABLED`) is a low-cost operational safety net: it returns empty/503 without code change, and re-enables on restart.
5. Chained PRs (PR1 backend ≤400 + PR2 frontend ≤400) protect reviewer focus — each slice has its own autonomous scope, verification, and rollback.
