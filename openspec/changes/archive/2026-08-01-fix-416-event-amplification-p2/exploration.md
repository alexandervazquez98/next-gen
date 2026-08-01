# Exploration: fix-416-event-amplification-p2

## Current State

P0 (`openspec/changes/archive/2026-07-29-fix-416-event-amplification`, merged to
`main`) already does the write-side work: `engines/snmp_worker.py` runs the
two-pass correlation flow and `_update_propagated_root_events`
(`backend/engines/snmp_worker.py:315-353`) writes `affected_ci_ids` /
`affected_ci_count` directly onto ROOT `Event` nodes via a SET clause:

```
SET root.affected_ci_ids = affected_ci_ids,
    root.affected_ci_count = size(affected_ci_ids),
    root.comments = ...
```

The fields exist in Neo4j today, and `test_snmp_worker_correlation.py` +
`test_event_correlation.py` already assert them end-to-end (43 backend hits
across the two-pass path). P2 does not touch any writer code.

What P0 explicitly deferred (per `proposal.md` "Out of Scope" line 15-18):

- "API additive fields and `/monitoring` KPI rendering (P2)"
- "Legacy in-process collector parity (P1)"
- "Queue leased-path correlation parity (P3)"

The current API/UI gap is concrete and reproducible. The event feed pipeline
is:

1. `backend/routers/events.py:50-57` — `GET /api/events?status=CONSOLE` calls
   `event_service.get_events(status)`.
2. `backend/services/event_service.py:958-986` — `get_events` runs a Cypher
   query that matches every Event under a CI **without any filter on
   `correlation_type`**. With P0 active, that means the API still surfaces
   children for cycles where propagation has already been suppressed in the
   graph, because P0 does NOT create child Event nodes (it only annotates the
   ROOT). On cycles where P0 cannot suppress (mixed top-of-stack, recovery
   races), children can still appear as their own rows.
3. `backend/services/event_service.py:173-207` — `_public_event_summary`
   filters the dict through an `allowed_keys` set that already includes
   `propagated_from`, `correlation_type`, `root_cause_ci_id`, but **does NOT
   include `affected_ci_ids` / `affected_ci_count`**. So even if the Cypher
   returned the fields, they would be dropped at serialization time.
4. `frontend/services/queryResources.ts:146-147` — `fetchActiveEvents` calls
   `/events?status=CONSOLE` (no opt-in for children).
5. `frontend/components/MonitoringConsole.tsx:1099-1101` — KPIs are computed
   directly from the raw event array:
   ```ts
   const kpiCritical = openEvents.filter((e) => e.severity === "CRITICAL").length;
   const kpiWarning  = openEvents.filter((e) => e.severity === "WARNING").length;
   const kpiAck      = ackEvents.length;
   ```
   No `isRoot` filter, no use of `affected_ci_count`.
6. `frontend/hooks/useEventCorrelation.ts` already computes an `isRoot` flag
   client-side (intra-CI "dominant" + `DEPENDS_ON | HOSTED_ON` topology). It
   ignores `CONNECTS_TO`. It is a useful safety net, but the source of truth
   for "is this a root" should be the backend-supplied
   `correlation_type === "ROOT"`.

`EventFeedSummary` in `backend/models/core.py:141-165` already declares
`propagated_from`, `correlation_type: Literal["ROOT", "PROPAGATED"]`,
`root_cause_ci_id` — the Pydantic surface for the correlation discriminator
is in place; only `affected_ci_ids` and `affected_count` (note: Pydantic
field, snake_case to match JSON convention) are missing.

## Affected Areas

### Backend — model + serialization

- `backend/models/core.py:141-165` — `EventFeedSummary` needs additive
  `affected_ci_ids: list[str] | None` and `affected_count: int | None`
  fields. `EventDetailEvent` (line 167) inherits these for free.
- `backend/services/event_service.py:173-207` — `_public_event_summary`
  `allowed_keys` must admit both new keys. The `propagated` derived flag
  (line 205-206) stays as-is.
- `backend/services/event_service.py:958-986` — `get_events` needs to accept
  `include_children: bool = False` and filter the Cypher with
  `coalesce(e.correlation_type, 'ROOT') = 'ROOT'` when false. Order of
  results must be preserved.
