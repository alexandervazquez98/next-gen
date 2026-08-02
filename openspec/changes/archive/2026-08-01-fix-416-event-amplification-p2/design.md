# Design: fix-416-event-amplification-p2

## Technical Approach

Expose the P0 ROOT annotations already written by `backend/engines/snmp_worker.py:315-353` without changing writer behavior. The API will default to a root-only feed, map Neo4j `affected_ci_count` to public `affected_count`, and add a permission-gated CI drill-down. The Monitoring Console will poll root rows, use backend `correlation_type` for KPI truth, retain `useEventCorrelation` only for stream grouping, and fetch affected CIs on demand.

```text
React poll (include_children=false)
  -> useActiveEventsQuery -> GET /api/events
  -> events router -> event_service.get_events
  -> Cypher root predicate -> _build/_public summary -> Neo4j
Total KPI click -> React Query per ROOT
  -> GET /api/events/{root_id}/affected
  -> EVENT_VIEW guard -> get_affected_siblings
  -> indexed UNWIND affected_ci_ids + MATCH CI -> modal
```

## Architecture Decisions

| ID | Decision | Alternatives | Rationale |
|---|---|---|---|
| AD-1 | `include_children=False` by default (`routers/events.py:50-57`). | `true`; new endpoint. | Operator feed must stop N+1 amplification. `true` remains an explicit compatibility opt-in. |
| AD-2 | Model defaults are `[]`/`0`; JSON omits both when empty/zero. | Always serialize `[]`/`0`; nullable fields. | Stable Python/TS access while preserving legacy payloads. Use a narrow serializer/exclusion rule; do not globally exclude defaults because `ack=False` is existing contract. Null/absent Neo4j fields mean no affected CIs. |
| AD-3 | Backend `correlation_type` is authoritative; `coalesce(e.correlation_type,'ROOT')='ROOT'` treats legacy null/absent rows as roots. Normalize missing public values to `ROOT` so the UI can use `=== 'ROOT'`; the hook is only a safety-net grouping algorithm. | Frontend-derived `isRoot`. | Prevents topology drift from changing KPI counts. |
| AD-4 | Flat `AffectedCI` list: `ci_id`, `ci_name`, `status`, plus optional hostname/location. | Aggregate stats object. | Existing `affected_ci_ids` is a per-CI set; one simple response supports modal grouping and avoids a second statistics contract. |
| AD-5 | Query keys include `{ include_children }` (`queryKeys.ts:14`). | Shared `['events','CONSOLE']`; separate factories. | Prevents root/raw cache cross-contamination and keeps one factory. |
| AD-6 | Preserve AI raw visibility with an explicit local `include_children=True` control at `ai_chat_service.py:422`’s event-list query boundary. | Make AI inherit root-only default. | Current line 422 serializes a custom Neo4j query; it does not call `event_service.get_events`. Do not invent a service call or lose AI location/severity scoping. |
| AD-7 | Update frontend mocks to root-only/default URLs and add explicit affected responses. | Force `include_children=true` in Monitoring. | Tests must prove the new contract; only consumers needing raw rows opt in. |

## Data / Contracts

```python
class EventFeedSummary(BaseModel):
    affected_ci_ids: list[str] = Field(default_factory=list)
    affected_count: int = 0  # mapped from Neo4j affected_ci_count

class AffectedCI(BaseModel):
    ci_id: str
    ci_name: str | None = None
    status: str | None = None
    ci_hostname: str | None = None
    ci_location_name: str | None = None

def get_events(status: str | None = None, include_children: bool = False) -> list[dict]: ...
def get_affected_siblings(event_id: str) -> list[AffectedCI]: ...
```

`get_events` adds the exact WHERE fragment only when false: `coalesce(e.correlation_type, 'ROOT') = 'ROOT'`; status predicates and `ORDER BY e.created_at DESC` remain unchanged. `_public_event_summary` admits both public keys and maps `affected_ci_count`; empty values are removed. `get_affected_siblings` first validates a ROOT with `_raise_event_not_found`, then performs stable indexed `UNWIND` plus `MATCH (ci:CI {id: ci_id})`, returning CI status and preserving `affected_ci_ids` order. Unknown/non-ROOT is `404 Event not found: <id>`; an empty ROOT returns `[]`.

```ts
type ActiveEventOptions = { include_children: boolean };
activeEvents: (opts: ActiveEventOptions) => ['events','CONSOLE',opts];
fetchActiveEvents(opts: ActiveEventOptions & { signal?: AbortSignal }): Promise<EventSummary[]>;
useActiveEventsQuery(include_children = false);
useAffectedCIsQuery(eventId: string, enabled?: boolean);
```

`EventSummary` gains optional `affected_ci_ids`, `affected_count`, and the existing API discriminator `correlation_type`. `useMonitoringConsoleData` passes `false` and remains row-transparent; raw callers pass `true`. KPI code uses `rootRows = events.filter(e => e.correlation_type === 'ROOT')`; the Total card shows `rootRows.length` and hides `affecting N CIs` when no positive count exists. Its click opens a modal using React Query `useQueries` per affected ROOT, rendering flat rows grouped by root.

