## Exploration: Event amplification (#416)

### Current State

The repository has three event-producing paths, but only one is production-default in the checked-in Docker topology:

- **In-process legacy collector:** `backend/main.py` starts `snmp_collector_loop()` only when `DISABLE_BACKEND_COLLECTOR` is false. The loop runs a cycle approximately every 60 seconds, iterates CIs and metrics, and calls `backend/services/snmp_service.py:store_metric_result` one result at a time.
- **External SNMP worker, non-queue path:** `docker-compose.yml` disables the backend collector and starts `backend/engines/snmp_worker.py`. Its scheduled `poll_snmp()` job runs every 10 seconds, collects the cycle results into in-memory lists, and then performs batched Neo4j/Timescale writes. This is the current default path.
- **External worker plus queue/writer path:** disabled by default by `POLLING_PG_QUEUE_ENABLED`, `POLLING_SNMP_LEASED_WORKER`, and `POLLING_DB_WRITER_ENABLED`. The leased worker returns envelopes; `writer_pool.run_writer_once()` persists Timescale samples/receipts first and delegates event writes to `polling/event_writer.py`.

#### Write-time correlation

`backend/repositories/topology_repo.py:build_open_parent_index` performs one Cypher query for a set of `(ci_id, metric_id)` pairs. It traverses `DEPENDS_ON`, `HOSTED_ON`, and `CONNECTS_TO` upstream for at most three hops, considers only parent events in `OPEN` or `ACK`, and omits non-propagating metrics (`MetricDef.can_propagate = false`). A missing key means ROOT. The query is based on events already persisted before the cycle; it does not see failures collected in the same cycle that have not yet been written.

`backend/engines/snmp_worker.py:poll_snmp` builds that index once, after all observations have been collected and before the event-write helpers run. `_resolve_correlation` is a no-I/O dictionary lookup: a hit produces `PROPAGATED`, `propagated_from`, and a CI-level `root_cause_ci_id`; a miss produces ROOT. Consequently, when a parent and ten children fail for the first time in the same cycle and no parent event existed before the cycle, every row misses the index and is initially treated as ROOT. This is the direct cause of the N+1 amplification in the default topology.

The external worker already contains the later root-enrichment behavior: `_refresh_snmp_collection_failures`, `_refresh_icmp_availability_events`, and `_refresh_icmp_latency_events` separate ROOT rows from PROPAGATED rows. ROOT rows may create/update an Event. PROPAGATED rows do not create child Event nodes; `_update_propagated_root_events` idempotently adds the affected CI ID and a comment to the referenced ROOT event. This prevents repeated propagated child creation, but it cannot correct a cache built before the current-cycle root exists.

The legacy path has different semantics. `store_metric_result` calls `find_open_parent_event` only when it is about to create a new Event. That query also traverses the three topology relationships up to depth three and only sees `OPEN`/`ACK` parent events. The result is written directly as a Neo4j `Event` with `correlation_type`, `propagated_from`, and `root_cause_ci_id`. Thus, if the parent was written earlier in iteration order, the child becomes a persisted PROPAGATED Event; if the child is processed first, it becomes ROOT. The path is order-dependent and still creates child Event nodes. Its breach refresh lookup is not root-only, while its recovery lookup is root-only and separately recovers descendants. The legacy fallback can also use a parent event ID as `root_cause_ci_id` when the parent result lacks a CI root cause, unlike the external worker's defensive ROOT fallback.

The queue path has no current topology lookup. `polling/scheduler.py` and `polling/snmp_executor.py` carry polling metadata but do not call `build_open_parent_index` or `find_open_parent_event`. `event_writer.build_event_rows` defaults correlation to ROOT unless an upstream envelope already contains correlation metadata. If PROPAGATED metadata is supplied, the queue writer still follows its existing child-event Cypher path; it does not use the external worker's root-enrichment helper. Therefore the queue path is both feature-flagged and semantically distinct, and a fix limited to `engines/snmp_worker.py` will not provide queue parity.

#### Event model, Neo4j persistence, and API

`backend/models/core.py` does **not** define a Pydantic `Event` persistence model. It defines `EventFeedSummary` and `EventDetailEvent`. The public summary currently exposes `propagated_from`, `correlation_type` (`ROOT` or `PROPAGATED`), and `root_cause_ci_id`; fields named `parent_event` or `correlation_id` are not present in the current model. Neo4j Event nodes are schemaless properties created by Cypher in the writers. The external root-enrichment path additionally stores `affected_ci_ids`, `affected_ci_count`, and comments, but those properties are not part of `EventFeedSummary`.

`backend/routers/events.py` exposes `GET /events`, mounted under the API prefix, and delegates to `event_service.get_events`. `get_events(status="CONSOLE")` returns `OPEN`, `ACK`, and `RECOVERED` Event nodes, ordered by `created_at`; it does not exclude PROPAGATED nodes or collapse event groups. `_public_event_summary` intentionally filters the public fields, so current root affected-CI metadata is invisible through this endpoint. Additive optional fields would be API-compatible; changing the endpoint to silently hide existing PROPAGATED records would be a contract change for non-frontend consumers.

