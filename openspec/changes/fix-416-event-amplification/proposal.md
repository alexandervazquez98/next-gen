# Proposal: P0 Write-Time Event Correlation Suppression (fix-416)

## Intent

`backend/engines/snmp_worker.py:poll_snmp` builds `build_open_parent_index` before current-cycle root Events are persisted. When a parent CI and N children fail in the same cycle with no pre-existing parent Event, all N+1 rows become separate ROOT Events. P0 introduces bounded two-pass correlation: deterministic root materialization first, then affected-CI attachment on just-written roots.

## Scope

### In Scope
- Two-pass correlation in `backend/engines/snmp_worker.py` for collection failures, ICMP availability, and ICMP latency/threshold families.
- Preserve `#310`/`#318` topology depth-three, `#322`/`#330` `pg_advisory_xact_lock` + `poll_collector_id`, `#405` correlation-topology-policy.
- Strict-TDD matrix from exploration §Recommendation: parent + N children, child-before-parent order, multi-affected-metric parent, repeated cycles, no parent relationship, non-propagating metrics, parent recovery in same cycle, topology-lookup failure → ROOT.

### Out of Scope (explicit follow-up slices)
- Legacy in-process collector parity (P1).
- API additive fields and `/monitoring` KPI rendering (P2).
- Queue leased-path correlation parity (P3).
- Topology backfill / AP parent synthesis (P3).

## Capabilities

### New Capabilities
- `event-write-time-correlation`: same-cycle two-pass correlation in the external worker. One ROOT Event + affected-CI annotations per parent failure.

### Modified Capabilities
- None. `event-writer-coordination-observability`, `cmdb-graph-level-of-detail`, `icmp-latency-threshold-env`, `legacy-event-backfill-local-evidence`, `vpn-tunnel-relations` remain unchanged. P0 alters internal write order only.

## Approach

Apply exploration recommendation #2 (two-pass). Refactor `poll_snmp`:

1. **Collect**: current per-cycle observation (unchanged).
2. **Root materialize**: deterministic candidate-root ordering from existing depth-three index plus current-cycle candidates; write only ROOT candidate rows.
3. **Affected-CI attach**: re-resolve open-parent index from just-persisted ROOTs; idempotently append dependents as `affected_ci_ids`/`affected_ci_count` via existing `_update_propagated_root_events`.

## Affected Areas

- `backend/engines/snmp_worker.py` (Modified): two-pass orchestration in `poll_snmp`.
- `backend/repositories/topology_repo.py` (Modified): add current-cycle candidate helper; depth-three contract unchanged.
- `backend/engines/correlation.py` (New): cycle candidate ordering + root materialization.
- `backend/tests/test_snmp_worker_correlation.py` (Modified): strict-TDD matrix.
- `backend/tests/test_event_correlation.py` (Modified): pass-3 affected-CI attach tests; preserve PROPAGATED tests.

## Risks

- **Same-cycle cache timing changes parent selection** (Med): test matrix covers all input orderings.
- **Pass-3 adds Neo4j round trips and lock duration** (Low): single SQLAlchemy session; advisory-lock triplet preserved.
- **Parent recovery in same cycle leaves recovered root with affected-CI annotations** (Med): explicit recovery test; root-enrichment helper already idempotent.
- **External consumers depending on raw N+1 rows** (Low): P0 does not change `/events` API; document in changelog.
- **Partial rollout leaves legacy/queue writers on old semantics** (Low): P0 only touches `engines/snmp_worker.py`; P1/P3 sequenced.

## Rollback Plan

Revert the commit introducing the two-pass helper. No DB migration. Legacy collector and queue paths unaffected.

## Success Criteria

- [ ] Parent + N children in same cycle produce ONE ROOT Event + N affected-CI annotations, regardless of input ordering.
- [ ] All existing correlation and lock tests still pass.
- [ ] `#310`/`#318`/`#322`/`#330`/`#405` invariants unchanged.
- [ ] No public API contract change.
