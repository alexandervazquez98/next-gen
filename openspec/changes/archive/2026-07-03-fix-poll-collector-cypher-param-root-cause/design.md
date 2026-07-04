# Design: Fix Poll Collector Cypher Parameter Root Cause

## Technical Approach

Audit polling/Event writer Cypher that touches `poll_collector_id`, then fix the direct malformed SNMP worker `SET` assignments by qualifying them with the existing Event alias. This satisfies the `cypher-param-fallback` delta spec by making primary existing-Event update queries valid without relying on fallback, while preserving fallback and its `cypher-param-fallback` log marker for temporary operational protection.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Property assignment target | Change bare `poll_collector_id = $poll_collector_id` to `existing.poll_collector_id = $poll_collector_id` in the three SNMP worker existing-Event update clauses. | Rename the parameter; remove collector attribution; rely on fallback. | In Cypher `SET name = ...` targets a variable, while `SET existing.name = ...` updates a node property. Python already passes the parameter; the query shape is the defect. |
| Fallback lifecycle | Keep `run_with_cypher_param_fallback` and existing fallback queries unchanged. | Remove fallback immediately after root-cause fix. | The proposal explicitly treats fallback as temporary defense-in-depth. Keeping it allows post-deploy verification that fallback logs trend to zero before a separate removal change. |
| Regression test style | Add focused string/AST-style tests against captured primary queries in `test_snmp_worker_cypher_fallback.py`. | Full Neo4j integration test; broad worker-cycle test. | Existing tests already capture query strings with fake sessions. Narrow tests fail fast before the fix, avoid external services, and directly prove no bare assignment remains. |
| Audit boundary | Report adjacent findings, but only change direct SNMP worker malformed assignments. | Expand to all collector/fallback cleanup in one PR. | The spec requires stopping before scope expansion. Other checked writers are already property-qualified, so expanding would add review risk without fixing issue #343. |

## Data Flow

```text
SNMP worker event helper
  ├─ primary Cypher with poll_collector_id param
  │    ├─ CREATE Event: poll_collector_id: $poll_collector_id
  │    └─ UPDATE Event: existing.poll_collector_id = $poll_collector_id
  └─ on matching ClientError only: fallback query without poll_collector_id
       └─ ERROR log marker: cypher-param-fallback
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/engines/snmp_worker.py` | Modify | Property-qualify the three malformed existing-Event update assignments in collection failure, ICMP availability, and ICMP latency primary queries. |
| `backend/tests/test_snmp_worker_cypher_fallback.py` | Modify | Add strict-TDD regression tests that first fail on bare primary assignments and pass only when captured primary queries use `existing.poll_collector_id`. |
| `backend/services/neo4j_write_guard.py` | No code change | Fallback behavior and logging contract remain intact for post-deploy evidence. |

## Interfaces / Contracts

No public API or schema contract changes. The internal Cypher contract is:

```cypher
SET existing.poll_collector_id = $poll_collector_id
```

Bare assignment `poll_collector_id = $poll_collector_id` is invalid for existing Event property updates and must be rejected by regression coverage.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Primary SNMP worker query strings reject bare existing-Event assignment. | Strict TDD: add failing tests first in `test_snmp_worker_cypher_fallback.py`, capture the first `session.run` query for each helper, assert no unqualified `SET` assignment and assert `existing.poll_collector_id = $poll_collector_id` is present. |
| Unit | Existing fallback behavior remains available. | Keep current fallback tests unchanged; they should continue passing. |
| Integration | Not required for this root-cause patch. | Existing fake-session tests directly validate the malformed source string without Neo4j dependency. |
| E2E | Post-deploy evidence only. | Operators check logs for `cypher-param-fallback`; expected trend is zero fallback activations for this root cause. |

## Migration / Rollout

No data migration required. Deploy the source fix, then verify logs for `cypher-param-fallback` after deployment; fallback activations for undefined `poll_collector_id` should trend to zero over 7 days. Do not remove fallback in this change.

## Suspicious Adjacent Findings

- `backend/polling/event_writer.py` already uses `existing.poll_collector_id = row.poll_collector_id`; non-blocking.
- `backend/services/snmp_service.py` existing-Event path already uses `existing.poll_collector_id = $poll_collector_id`; non-blocking.
- `backend/services/neo4j_write_guard.py` docs still describe the cause as unresolved; non-blocking and out of scope unless maintainers request wording cleanup.

## Open Questions

None.