#### Topology gaps

A CI without a registered upstream CI, without the expected relationship direction/type, or without an open parent Event has no key in `build_open_parent_index` and is correctly treated as ROOT under the current algorithm. The same applies when the path exceeds the hard-coded depth of three or when `can_propagate` is false. There is no AP-specific parent synthesis or topology backfill in this function. APs that are present as CIs but lack their parent relationship/event remain independent roots, so write-time correlation cannot solve an inventory/topology gap. Parent selection is also one event per `(child CI, metric)` pair, choosing the highest severity and oldest creation time; multiple simultaneous parent metrics are not represented as multiple parent links.

#### Frontend behavior

`/monitoring` is the event console route. The sidebar label `Architecture` maps to the index route `/`, which renders `SystemDashboard`; there is no separate `/architecture` route in `frontend/App.tsx`. `useActiveEventsQuery` requests `/events?status=CONSOLE` every 10 seconds, and `useMonitoringConsoleData` passes that raw list to `MonitoringConsole`.

`MonitoringConsole` calculates Critical, Warning, Acknowledged, and Total Active KPI cards from the raw `events` array. It does not use the grouped root list for KPI counts. `useEventCorrelation` is only a client-side presentation safety net: it groups same-CI events and `DEPENDS_ON`/`HOSTED_ON` provider-consumer events, returns only `isRoot` items for the stream, and displays `relatedEvents.length`. It does not recognize `CONNECTS_TO`, does not consume persisted `affected_ci_count`, and cannot prevent raw API consumers or KPI calculations from seeing N+1 records. The current `Correlated Events` badge is therefore a visual count derived from events that were already returned, not a durable affected-CI contract.

### Affected Areas

- `backend/engines/snmp_worker.py` — default external worker; per-cycle cache is built before current-cycle root writes; existing root-enrichment behavior must remain idempotent.
- `backend/repositories/topology_repo.py` — batched parent lookup, depth/type/direction limits, and missing-parent behavior.
- `backend/services/snmp_service.py` — legacy in-process write-time lookup and persisted PROPAGATED child-event behavior.
- `backend/polling/event_writer.py` — queue writer defaults to ROOT and has a different PROPAGATED child-event implementation.
- `backend/polling/snmp_executor.py`, `backend/polling/scheduler.py`, `backend/polling/writer_pool.py` — queue metadata and write ordering; no current topology correlation seam.
- `backend/models/core.py`, `backend/services/event_service.py`, `backend/routers/events.py` — public event fields, filtering, and serialization.
- `frontend/types.ts`, `frontend/hooks/useEventCorrelation.ts`, `frontend/hooks/queries/useActiveEventsQuery.ts`, `frontend/components/MonitoringConsole.tsx` — raw KPI counts, client grouping, polling cadence, and affected-event display.
- `backend/tests/test_snmp_worker_correlation.py`, `backend/tests/test_event_correlation.py`, `backend/tests/test_polling_event_writer.py`, and related frontend hook/component tests — existing contracts for PROPAGATED, recovery, and API/UI behavior.

### Approaches

1. **Small same-cycle lookahead** — On a cache miss, perform a bounded parent lookup or consult an in-memory current-cycle failure index before writing the child.
   - Pros: Small conceptual change; can reduce amplification when the parent happens to be processed first; preserves current batch shape.
   - Cons: A lookup alone cannot reference a root Event that has not been created; arbitrary result order still leaves child-first cases; per-row Neo4j reads increase latency and contention; it is difficult to apply consistently to all three external-worker event families and the legacy path.
   - Effort: Medium

2. **Two-pass cycle correlation** — Build a current-cycle candidate index/topology ordering, write only root candidates in pass one, then rebuild/resolve the open-parent index and attach dependent rows as affected CIs in pass two.
   - Pros: Deterministic for unordered batches; fits the external worker's existing collect-then-write design; keeps `PROPAGATED` as internal correlation metadata and preserves idempotent root enrichment; avoids durable N+1 child Events.
   - Cons: Requires an explicit definition of a current-cycle root, additional topology/read/write work, and careful handling of parent recovery and concurrent writers; legacy parity needs a separate adapter because it currently writes one result at a time.
   - Effort: Medium-High

3. **Post-commit reconciliation** — Write current rows first, then associate children with roots and remove, hide, or recover duplicate child Events.
   - Pros: Can use committed Neo4j Event IDs and can be implemented as a separate reconciliation step.
   - Cons: Violates the issue's hard requirement during the reconciliation window; `/events`, KPIs, escalation, and external consumers can observe N+1; cleanup races with ACK/close/recovery and creates migration/idempotency complexity.
   - Effort: High