- `backend/services/event_service.py` (new function) — `get_affected_siblings`
  reads the ROOT event, returns `affected_ci_ids` joined with minimal CI info
  (`id`, `name`, `ip`, `location_name`) so the operator drill-down does not
  have to re-fetch every CI. Single Cypher with `UNWIND` + `MATCH (ci:CI)
  WHERE ci.id IN $ids`.
- `backend/routers/events.py:50-57` — `get_events` adds
  `include_children: bool = Query(False, ...)`.
- `backend/routers/events.py` (new route, near line 87) — `GET /events/{id}/affected`
  calls `get_affected_siblings`, returns the list. Must enforce the same
  `EVENT_VIEW` permission as the existing `/events/{id}` (line 92).

### Backend — tests

- `backend/tests/test_routers_events.py` — extend to cover the new query
  parameter and the new endpoint. Two existing routes already covered.
- `backend/tests/test_event_service_smoke.py` — there is **no
  `test_event_service.py`** (only `_smoke` and `_correlation`). P2 should
  add a focused `test_event_service.py` (or extend `_smoke`) for the
  `_public_event_summary` allowlist and the new `get_events` filter
  branch.
- `backend/tests/test_event_correlation.py` — already asserts
  `affected_ci_ids` writes. P2 does NOT need to add to it, but a strict-TDD
  test for the new service function is required.
- `backend/tests/test_snmp_worker_correlation.py` — no changes (writer path
  untouched, in scope rule).

### Frontend — types + hooks

- `frontend/types.ts:274-300` — `EventSummary` needs additive
  `affected_ci_ids?: string[]` and `affected_count?: number`.
  `EventDetailEvent` (line 348) extends it for free.
- `frontend/services/queryResources.ts:146-147` — `fetchActiveEvents` accepts
  `include_children?: boolean` and appends the query param.
- `frontend/hooks/queries/useActiveEventsQuery.ts` — pass
  `include_children: false` as the default. Query key change is required so
  polled data does not silently mix root-only with all-events (one cache
  key per mode).
- `frontend/services/queryKeys.ts:14` — `activeEvents` factory needs an
  `includeChildren` discriminator (or two factories
  `activeEventsRoots` / `activeEventsAll`).

### Frontend — UI

- `frontend/components/MonitoringConsole.tsx:1099-1101` — KPIs must filter
  on `isRoot` (already provided by `useEventCorrelation` at line 25-31). Add
  a "affecting N CIs" sub-label sourced from `event.affected_count` when
  > 0.
- `frontend/components/MonitoringConsole.tsx` (drill-down) — new modal/section
  that calls the `/events/{id}/affected` endpoint and renders the list of
  CIs. Could live in the existing `RelatedAlarmsPanel` (line 2463) or a
  sibling.
- `frontend/hooks/useEventCorrelation.ts:89` — extend the topology branch to
  recognise `CONNECTS_TO` in addition to `DEPENDS_ON | HOSTED_ON`. Optional
  safety-net improvement; the backend-side `correlation_type` is the primary
  signal.

### Frontend — tests

- `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx` — already
  mocks `/events?status=CONSOLE`. Add assertions that default mode returns
  only ROOTs and that KPI counts drop accordingly.
- `frontend/components/__tests__/EventDetailModal.acceptance.test.tsx` —
  extend mocks to include `/events/{id}/affected`; assert drill-down renders.
- `frontend/hooks/useEventCorrelation.test.ts` — add a `CONNECTS_TO`
  regression case.

## Approaches

### API filter

1. **`?include_children=true|false` on `GET /events`, default `false`.** —
   Backward-incompatible default change but behaviour matches operator
   expectation. One endpoint, one query param, minimal API surface.
   - Pros: small diff, query param is self-documenting, same payload shape.
   - Cons: silent default change; existing clients that relied on raw
     N+1 counts will see fewer rows. Mitigation: explicit
     `include_children=true` keeps the old behaviour.
   - Effort: **Low**.
