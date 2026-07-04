# Proposal: Fix Poll Collector Cypher Parameter Root Cause

## Intent

Eliminate the source-level Cypher syntax defect that causes `Variable poll_collector_id not defined` and activates the existing Event-write fallback despite Python passing the correct kwargs.

## Scope

### In Scope
- Audit all `poll_collector_id` Cypher usage in the polling/Event writer paths.
- Fix direct malformed existing-Event assignments such as `poll_collector_id = $poll_collector_id` by property-qualifying them.
- Add focused regression tests proving primary SNMP worker queries do not contain bare `poll_collector_id` assignments.
- Preserve the current fallback temporarily as defense-in-depth until post-deploy evidence supports removal.

### Out of Scope
- Removing the fallback in this change.
- Continuing unrelated Neo4j driver investigation once the source-level root cause is proven.
- Expanding implementation beyond the direct defect without approval; suspicious adjacent findings should be reported first.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `cypher-param-fallback`: clarify that protected primary Event writers must not rely on fallback for malformed `poll_collector_id` property assignments, while the fallback remains temporary operational protection.

## Approach

Use the exploration recommendation: audit `poll_collector_id` Cypher strings, correct malformed SNMP worker `SET` clauses to assign `existing.poll_collector_id = $poll_collector_id`, and add narrow tests that fail on the bare-assignment pattern. Keep fallback logging intact for operational verification.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/engines/snmp_worker.py` | Modified | Correct malformed Event update Cypher assignments found during audit. |
| `backend/services/neo4j_write_guard.py` | Unchanged | Fallback remains as temporary defense-in-depth and log evidence source. |
| `backend/tests/test_snmp_worker_cypher_fallback.py` | Modified | Add regression coverage for primary query shape. |
| `openspec/specs/cypher-param-fallback/spec.md` | Modified via delta | Specify primary query correctness alongside temporary fallback protection. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Audit misses another malformed Cypher string | Medium | Search all `poll_collector_id` Cypher usage before editing. |
| Tests only validate fallback, not primary query correctness | Medium | Add direct assertions against bare assignment patterns. |
| Fallback activations continue for a separate cause | Low | Keep fallback logging and document post-deploy evidence review. |

## Rollback Plan

Revert the implementation PR. The existing fallback remains in place, so Event writes should continue to be protected while the root-cause fix is investigated again.

## Dependencies

- Existing fallback capability and logs from `cypher-param-fallback`.
- Backend pytest environment.

## Success Criteria

- [ ] Audit confirms direct `poll_collector_id` Cypher usage is property-qualified where assigned.
- [ ] Focused backend regression tests fail before and pass after the fix.
- [ ] PR for issue #343 includes fix, tests, and OpenSpec artifacts.
- [ ] Follow-up operational verification checks `cypher-param-fallback` logs trend to zero for 7 days after deploy.