4. **Per-metric/CI buffer with periodic flush** — Hold failed observations until a short correlation window closes, then emit roots and affected-CI annotations.
   - Pros: Handles arbitrary arrival order and late parent observations; can be extended to distributed workers.
   - Cons: Adds alert latency, memory/durability/backpressure requirements, restart recovery, and a new lifecycle state; substantially changes operational semantics and is not justified for the first fix.
   - Effort: High

### Recommendation

Use **Approach 2 for the first implementation slice**, starting with the production-default external worker. The slice should introduce a bounded current-cycle correlation context that considers the existing persisted `OPEN`/`ACK` index plus failures observed in the same cycle, deterministically materializes root events first, and then runs the existing PROPAGATED-to-root enrichment path. It must cover collection failures, ICMP availability, and ICMP latency/threshold breaches, preserve the existing depth-three topology contract, and retain advisory-lock ordering and the `poll_collector_id` Cypher fallback.

The current-cycle phase must not merely rerun `build_open_parent_index`: that function only returns already persisted Events. It needs either a deterministic parent-first ordering within the existing depth limit or an equivalent batched topology/candidate resolution that can identify which observed CIs are roots before creating their Events. The second pass should re-resolve parent Event IDs and update `affected_ci_ids`/`affected_ci_count` idempotently without creating child Event nodes.

The first slice should be backend-only and prove the invariant with strict-TDD cases: one parent plus many children in the same cycle; child-before-parent input order; multiple affected metrics; repeated cycles; no parent relationship; non-propagating metrics; a parent recovering in the same cycle; and a topology lookup failure falling back safely to ROOT. Legacy collector parity should follow immediately because it is still runnable outside the checked-in compose defaults and currently has materially different child-event semantics.

After the write invariant is stable, expose optional `affected_ci_ids`/`affected_ci_count` (and, if needed, a stable affected-CI summary) through the API. Then update MonitoringConsole KPI/group rendering to use durable root metadata while retaining `useEventCorrelation` as a compatibility fallback. Queue-path correlation should be a separate gated slice: it needs a shared correlation seam before `polling/event_writer.py` can claim parity.

### Priority Slices (P0/P1/P2/P3)

- **P0 — Write-time suppression for the default external worker:** eliminate first-cycle same-batch amplification and keep one ROOT Event plus idempotent affected-CI annotations. Cover all current external-worker event families and preserve #310/#318 topology RCA, #322/#330 advisory locks/collector identity, and the current root-enrichment behavior associated with #405.
- **P1 — Legacy collector parity and public API contract:** prevent the in-process path from creating PROPAGATED child Event nodes, align its root/affected-CI lifecycle with P0, and add optional affected-CI fields to `EventFeedSummary`/`get_events` without breaking existing correlation fields.
- **P2 — Frontend semantics:** make `/monitoring` KPIs and event badges use root-event and affected-CI data rather than raw N+1 counts; retain client grouping for older records and explicitly decide whether `CONNECTS_TO` is included in the UI grouping contract. `/` remains the Architecture/SystemDashboard route and should not be changed to treat collector snapshots as event snapshots.
- **P3 — Queue parity and topology remediation:** add correlation to the leased queue path only behind its existing flags, then audit/backfill missing AP parent relationships through a separately reviewable, idempotent topology operation. Do not make topology backfill a hidden side effect of event creation.

### Risks

- The same-cycle cache currently represents the graph state before event writes; changing its timing can alter which parent is selected and how parent recovery is interpreted.
- `build_open_parent_index` chooses one highest-severity/oldest parent event per child-metric pair and does not select multiple parent metrics; this may under-represent multi-metric root causes.
- Missing AP parent CIs/links, unsupported relationship types, incorrect direction, and depth greater than three will continue to produce ROOT events unless topology data is repaired.
- Legacy and queue writers currently persist PROPAGATED child Events, while the external worker enriches roots instead; partial rollout can produce mixed API/UI semantics.
- Replacing raw API rows with root-only rows could break consumers that depend on seeing existing PROPAGATED records; additive fields and explicit filtering are safer than silent removal.
- Two-pass writes increase Neo4j round trips and may increase lock duration. The existing sorted advisory-lock contract and single-cycle SQLAlchemy session must be preserved to avoid cross-writer races/deadlocks.
- Parent failure and recovery observed in one cycle can leave a recovered root with affected-CI annotations; lifecycle expectations need explicit tests before changing recovery queries.
- Frontend polling remains eventually consistent (`/events` every 10 seconds); a write-time fix removes amplification but does not create an immediate push update.

### Ready for Proposal

Yes. The problem and first slice are sufficiently bounded for a proposal: start with P0 external-worker same-cycle two-pass correlation, define the root/affected-CI invariant and recovery behavior, and keep legacy parity, API/UI, queue parity, and topology backfill as explicitly sequenced follow-up slices. The proposal should request a review-budget forecast because the complete P0-P3 roadmap may exceed the configured 800 changed-line budget even though the first backend-only slice should remain reviewable.