2. **Separate endpoint `/api/root-events`.** — leaves `/api/events` alone.
   - Pros: zero breaking change, clear intent per endpoint.
   - Cons: two endpoints to maintain, the `/api/events` query will
     forever carry the suppressed-but-still-overcounted rows.
   - Effort: **Low**.
3. **Return `is_root: bool` / `correlation_type` on every event; client
   decides.** — additive, no breaking change. KPIs need to be reworked to
   count only roots client-side.
   - Pros: zero risk to existing consumers.
   - Cons: KPIs still count raw rows unless the client is reworked; two
     sources of truth (client `useEventCorrelation` vs backend
     `correlation_type`).
   - Effort: **Low**.

### KPI source

1. **Reuse `/api/events` filtered by `is_root` client-side.** — Uses the
   `useEventCorrelation` safety net already in place.
   - Pros: no new endpoint, fast to ship, exercises the existing hook.
   - Cons: every consumer (Monitoring, AI chat context, future clients)
     has to remember to filter; the truth drifts from backend.
   - Effort: **Low**.
2. **Dedicated `/api/events/summary` returning precomputed counts.**
   `{roots_total, critical_roots, warning_roots, ack_roots, ci_impact_total}`.
   - Pros: cheap to render, no client-side aggregation.
   - Cons: yet another endpoint, counts must stay in sync with the feed
     query (different Cypher path).
   - Effort: **Medium**.
3. **WebSocket push for root changes.** — Out of scope for this PR.
   - Pros: real-time.
   - Cons: substantial infra, not requested by issue #416.
   - Effort: **High**.

### Drill-down

- `GET /events/{id}/affected` — returns
  `[{ ci_id, ci_name, ci_hostname, ci_location_name }]` straight from the
  `affected_ci_ids` already on the ROOT. Single Cypher. **No alternative
  considered** — P0's data shape already supports it natively.

## Recommendation

**Approach (1)** for the API filter (`?include_children=true|false`, default
`false`) plus **Approach (i)** for KPIs (filter via existing
`useEventCorrelation.isRoot`). The drill-down is the only path that makes
sense.

Rationale:

- The whole point of P2 is to fix the operator's view. Keeping
  `/api/events` returning the full set would defeat the fix; approach (2)
  just pushes the same problem under a new URL.
- Approach (3) keeps the bug at the consumer level forever.
- The "silent default change" concern from (1) is acceptable because:
  (a) P0 already established the contract that propagated children should
  not be visible (their comments are appended to the ROOT, no child Event
  is created), so today the only rows coming back are the genuine ROOT
  Event plus the rare pre-P0 PROPAGATED child rows. (b) The
  `include_children=true` opt-out restores the prior behaviour for any
  consumer that truly needs the raw set (audit, AI chat context
  re-ingestion).
- Approach (i) keeps Monitoring rendering cheap. `useEventCorrelation` is
  already in the dependency graph and the hook is tested. The only new
  work is the sub-label "affecting N CIs" sourced from
  `event.affected_count`.
- WebSocket push (iii) is out of scope for P2 — the polling cadence
  (10s) is acceptable for operator dashboards.

## Risks

- **Breaking-change to AI chat context** (`services/ai_chat_service.py:422`)
  — the chat context builder also feeds through `_public_event_summary`.
  With `include_children=false`, the chat loses raw child rows. **Mitigation**:
  audit `ai_chat_service.py` to ensure it only needs ROOT events. If it
  needs the full set, call `get_events(status, include_children=True)`
  explicitly. **Severity: Low**.
- **Breaking-change to existing tests** —
  `MonitoringConsole.smoke.test.tsx`, `EventDetailModal.acceptance.test.tsx`,
  `MonitoringConsole.forcedClose.test.tsx` all mock `/events?...` as raw
  rows. They must be updated to either mock root-only rows or to set
  `include_children=true` on the request URL. **Severity: Low** (mechanical
  update).
- **Pre-P0 PROPAGATED children still exist in Neo4j** — events created
  before the P0 rollout retain `correlation_type = 'PROPAGATED'`. With the
  default filter, those legacy rows are now invisible. The frontend
  `useEventCorrelation` hook still picks them up if the polling ever
  returns them, but with `include_children=false` it won't. **Mitigation**:
  document in changelog and consider a one-off backfill to convert legacy
  PROPAGATED into affected_ci_ids on their parent (already covered by the
  archived `recommend-legacy-event-backfill` change — do not duplicate
  here). **Severity: Low**.
