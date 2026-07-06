## Exploration: Event writer coordination observability

### Current State
Issue #322 is implemented: `backend/services/event_lock.py` exposes `acquire_event_triplet_lock(pg_db, ci_id, metric_id, event_type)`, which runs `SELECT pg_advisory_xact_lock(hashtext(:key))` using the triplet key. The three protected polling Event writers already acquire this lock before Neo4j Event create/update paths: `backend/engines/snmp_worker.py`, `backend/services/snmp_service.py`, and `backend/polling/event_writer.py` via `writer_pool.run_writer_once`. Batched writers sort distinct triplets before acquisition to avoid PostgreSQL advisory-lock deadlocks.

Issue #334 has also landed a CI guard in `backend/tests/test_event_writer_lock_guard.py` plus `backend/tests/README.md`; it discovers production Event emitters and requires protected/exempt classification with evidence metadata, but it intentionally does not add runtime observability. There is no Prometheus/OpenTelemetry dependency in backend requirements, no existing lock metrics, no lock wait logging, and the only current health surfaces are `/` and `/api/system/status`.

### Affected Areas
- `backend/services/event_lock.py` — central point for measuring lock acquisition count, wait duration, timeout failures, and structured logging without changing each writer's Event semantics.
- `backend/engines/snmp_worker.py` — protected writer; likely needs a `writer` label/context when calling the shared helper.
- `backend/services/snmp_service.py` — protected legacy writer; session lifetime must remain open across the Neo4j write after any observability wrapper.
- `backend/polling/event_writer.py` — protected batch writer; `_acquire_sorted_locks` should preserve deterministic ordering while passing writer context into the helper.
- `backend/polling/writer_pool.py` — confirms the queue writer passes the open Timescale session as `lock_db`; timeout behavior must preserve result retry semantics.
- `backend/tests/test_writer_advisory_lock.py`, `backend/tests/test_snmp_worker.py`, `backend/tests/test_snmp_service_collection_failures.py`, `backend/tests/test_polling_event_writer.py` — current lock behavior tests; best place for regression coverage around metrics/logging/timeout semantics.
- `backend/tests/test_event_writer_lock_guard.py` and `backend/tests/README.md` — existing future-writer guard; issue #326 should not duplicate #334, only document how the guard complements runtime observability.
- `backend/main.py` — current `/` and `/api/system/status` health surfaces; any lock healthcheck/status exposure would integrate here unless a dedicated observability endpoint is introduced.
- `backend/postgres_db.py` and `docker-compose.yml` — deployment invariant location: all Event writers must point at the same PostgreSQL/Timescale instance via the same `POSTGRES_HOST`, `POSTGRES_PORT`, and database identity.
- `docs/itsm/event-flow.md`, `docs/polling-pipeline-runbook.md`, or a new focused backend event-writer document — appropriate homes for operational invariants without overloading test documentation.

### Approaches
1. **Minimal helper-level instrumentation and documentation** — Keep `pg_advisory_xact_lock`, measure elapsed time around `pg_db.execute`, increment in-process counters/histograms, emit structured logs at DEBUG/INFO thresholds, and document shared-Postgres/session-lifetime invariants.
   - Pros: low semantic risk; one central helper; avoids touching Neo4j Event logic; fast to test with existing mocks; keeps issue #334 scoped to CI guardrails.
   - Cons: in-process metrics may not be scrape-compatible without a metrics exporter; helper needs writer context added to call sites for useful labels.
   - Effort: Medium.

2. **Timeout-capable lock helper using PostgreSQL local settings** — Add a configurable lock timeout around acquisition, e.g. `SET LOCAL lock_timeout` before `pg_advisory_xact_lock`, then fail fast with structured logging/metrics when lock acquisition cannot complete.
   - Pros: directly addresses blocking/unavailability; keeps timeout scoped to the current transaction; preserves PostgreSQL as the coordination backend.
   - Cons: product/operations must decide whether timeout is fail-closed (skip/retry Event write) or fail-open (write without lock and risk duplicates); tests need real-Postgres coverage for timeout behavior.
   - Effort: Medium/High.

3. **Full observability surface and runtime invariant checks** — Add scrapeable metrics endpoint/dependency, lock health in `/api/system/status` or a dedicated health endpoint, startup/runtime checks that all writers target the same PostgreSQL instance, and alert-ready documentation.
   - Pros: most operationally complete; aligns with issue's metrics/alerts/healthcheck ambitions; makes drift visible to operators.
   - Cons: larger PR; may exceed review budget; introduces product decisions around metrics stack, alert ownership, healthcheck failure semantics, and deployment topology; could blur into framework-level single-writer enforcement.
   - Effort: High.

### Recommendation
Proceed with a scoped proposal that splits issue #326 into two reviewable slices if needed: first add helper-level runtime observability plus invariant documentation, then add timeout/healthcheck behavior once fail-open vs fail-closed policy is decided. Instrumenting `backend/services/event_lock.py` is the safest anchor because all protected writers already converge there and existing tests can prove semantics remain unchanged.

Do not reimplement issue #334. Treat the existing `test_event_writer_lock_guard.py` as the future-writer enforcement baseline and limit this change to documenting the guard's role plus adding runtime observability for actual lock usage.

### Risks
- Timeout behavior is a real product/operations decision: fail-open preserves Event writes but can reintroduce duplicate OPEN Events; fail-closed preserves dedup semantics but can drop/defer Event visibility during PostgreSQL issues.
- A scrapeable Prometheus-style implementation may require adding a new dependency and endpoint; the repo currently has no general metrics exporter pattern.
- Logging every acquisition with triplet labels can become noisy and may expose high-cardinality identifiers; default DEBUG plus INFO only above a wait threshold is safer.
- Hash collisions from `hashtext()` only cause false contention, not data loss, but metrics may make collision-like contention visible without proving root cause.
- Healthcheck semantics can cause operational harm if lock contention marks the backend unhealthy and triggers restarts while writers are merely waiting.
- PostgreSQL pool exhaustion remains possible because lock waits hold connections for the Neo4j write duration; documentation should include pool-sizing guidance.

### Ready for Proposal
Yes — proposal can start, but it should ask these open questions before design/tasks: Which metrics backend should be used (in-process/status payload only vs Prometheus-compatible exporter)? Should alert definitions be documentation-only or implemented in repo? Should lock acquisition timeout fail-open, fail-closed/retry, or only log for the first slice? Should lock health affect `/api/system/status`, `/`, a new endpoint, or only metrics/logs? What wait thresholds should drive INFO logs and alerts (`50ms` log and `100ms p99` alert are issue defaults but need confirmation)?
