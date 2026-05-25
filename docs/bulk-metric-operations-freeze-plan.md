# Bulk metric operations freeze plan

## Problem

Bulk metric deletion and other large metric modifications can make the system appear blocked: the UI does not refresh, requests remain pending, and the app feels hung.

The current evidence points to backend contention, not only frontend rendering. Large Neo4j mutations run synchronously inside FastAPI `async` endpoints, while the UI continues polling endpoints that also depend on Neo4j.

## Confirmed hot spots

- `backend/routers/metrics.py`
  - `POST /api/metrics` calls synchronous metric save/reconciliation inline.
  - `DELETE /api/metrics/{metric_id}` calls synchronous metric delete inline.
- `backend/services/metric_service.py`
  - `_reconcile_metric_assignments()` scans all CIs and calls `reconcile_node_metrics()` per affected CI.
  - `reconcile_node_metrics()` fetches all MetricDefs per CI and performs per-relationship writes.
  - `delete_metric()` performs a single `DETACH DELETE` on a potentially highly connected MetricDef.
- `backend/services/node_service.py`
  - Bulk node upload inserts rows individually, then reconciles metrics per inserted CI.
- `backend/repositories/topology_repo.py`
  - `/nodes` loads all CIs and aggregates `HAS_METRIC` summaries, so refreshes contend with metric relationship churn.
- `frontend/components/MetricsManager.tsx`
  - Metric save/delete waits for one long request, uses blocking browser modals, and refreshes only after completion.
- `frontend/components/MassLinkEditor.tsx`
  - Mass relationship operations follow the same synchronous request pattern.
- `backend/Dockerfile`
  - Backend runs one uvicorn worker by default, so long inline sync mutations can starve other API requests.

## Root cause

The worst path is effectively `CIs × MetricDefs`:

1. Saving a metric writes the MetricDef.
2. `_reconcile_metric_assignments()` scans every CI.
3. For each affected CI, `reconcile_node_metrics()` fetches all MetricDefs again.
4. Relationship removals/additions are executed one by one.

For deletes, `DETACH DELETE` can remove many relationships in one transaction, holding locks and delaying concurrent reads/writes such as `/api/nodes` refresh polling.

## Proposed delivery plan

### Phase 1 — Safe mitigation

Goal: reduce perceived freezes with low review risk.

- Run heavy synchronous service calls from route handlers through a threadpool boundary so the FastAPI event loop is not monopolized.
- Add logging/timing around metric save/delete/reconciliation and bulk upload.
- Improve MetricsManager delete/save UI state:
  - show an operation-in-progress message,
  - disable only the relevant action,
  - clear selected metric after delete,
  - await refreshes after mutation.
- Add focused tests that long-running service calls do not block route coroutine completion semantics where practical.

Limit: this mitigates API starvation but does not eliminate Neo4j lock/contention from large transactions.

### Phase 2 — Batch reconciliation

Goal: remove the `CIs × MetricDefs` loop.

- Replace per-CI reconciliation for metric save/edit with set-based Cypher.
- Compute affected CIs in the database where possible.
- Use `UNWIND $rows` / batch writes for relationship add/remove operations.
- Preserve existing semantics:
  - brand/model/layer/name criteria,
  - explicit CI names,
  - `excluded_names`,
  - AppliedDictionary `excluded_metrics` / `extra_metrics`.
- Add query-count or performance-regression tests for large N.

### Phase 3 — Chunked delete / async jobs

Goal: make destructive mass changes observable and cancellable.

- Replace direct `DETACH DELETE` for MetricDef with chunked relationship cleanup followed by MetricDef delete.
- Consider marking MetricDef as disabled/deleting first so collection stops quickly.
- Add a job model/status endpoint for long operations.
- Add frontend progress polling and completion/error states.

### Phase 4 — Refresh/read scalability

Goal: stop dashboard refreshes from amplifying write contention.

- Split lightweight CI list from metric summaries or make `/nodes` pageable/selective.
- Invalidate/refetch relevant React Query keys after mutations instead of relying only on polling.
- Consider separate endpoint for metric summaries by selected CI/page.

## Acceptance criteria

- Creating/editing a metric applicable to many CIs no longer makes unrelated API refreshes appear frozen.
- Deleting a widely applied metric completes predictably or returns an observable async job.
- `/api/nodes` and active event refreshes remain responsive during large metric operations, within documented limits.
- Existing dictionary overlay behavior remains correct.
- Tests cover additions, removals, explicit names, exclusions, and dictionary extras/exclusions.
- The UI clearly communicates long-running operations and refreshes state after completion.

## Validation checklist

- Reproduce with hundreds/thousands of CIs and one widely applicable metric.
- Observe Browser Network for `POST /api/metrics`, `DELETE /api/metrics/{id}`, `/api/nodes`, and `/api/events?status=ACTIVE`.
- Observe Neo4j with query logs or `SHOW TRANSACTIONS` during delete/reconcile.
- Run backend metric reconciliation tests.
- Run frontend `MetricsManager` tests after UI changes.

## Non-goals for the first implementation

- Rewriting the full polling engine.
- Deleting historical metric samples unless explicitly specified.
- Changing metric applicability semantics.
- Broad redesign of all mass relationship operations in the first PR.
