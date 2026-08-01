# Delta for Event Root Affected Exposure

## ADDED Requirements

### Requirement: REQ-001 — Additive `affected_ci_ids` / `affected_count` on Event Summary Surface

The `EventFeedSummary` Pydantic model SHALL expose two additive fields: `affected_ci_ids: list[str] | None = None` and `affected_count: int | None = None`. `EventDetailEvent` inherits both fields. The fields SHALL be omitted from the JSON payload when the ROOT has no dependents (`affected_ci_ids` empty, null, or `affected_count = 0`).

#### Scenario: ROOT with dependents exposes both fields

- GIVEN a ROOT Event has `affected_ci_ids = ["ci-A","ci-B","ci-C"]` and `affected_ci_count = 3` in Neo4j
- WHEN `GET /api/events?status=CONSOLE` returns the event
- THEN the JSON object contains `affected_ci_ids: ["ci-A","ci-B","ci-C"]` and `affected_count: 3`

#### Scenario: ROOT without dependents omits fields

- GIVEN a ROOT Event has no dependents (empty or null `affected_ci_ids`)
- WHEN `GET /api/events?status=CONSOLE` returns the event
- THEN neither `affected_ci_ids` nor `affected_count` is present in the JSON payload

### Requirement: REQ-002 — `_public_event_summary` Allowlist Admits New Fields

The `allowed_keys` set in `backend/services/event_service.py:_public_event_summary` SHALL include `affected_ci_ids` and `affected_count`. The `propagated` derived flag SHALL stay unchanged.

#### Scenario: Allowlist includes the two new keys

- GIVEN a populated summary dict containing both new keys plus a `null` value
- WHEN `_public_event_summary` is called
- THEN the returned dict includes both non-null keys and omits the `null` one

### Requirement: REQ-003 — `GET /api/events` Honors `include_children`

`GET /api/events` SHALL accept `?include_children=true|false` (FastAPI `Query(False)`). Default SHALL be `false`. When `false`, the Cypher SHALL add `coalesce(e.correlation_type, 'ROOT') = 'ROOT'` to the WHERE clause. Result ordering SHALL be preserved.

#### Scenario: Default call returns roots only

- GIVEN the database has one ROOT Event plus one legacy PROPAGATED Event
- WHEN the client calls `GET /api/events?status=CONSOLE` without `include_children`
- THEN the response contains only the ROOT Event

#### Scenario: Explicit `include_children=true` returns full set

- GIVEN the same setup as the default scenario
- WHEN the client calls `GET /api/events?status=CONSOLE&include_children=true`
- THEN the response contains both the ROOT and the legacy PROPAGATED Event

#### Scenario: Explicit `include_children=false` matches default

- GIVEN the same setup as the default scenario
- WHEN the client calls `GET /api/events?status=CONSOLE&include_children=false`
- THEN the response contains only the ROOT Event

### Requirement: REQ-004 — New `GET /api/events/{id}/affected` Endpoint

A new route `GET /api/events/{id}/affected` SHALL return a list of `{ci_id, ci_name, ci_hostname, ci_location_name}` entries from the ROOT event's `affected_ci_ids`. The route SHALL enforce the same `UserPermission.EVENT_VIEW` guard as `GET /api/events/{id}` (`backend/routers/events.py:92`). Unknown or non-ROOT ids SHALL respond `404` with `{"detail":"Event not found: <id>"}`.

#### Scenario: Existing ROOT returns drill-down

- GIVEN a ROOT Event with `affected_ci_ids = ["ci-A","ci-B"]`
- WHEN the operator calls `GET /api/events/{root_id}/affected`
- THEN the response is a 200 with two entries, each containing at least `{ci_id, ci_name, status}`

#### Scenario: Unknown Event id returns 404

- GIVEN no Event with the supplied id exists
- WHEN the operator calls `GET /api/events/unknown-id/affected`
- THEN the response is a 404 with detail `"Event not found: unknown-id"`

#### Scenario: Missing `EVENT_VIEW` returns 403

- GIVEN the authenticated user lacks `EVENT_VIEW`
- WHEN the operator calls `GET /api/events/{root_id}/affected`
- THEN the response is a 403 with detail `"Not authorized to view events"`

