# Event Root Affected Exposure Specification

## Purpose

Define the public surface that exposes a ROOT Event's affected-CI set so the operator dashboard, drill-down, and downstream consumers (AI chat context, audit, smoke tests) can reason about blast radius without re-deriving it from raw N+1 PROPAGATED child rows. This capability is the P2 follow-up to `event-write-time-correlation`: P0 already writes `affected_ci_ids` and `affected_ci_count` onto ROOT `Event` nodes (`backend/engines/snmp_worker.py:315-353`); this spec exposes those fields through the API and reshapes the operator view around them. The writer path is untouched.

## Requirements

### REQ-001: Additive `affected_ci_ids` / `affected_count` on Event Summary Surface

The `EventFeedSummary` Pydantic model SHALL expose two additive fields:
- `affected_ci_ids: list[str] | None = None`
- `affected_count: int | None = None`

`EventDetailEvent` inherits both fields for free. The fields SHALL be omitted from the JSON payload when the ROOT has no dependents (`affected_ci_ids` empty, null, or `affected_count = 0`) to keep the historical contract for legacy ROOTs.

#### Scenario: ROOT with dependents exposes both fields

- GIVEN a ROOT Event has `affected_ci_ids = ["ci-A", "ci-B", "ci-C"]` and `affected_ci_count = 3` in Neo4j
- WHEN `GET /api/events?status=CONSOLE` returns the event
- THEN the JSON object contains `affected_ci_ids: ["ci-A","ci-B","ci-C"]` and `affected_count: 3`

#### Scenario: ROOT without dependents omits fields

- GIVEN a ROOT Event has no dependents (empty or null `affected_ci_ids`)
- WHEN `GET /api/events?status=CONSOLE` returns the event
- THEN neither `affected_ci_ids` nor `affected_count` is present in the JSON payload

### REQ-002: `_public_event_summary` Allowlist Admits New Fields

The `allowed_keys` set in `backend/services/event_service.py:_public_event_summary` (line 173-198) SHALL include `affected_ci_ids` and `affected_count` so the serialization layer forwards them. The `propagated` derived flag (line 205-206) SHALL stay unchanged.

#### Scenario: Allowlist includes the two new keys

- GIVEN a populated summary dict containing both new keys plus a `null` value
- WHEN `_public_event_summary` is called
- THEN the returned dict includes both non-null keys and omits the `null` one

### REQ-003: `GET /api/events` Honors `include_children` Query Parameter

`GET /api/events?status=CONSOLE&include_children=true|false` SHALL accept the new boolean parameter. Default SHALL be `false` (roots only). When `false`, the Cypher SHALL add `coalesce(e.correlation_type, 'ROOT') = 'ROOT'` to the WHERE clause. Result ordering SHALL be preserved (`ORDER BY e.created_at DESC`). The parameter SHALL be accepted as `?include_children=true|false` (FastAPI `Query(False)`), with missing/empty treated as `false`.

#### Scenario: Default call returns roots only

- GIVEN the database has one ROOT Event plus one legacy PROPAGATED Event
- WHEN the client calls `GET /api/events?status=CONSOLE` without `include_children`
- THEN the response contains only the ROOT Event

#### Scenario: Explicit `include_children=true` returns full set

- GIVEN the same setup as above
- WHEN the client calls `GET /api/events?status=CONSOLE&include_children=true`
- THEN the response contains both the ROOT and the legacy PROPAGATED Event

#### Scenario: Explicit `include_children=false` is identical to default

- GIVEN the same setup as above
- WHEN the client calls `GET /api/events?status=CONSOLE&include_children=false`
- THEN the response contains only the ROOT Event

### REQ-004: New `GET /api/events/{id}/affected` Drill-Down Endpoint

A new route `GET /api/events/{id}/affected` SHALL return a list of affected CI entries `{ci_id, ci_name, ci_hostname, ci_location_name}` for the given Event id. The route SHALL require the same `UserPermission.EVENT_VIEW` guard as the existing `GET /api/events/{id}` (`backend/routers/events.py:92`). When the Event id does not exist or is not a ROOT Event, the route SHALL respond with `404 Not Found` and a structured `{"detail": "Event not found: <id>"}` payload consistent with `_raise_event_not_found`.