- **Empty `affected_ci_ids` on legacy ROOT events** — events written before
  P0 may have `affected_ci_ids` unset (null in Neo4j). The Cypher
  `coalesce(...)` and the Pydantic `| None` handle this. The frontend
  treats `undefined` as "no drill-down available" (no sub-label). **Severity:
  Low**.
- **Permission parity** — new `/events/{id}/affected` endpoint must enforce
  the same `EVENT_VIEW` permission as `/events/{id}`. Copy the existing
  pattern (`routers/events.py:92`). **Severity: Low**.
- **Query key invalidation** — adding `include_children` to the query string
  without updating the query key factory would cause stale cache
  cross-contamination between modes. The recommended change to
  `queryKeys.ts` mitigates this. **Severity: Low**.
- **Two sources of "is root"** — backend `correlation_type` (authoritative)
  vs. client `useEventCorrelation.isRoot` (derived safety net). Document
  the precedence in code comments. **Severity: Low**.

## Consumers of `GET /api/events`

Backend (read consumers of `_public_event_summary`):

- `backend/routers/events.py:51` — `get_events` router (the endpoint itself)
- `backend/services/ai_chat_service.py:422` — AI chat context builder
- `backend/services/event_service.py:1041` — internal call inside
  `get_related_events`

Backend (write/mutation consumers of `/api/events/...`, not affected by the
filter change):

- `backend/routers/events.py:109` — `POST /events/{id}/ack`
- `backend/routers/events.py:159` — `POST /events/{id}/close`
- `backend/routers/events.py:249` — `POST /events/{id}/comment`
- `backend/routers/events.py:269` — `POST /events/prune`
- `backend/routers/events.py:314` — `GET /events/bulk/stream-progress` (SSE)
- `backend/routers/events.py:383` — `POST /events/{id}/diagnose`

Frontend (read consumers):

- `frontend/services/queryResources.ts:146` — `fetchActiveEvents` → `/events?status=CONSOLE`
  - Called by `frontend/hooks/queries/useActiveEventsQuery.ts:5`
  - Consumed by `frontend/hooks/queries/useMonitoringConsoleData.ts:10`
  - Consumed by `frontend/components/MonitoringConsole.tsx:867`
- `frontend/services/queryResources.ts:190` — `fetchEventDetail(eventId)` →
  `/events/{id}` (not affected by the new filter; detail uses the event's
  own `affected_ci_ids`)
- `frontend/services/queryResources.ts:194` — `fetchRelatedEventsForCi` →
  `/events/related/{ciId}` (not affected; existing endpoint)

Frontend (test consumers that mock the endpoint):

- `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx`
- `frontend/components/__tests__/EventDetailModal.acceptance.test.tsx`
- `frontend/components/__tests__/MonitoringConsole.forcedClose.test.tsx`
- `frontend/services/queryResources.test.ts`
- `frontend/hooks/queries/resourceQueries.test.tsx`

## Field-location map for `affected_ci_ids` / `affected_count`

| Where it lives now | Path | Line | Notes |
|---|---|---|---|
| Written by writer (P0) | `backend/engines/snmp_worker.py` | 335-336 | SET clause, untouched |
| Read by service (raw) | `backend/services/event_service.py` | 144-170 | `_build_event_summary` copies all `event_data` keys, so the value is already in the summary dict |
| Dropped at serialization | `backend/services/event_service.py` | 173-207 | `_public_event_summary` `allowed_keys` set — **needs `affected_ci_ids` + `affected_count` added** |
| Pydantic surface (missing) | `backend/models/core.py` | 141-165 | `EventFeedSummary` — **needs two new optional fields** |
| Pydantic surface (inherited) | `backend/models/core.py` | 167-171 | `EventDetailEvent` extends `EventFeedSummary` for free |
| Frontend type (missing) | `frontend/types.ts` | 274-300 | `EventSummary` — **needs `affected_ci_ids?: string[]` + `affected_count?: number`** |
| Frontend query param (missing) | `frontend/services/queryResources.ts` | 146-147 | `fetchActiveEvents` — needs `include_children?: boolean` |
| Frontend query key (missing) | `frontend/services/queryKeys.ts` | 14 | `activeEvents` factory — needs an `includeChildren` discriminator |
| Frontend default | `frontend/hooks/queries/useActiveEventsQuery.ts` | 5-9 | must pass `include_children: false` and the new key |
| UI consumption (missing) | `frontend/components/MonitoringConsole.tsx` | 1099-1101 | KPI labels need root filter + "affecting N CIs" |
| Drill-down endpoint (missing) | `backend/routers/events.py` | after line 87 | new `GET /events/{id}/affected` |
| Drill-down service (missing) | `backend/services/event_service.py` | new function after line 986 | `get_affected_siblings(event_id)` |

