## Exploration: fix-poll-collector-cypher-param-root-cause

### Current State
Issue #343 is still reproducible from source inspection on both `origin/main` and this isolated worktree (`HEAD` is `c3a7243`, same as `origin/main`). The external SNMP worker has three malformed Cypher `SET` assignments that use a bare identifier, e.g. `poll_collector_id = $poll_collector_id`, inside `FOREACH` update branches. In Cypher, that is not an Event property assignment; it refers to an unbound variable named `poll_collector_id`, which explains Neo4j errors like `Variable poll_collector_id not defined` even though Python passes the `poll_collector_id` kwarg correctly.

The prior mitigation still exists: `backend/services/neo4j_write_guard.py` wraps selected Event writes, logs `cypher-param-fallback`, and retries a matching fallback query that omits `poll_collector_id`. This keeps Event writes alive, but it also masks the worker-side root cause until the malformed assignments are fixed. The legacy in-process SNMP service already uses the correct property form for updates (`existing.poll_collector_id = $poll_collector_id`), and the queue writer path uses row properties (`existing.poll_collector_id = row.poll_collector_id`), so the malformed bare assignments appear isolated to `backend/engines/snmp_worker.py`.

### Affected Areas
- `backend/engines/snmp_worker.py` — contains three root-cause candidates: lines 349, 477, and 635 assign bare `poll_collector_id = $poll_collector_id` in existing-Event `SET` clauses; CREATE clauses use `poll_collector_id: $poll_collector_id` correctly.
- `backend/services/neo4j_write_guard.py` — contains the temporary fallback wrapper and diagnostic logging for `Variable poll_collector_id not defined`; still documents the fallback as an unresolved RCA mitigation.
- `backend/services/snmp_service.py` — legacy service path already uses `existing.poll_collector_id = $poll_collector_id` for existing Event updates and `poll_collector_id: $poll_collector_id` for creates.
- `backend/polling/event_writer.py` — queue/writer path persists collector attribution through row data (`poll_collector_id: row.poll_collector_id`, `existing.poll_collector_id = row.poll_collector_id`) and does not show the malformed bare-param shape.
- `backend/tests/test_snmp_worker_cypher_fallback.py` — verifies fallback activation and fallback query omission, but not that primary SNMP worker queries use property-qualified assignments.
- `backend/tests/test_neo4j_write_guard.py` and `backend/tests/test_snmp_service_cypher_fallback.py` — cover fallback predicate/logging/dangling-comma behavior and legacy-service fallback behavior; they do not prove the issue #343 root-cause fix.
- `backend/tests/test_polling_event_writer.py` — includes queue writer collector-id persistence coverage, not the external SNMP worker malformed assignment case.
- `openspec/specs/cypher-param-fallback/spec.md` — canonicalizes the fallback behavior from issue #340 as a protected Event-write mitigation.

### Approaches
1. **Root-cause fix with focused regression tests** — Change the three SNMP worker existing-Event assignments to `existing.poll_collector_id = $poll_collector_id` and add tests that assert primary queries never contain the bare assignment.
   - Pros: Eliminates the known Cypher syntax root cause; keeps collector attribution on existing Events; directly supports the 7-day fallback-to-zero target.
   - Cons: Fallback may still remain for other unknown production-only causes unless separately deprecated; needs verification in logs after deploy.
   - Effort: Low

2. **Document fallback as permanent** — Treat the guard as intentional long-term behavior and document the known malformed primary queries as tolerated.
   - Pros: Minimal code churn; production remains protected by the existing mitigation.
   - Cons: Leaves a known syntax defect in the primary path; fallback activations will likely continue and fail the acceptance target; weak operational posture.
   - Effort: Low

### Recommendation
Proceed with SDD proposal/spec/design/tasks for the root-cause fix. The evidence points to a concrete code defect in `backend/engines/snmp_worker.py`, not a Neo4j driver parameter-binding issue. The proposal should explicitly scope only the three property-assignment corrections plus focused regression tests that fail on bare `poll_collector_id = $poll_collector_id` in primary SNMP worker Event-update queries. Keep the fallback in place as defense-in-depth until post-deploy logs show `cypher-param-fallback` trends to zero for 7 days; do not document it as permanent yet.

### Risks
- Tests today mostly validate fallback behavior, so an implementation could “pass the old tests” while leaving the malformed primary assignments intact.
- The 7-day acceptance target needs production log/metric evidence after deployment; code inspection alone cannot prove fallback activations trend to zero.
- Other unsearched Cypher strings outside Python files could theoretically reference `poll_collector_id`, but the SNMP worker/Neo4j write paths requested for this exploration identify the concrete root-cause candidates.

### Ready for Proposal
Yes — tell the user the root cause is verified in the isolated worktree and still present on `origin/main`: three SNMP worker `SET` clauses assign a bare Cypher variable instead of the `existing` Event property. The next phase should create a proposal for a small targeted fix with regression tests and post-deploy fallback-log verification.