#### Scenario: Existing ROOT returns drill-down

- GIVEN a ROOT Event with `affected_ci_ids = ["ci-A","ci-B"]`
- WHEN the operator calls `GET /api/events/{root_id}/affected`
- THEN the response is a 200 with a list of two entries, each containing at least `{ci_id, ci_name, status}` and ordered as in `affected_ci_ids`

#### Scenario: Unknown Event id returns 404

- GIVEN no Event with the supplied id exists
- WHEN the operator calls `GET /api/events/unknown-id/affected`
- THEN the response is a 404 with detail `"Event not found: unknown-id"`

#### Scenario: Missing `EVENT_VIEW` returns 403

- GIVEN the authenticated user lacks `EVENT_VIEW`
- WHEN the operator calls `GET /api/events/{root_id}/affected`
- THEN the response is a 403 with detail `"Not authorized to view events"`

### REQ-005: Monitoring KPI Counts ROOTs Only and Reports Affected CI Count

The Monitoring Console KPI cards (`frontend/components/MonitoringConsole.tsx:1099-1101`) SHALL filter the underlying event set to ROOT events only using the backend-supplied `correlation_type === "ROOT"` discriminator. The total root count SHALL be rendered with a sub-label `"affecting N CIs"` where `N = sum(event.affected_count)` across the root events. When `affected_count` is missing on every event the sub-label SHALL be hidden.

#### Scenario: KPI counts only ROOTs

- GIVEN the polled feed contains 2 ROOT events and 1 legacy PROPAGATED event
- WHEN the Monitoring Console renders KPI cards
- THEN `kpiCritical`, `kpiWarning`, and `kpiAck` are computed over the 2 ROOT events only

#### Scenario: Sub-label reports total affected CIs

- GIVEN two root events with `affected_count = 3` and `affected_count = 2`
- WHEN the Monitoring Console renders the "Total" KPI
- THEN the sub-label reads `"affecting 5 CIs"`

### REQ-006: React Query Key Discriminates `include_children`

The query key factory in `frontend/services/queryKeys.ts` SHALL produce a distinct cache entry per `includeChildren` boolean so concurrent polling with different values SHALL NOT cross-contaminate. `useActiveEventsQuery` SHALL call the factory with `includeChildren: false` by default.

#### Scenario: Distinct query keys per mode

- GIVEN `useActiveEventsQuery` mounts with `includeChildren = false`
- AND another caller simultaneously calls `fetchActiveEvents({ include_children: true })`
- WHEN React Query resolves both
- THEN the cache stores two distinct entries (e.g. `["events", "CONSOLE", { includeChildren: false }]` vs `["events", "CONSOLE", { includeChildren: true }]`) and does not overwrite one with the other

### REQ-007: `useEventCorrelation` Extends Topology Grouping to `CONNECTS_TO`

The `useEventCorrelation` hook (`frontend/hooks/useEventCorrelation.ts:89`) SHALL recognise `CONNECTS_TO` in addition to `DEPENDS_ON | HOSTED_ON` when grouping downstream consumer events under an upstream provider ROOT. The backend-supplied `correlation_type` SHALL remain the authoritative "is root" signal; the hook's topology branch is a client-side safety net.

#### Scenario: `CONNECTS_TO` link suppresses consumer ROOT

- GIVEN a topology link of type `CONNECTS_TO` from CI consumer to CI provider
- AND both CIs have active CRITICAL events
- WHEN the hook groups events
- THEN the consumer event is attached to the provider's `relatedEvents` and flagged `isRoot = false`

### REQ-008: Frontend Type Mirrors Backend Additive Fields

The TypeScript `EventSummary` interface (`frontend/types.ts:274-300`) SHALL declare `affected_ci_ids?: string[]` and `affected_count?: number` as optional fields. `EventDetailEvent` extends `EventSummary` and SHALL inherit both.

#### Scenario: TypeScript compilation accepts new fields