### Requirement: REQ-005 — Monitoring KPI Counts ROOTs Only with Affected Sub-Label

The Monitoring Console KPI cards (`frontend/components/MonitoringConsole.tsx:1099-1101`) SHALL filter to ROOT events only using backend-supplied `correlation_type === "ROOT"`. The total KPI SHALL show a sub-label `"affecting N CIs"` where `N = sum(event.affected_count)` across the roots.

#### Scenario: KPI counts only ROOTs

- GIVEN the polled feed contains 2 ROOT events and 1 legacy PROPAGATED event
- WHEN the Monitoring Console renders KPI cards
- THEN `kpiCritical`, `kpiWarning`, and `kpiAck` are computed over the 2 ROOT events only

#### Scenario: Sub-label reports total affected CIs

- GIVEN two root events with `affected_count = 3` and `affected_count = 2`
- WHEN the Monitoring Console renders the "Total" KPI
- THEN the sub-label reads `"affecting 5 CIs"`

### Requirement: REQ-006 — React Query Key Discriminates `include_children`

`frontend/services/queryKeys.ts` SHALL produce a distinct cache entry per `includeChildren` boolean. `useActiveEventsQuery` SHALL pass `includeChildren: false` by default.

#### Scenario: Distinct query keys per mode

- GIVEN `useActiveEventsQuery` mounts with `includeChildren = false`
- AND another caller invokes `fetchActiveEvents({ include_children: true })`
- WHEN React Query resolves both
- THEN the cache stores two distinct entries and does not overwrite one with the other

### Requirement: REQ-007 — `useEventCorrelation` Extends Topology Grouping to `CONNECTS_TO`

`frontend/hooks/useEventCorrelation.ts:89` SHALL recognise `CONNECTS_TO` in addition to `DEPENDS_ON | HOSTED_ON` when grouping downstream consumer events under an upstream provider ROOT.

#### Scenario: `CONNECTS_TO` link suppresses consumer ROOT

- GIVEN a `CONNECTS_TO` link from consumer to provider
- AND both CIs have active CRITICAL events
- WHEN the hook groups events
- THEN the consumer event is attached to the provider's `relatedEvents` and flagged `isRoot = false`

### Requirement: REQ-008 — Frontend Type Mirrors Backend Additive Fields

The TypeScript `EventSummary` interface (`frontend/types.ts:274-300`) SHALL declare `affected_ci_ids?: string[]` and `affected_count?: number`. `EventDetailEvent` inherits them.

#### Scenario: TypeScript compilation accepts new fields

- GIVEN a payload from `fetchActiveEvents`
- WHEN the consumer destructures `event.affected_ci_ids` and `event.affected_count`
- THEN the TypeScript compiler accepts the access without `as any` casts

### Requirement: REQ-009 — Backward Compatibility for Audit, AI Chat, and Legacy Test Consumers

Audit re-ingestion, `services/ai_chat_service.py:422`, internal `get_related_events` (`backend/services/event_service.py:1010`), and frontend smoke tests SHALL preserve prior behaviour by either passing `include_children=true` explicitly or updating test mocks. Breaking changes SHALL be listed in the changelog under "BREAKING" with mitigation.

#### Scenario: AI chat context opts in

- GIVEN the AI chat context builder needs the raw N+1 set today
- WHEN the P2 code lands
- THEN `services/ai_chat_service.py:422` SHALL call `get_events(status, include_children=True)` explicitly

#### Scenario: Frontend smoke test mocks root-only responses

- GIVEN `MonitoringConsole.smoke.test.tsx` mocks `/events?status=CONSOLE`
- WHEN the P2 code lands
- THEN the mock SHALL include `?include_children=true` in the asserted URL or replace rows with root-only payloads

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

- **P1** legacy in-process collector parity.
- **P3** leased queue writer parity, topology backfill, AP parent synthesis, or relationship remediation.
- WebSocket push for ROOT changes; polling cadence stays at 10 s.
- Re-platforming the `/architecture` route's `SystemDashboard`.
- Modifying `_update_propagated_root_events` write semantics in `backend/engines/snmp_worker.py`.

## Open Questions

- Whether `affected_ci_ids` should also be exposed on non-ROOT events for debugging. Current decision: no; consumers must opt into `include_children=true`.