## Changed-lines forecast

| File | Approx. lines added | Why |
|---|---|---|
| `backend/models/core.py` | +5 | two Pydantic fields |
| `backend/services/event_service.py` | +55-65 | `_public_event_summary` allowlist (+2); `get_events` query param + WHERE (+5); new `get_affected_siblings` (+35); new return-type helper (+15) |
| `backend/routers/events.py` | +20 | query param on existing route (+3); new `/events/{id}/affected` route (+17) |
| `backend/tests/test_routers_events.py` (or new `test_event_service.py`) | +80-120 | strict-TDD matrix: empty filter, populated filter, drill-down 404, permission check |
| `frontend/types.ts` | +2 | two interface fields |
| `frontend/services/queryResources.ts` | +6 | `include_children` param |
| `frontend/services/queryKeys.ts` | +3 | key discriminator |
| `frontend/hooks/queries/useActiveEventsQuery.ts` | +4 | pass the default + new key |
| `frontend/components/MonitoringConsole.tsx` | +30-40 | KPI root filter, sub-label, drill-down modal |
| `frontend/components/__tests__/MonitoringConsole.smoke.test.tsx` | +25 | default-filter assertions |
| `frontend/components/__tests__/EventDetailModal.acceptance.test.tsx` | +15 | drill-down render |
| `frontend/hooks/useEventCorrelation.ts` | +3 | `CONNECTS_TO` |
| `frontend/hooks/useEventCorrelation.test.ts` | +15 | regression case |

Totals: **backend ~160-210 lines**, **frontend ~100-110 lines**, **total
~260-320 lines**. Well under the 800-line review budget.

## Ready for Proposal

**Yes.** The P2 scope is bounded, additive on the API surface, the writer
path is untouched, and the breaking-change risk is limited to two
backend consumers (`ai_chat_service.py`, internal `get_related_events`) plus
mechanical test updates. The orchestrator should propose:

- Backend additive fields (`affected_ci_ids`, `affected_count`) on
  `EventFeedSummary`.
- New `include_children: bool = False` query param on `GET /api/events`.
- New `GET /api/events/{id}/affected` endpoint.
- Frontend: types + hook default + KPI root-filter + sub-label + drill-down
  modal.
- Frontend hook `useEventCorrelation` extended with `CONNECTS_TO`.
- Strict-TDD test matrix across all new surfaces.

Next SDD phase: **spec** (because the proposal already has the shape from
P0 — most decisions are about WHERE the fields land, which is a spec-level
detail, not a design tradeoff). The orchestrator should launch `sdd-spec`
next, then `sdd-propose` (or merge the two if the openspec convention
allows specs-first-then-proposal).

## Open questions for the orchestrator

- **AI chat context** (`ai_chat_service.py:422`): should the AI agent see
  roots only, or the full set with `include_children=true`? Documented in
  proposal scope but worth a stakeholder confirmation. **Severity: Low**,
  defaults to "roots only" if unconfirmed.
- **Legacy PROPAGATED events**: should P2 trigger any one-off backfill
  job, or defer to the existing `recommend-legacy-event-backfill` slice?
  Recommend defer.
- **Mutation endpoints** (`/ack`, `/close`, `/comment`) operate on the
  ROOT event id. If a legacy PROPAGATED child id is somehow referenced,
  the mutation will 404 today. No change proposed, but worth flagging in
  the proposal.