- GIVEN a payload from `fetchActiveEvents`
- WHEN the consumer destructures `event.affected_ci_ids` and `event.affected_count`
- THEN the TypeScript compiler accepts the access without `as any` casts

### REQ-009: Backward Compatibility for Audit, AI Chat, and Legacy Test Consumers

Consumers that today rely on the raw N+1 set from `GET /api/events` (audit re-ingestion, AI chat context in `backend/services/ai_chat_service.py:422`, internal `get_related_events` at `backend/services/event_service.py:1010`, frontend smoke tests in `MonitoringConsole.smoke.test.tsx` and `EventDetailModal.acceptance.test.tsx`) SHALL preserve their prior behaviour by either:
- passing `include_children=true` explicitly (backend audit/AI paths), or
- updating test mocks to mock root-only responses and asserting the new default.

Any consumer migrated MUST be flagged in the changelog under "BREAKING" with the mitigation listed.

#### Scenario: AI chat context opts in

- GIVEN the AI chat context builder needs the raw N+1 set today
- WHEN the P2 code lands
- THEN `services/ai_chat_service.py:422` SHALL call `get_events(status, include_children=True)` explicitly

#### Scenario: Frontend smoke test mocks root-only responses

- GIVEN `MonitoringConsole.smoke.test.tsx` mocks `/events?status=CONSOLE` with raw rows
- WHEN the P2 code lands
- THEN the mock SHALL either include `?include_children=true` in the asserted URL or replace rows with root-only payloads

## Scenario Matrix

| ID | Surface | WHEN | THEN |
|---|---|---|---|
| SCN-001 | `GET /api/events` default | WHEN the client calls `GET /api/events?status=CONSOLE` without `include_children` | THEN only ROOT events are returned |
| SCN-002 | `GET /api/events?include_children=true` | WHEN the client passes `include_children=true` | THEN the response contains the raw set (ROOT + PROPAGATED) |
| SCN-003 | `GET /api/events?include_children=false` | WHEN the client passes `include_children=false` explicitly | THEN only ROOT events are returned (identical to SCN-001) |
| SCN-004 | `GET /api/events/{root_id}/affected` | WHEN the operator drills into a ROOT with `affected_ci_ids=["ci-A","ci-B"]` | THEN a 200 returns entries with at least `{ci_id, ci_name, status}` |
| SCN-005 | `GET /api/events/{unknown}/affected` | WHEN the operator supplies an unknown id | THEN a 404 with `{"detail":"Event not found: <id>"}` |
| SCN-006 | Field presence | WHEN a ROOT has dependents | THEN `affected_ci_ids` and `affected_count` are present and non-null |
| SCN-007 | Query key isolation | WHEN `useActiveEventsQuery` coexists with `include_children=true` callers | THEN both cache entries coexist without overwriting |
| SCN-008 | KPI root filter + sub-label | WHEN the Monitoring Console renders KPI cards | THEN only ROOT events are counted and the total KPI shows `"affecting N CIs"` |
| SCN-009 | `CONNECTS_TO` topology grouping | WHEN a `CONNECTS_TO` link joins provider and consumer CIs with active events | THEN the consumer event is attached to the provider ROOT |
| SCN-010 | Empty affected set | WHEN a ROOT has no dependents | THEN `affected_count` is omitted and no drill-down entry is exposed |

## Out of Scope

- **P1** legacy in-process collector parity and changes to its persisted child-Event behavior.
- **P3** leased queue writer parity, topology backfill, AP parent synthesis, or relationship remediation.
- WebSocket push for ROOT changes; polling cadence stays at 10 s.
- Re-platforming the `/architecture` route's `SystemDashboard`; only `MonitoringConsole` reads `affected_ci_ids` for KPI purposes.
- Modifying `_update_propagated_root_events` write semantics in `backend/engines/snmp_worker.py` (P0 contract).

## Open Questions

- Whether `affected_ci_ids` should also be exposed on non-ROOT events (e.g. legacy PROPAGATED rows) for debugging. Current decision: no; consumers must opt into `include_children=true` and inspect via the existing detail endpoint if needed.