## File Changes and Forecast

| File | Action | Description | +lines |
|---|---|---|---:|
| `backend/models/core.py` | Modify | Fields plus `AffectedCI` response model. | 10 |
| `backend/services/event_service.py` | Modify | Mapping/allowlist, root filter, drill-down Cypher. | 65 |
| `backend/routers/events.py` | Modify | Query parameter and guarded `/events/{id}/affected` before `/{id}`. | 22 |
| `backend/services/ai_chat_service.py` | Modify | Explicit raw-child compatibility control. | 8 |
| `backend/tests/test_event_service.py` | Create | Serialization, filter, order, empty/404 drill-down. | 115 |
| `backend/tests/test_routers_events.py` | Modify | `event`/`api` route, 403, 404, query matrix. | 85 |
| `frontend/types.ts` | Modify | Additive fields and discriminator. | 5 |
| `frontend/services/queryResources.ts` | Modify | Query parameter and affected fetcher. | 16 |
| `frontend/services/queryKeys.ts` | Modify | Boolean discriminator and affected key. | 6 |
| `frontend/hooks/queries/useActiveEventsQuery.ts` | Modify | Default false propagation. | 8 |
| `frontend/hooks/queries/useMonitoringConsoleData.ts` | Modify | Explicit root-only call. | 2 |
| `frontend/hooks/queries/useAffectedCIsQuery.ts` | Create | React Query drill-down hook. | 18 |
| `frontend/hooks/useEventCorrelation.ts` | Modify | Add `CONNECTS_TO`; preserve output contract. | 2 |
| `frontend/components/MonitoringConsole.tsx` | Modify | Root KPIs, sub-label, modal/useQueries. | 55 |
| `frontend/services/queryResources.test.ts`, `queryKeys.test.ts` | Modify | Fetch URL and cache isolation RED tests. | 30 |
| `frontend/hooks/queries/resourceQueries.test.tsx`, `useEventCorrelation.test.ts` | Modify | Hook propagation and `CONNECTS_TO` RED tests. | 40 |
| `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx` | Modify | Root-only KPI/default URL mock. | 30 |
| `frontend/components/__tests__/EventDetailModal.acceptance.test.tsx` | Modify | Affected endpoint mock and drill-down assertion. | 20 |
| `frontend/components/__tests__/MonitoringConsole.forcedClose.test.tsx` | Modify | Root-only event mock URL. | 10 |
| `frontend/components/MonitoringConsole.test.tsx` | Modify | KPI/sub-label unit coverage. | 20 |
| `frontend/test/e2e/monitoring-event-kpi.spec.ts` | Create | Playwright KPI and modal flow. | 45 |

Forecast: backend 305, frontend production 112, tests 195; total ~612 authored changed lines, below the configured 800-line budget.

## Testing Strategy (strict TDD)

RED tests precede production edits. Backend uses `pytest -m 'event or api'`: model/allowlist mapping, SCN-001..003 filter behavior, ordered affected rows, empty ROOT, unknown/non-ROOT 404, `EVENT_VIEW` 403, and AI raw opt-in. Frontend Vitest covers URL encoding, query-key separation, default propagation, KPI root/count behavior, modal loading/error, and `CONNECTS_TO`. Playwright intercepts root feed plus affected endpoints, clicks Total Active, and asserts the root count, `affecting N CIs`, and drill-down rows.

## Threat Matrix

| Boundary | Applicability | Safe/failure behavior and RED test |
|---|---|---|
| Route precedence/IDs | Applicable | Declare `/events/{id}/affected` before `/{id}`; unknown/non-root 404; router test. |
| Permission | Applicable | Copy `EVENT_VIEW` guard; missing permission 403; router test. |
| Query cache | Applicable | Boolean key isolation; Vitest key test. |
| Idempotency/data | Applicable (read-only) | No writes; repeated drill-down is stable and preserves order; service test. |
| Documentation-like paths; Git selection; commit state; push state; PR commands | N/A | This change executes no files, Git, push, or PR commands; no RED tests. |

## Migration / Rollout

No DB migration and no kill-switch. P0 fields already exist; legacy null/absent correlation is treated as ROOT. `include_children=true` is the compatibility path for AI/raw consumers. Add a `BREAKING` changelog entry with that mitigation. Rollback is a commit revert; no backfill is included.

## Consumer Migration / Open Questions

- `backend/services/ai_chat_service.py:422`: add explicit `include_children=True` to its local event-list query boundary; preserve its existing scope filters.
- Frontend smoke mocks: `MonitoringConsole.smoke.test.tsx` uses root-only `/events?status=CONSOLE` and affected responses; `EventDetailModal.acceptance.test.tsx` adds `/events/{id}/affected`; `MonitoringConsole.forcedClose.test.tsx` replaces raw child rows with ROOT rows.
- No blocking questions. `get_related_events` remains unchanged because it is a CI-scoped query, not `get_events`.
