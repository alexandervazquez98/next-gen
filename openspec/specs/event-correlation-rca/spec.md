# Topology-Aware Event Correlation RCA Specification

## Capability

Topology-aware event correlation: production collectors tag cascading events as `PROPAGATED` with `root_cause_ci_id`; authoritative consumers filter them by default while forensic records remain intact.

## Requirements

### Requirement: REQ-CORR-1 — Write-side correlation for Path A

`backend/engines/snmp_worker.py:271-272,326,405-406` SHALL call `find_open_parent_event(ci_id)` before writing each new Path A event. If a parent open event exists, it SHALL write `correlation_type='PROPAGATED'`, `propagated_from=<parent event id>`, `root_cause_ci_id=<root ci id>`; otherwise it SHALL write `correlation_type='ROOT'`, `root_cause_ci_id=<own ci_id>`.

#### Scenario: Path A root failure

- Given CI A has no open upstream parent event
- When Path A writes A's failure event
- Then A is stored as `ROOT` with `root_cause_ci_id='A'`

#### Scenario: Path A propagated downstream failure

- Given CI A has an open event and CI E depends on A
- When Path A writes E's failure event while A remains open
- Then E is stored as `PROPAGATED` with `propagated_from` equal to A's event id and `root_cause_ci_id='A'`

#### Scenario: Path A downstream without parent

- Given CI E has no open upstream parent event
- When Path A writes E's failure event
- Then E is stored as `ROOT` with `root_cause_ci_id='E'`

#### Test coverage: mandatory multi-CI Path A chain test

The mandatory multi-CI Path A chain integration test (`backend/tests/test_path_a_rca_chain.py`) covers the write-side correlation behavior of this requirement end-to-end against a `MockNeo4jDriver`. PR 1's T5 covers write-side behavior only: Event node shape, `correlation_type`/`propagated_from`/`root_cause_ci_id`, and per-CI severity. Consumer-side assertions (`escalation_notifier` call counts, `GET /api/events` default-vs-opt-in) are tested in PR 2 via T9/T10, NOT in T5.

### Requirement: REQ-CORR-2 — Write-side correlation for Path C

`backend/polling/snmp_worker.py` SHALL pre-tag every envelope with `correlation_type`, `propagated_from`, and `root_cause_ci_id` before `backend/polling/event_writer.py:batch_update_events`; `event_writer.py:211-214` and `build_event_rows` SHALL preserve those fields.

#### Scenario: Path C root failure

- Given CI A has no open upstream parent event
- When Path C builds and writes A's envelope
- Then the persisted row is `ROOT` with `root_cause_ci_id='A'`

#### Scenario: Path C propagated downstream failure

- Given CI A has an open event and CI E depends on A
- When Path C builds and writes E's envelope
- Then the persisted row is `PROPAGATED` with `propagated_from` equal to A's event id and `root_cause_ci_id='A'`

#### Scenario: Path C writer round-trip preserves metadata

- Given an envelope contains `PROPAGATED`, `propagated_from`, and `root_cause_ci_id`
- When `event_writer.build_event_rows` converts it for batch write
- Then no correlation field is dropped or rewritten to `ROOT`

### Requirement: REQ-CORR-3 — Write-side correlation for CLI poll alerts

`backend/engines/cli_worker.py:350-361` SHALL apply the same correlation tagging to `CLI_POLL_ALERT` events as Path A applies to ICMP availability events.

#### Scenario: CLI alert propagated

- Given a CLI poll alert is raised for a CI with a failing upstream parent
- When `cli_worker.py` writes the alert
- Then the event is `PROPAGATED` with the parent's event id and root CI

#### Scenario: CLI alert root

- Given a CLI poll alert is raised for a CI with no failing upstream parent
- When `cli_worker.py` writes the alert
- Then the event is `ROOT` with `root_cause_ci_id` equal to its own CI

### Requirement: REQ-CORR-4 — Authoritative event helper

`backend/services/event_service.py` SHALL expose `_is_authoritative_event(event)` returning `False` only when `correlation_type == 'PROPAGATED'`. `_is_authoritative_availability_event` at `event_service.py:466` SHALL delegate to it or remain semantically consistent.

#### Scenario: ROOT is authoritative

- Given an event has `correlation_type='ROOT'`
- When `_is_authoritative_event` evaluates it
- Then it returns `True`

#### Scenario: PROPAGATED is non-authoritative

- Given an event has `correlation_type='PROPAGATED'`
- When `_is_authoritative_event` evaluates it
- Then it returns `False`

#### Scenario: Missing type is backward-compatible

- Given a legacy event has no `correlation_type`
- When `_is_authoritative_event` evaluates it
- Then it returns `True`

### Requirement: REQ-CORR-5 — Escalation gating

`backend/services/escalation_notifier.py:53-91` SHALL NOT emit an escalation when the triggering event is non-authoritative.

#### Scenario: Critical propagated event suppressed

- Given a CRITICAL event is `PROPAGATED`
- When escalation notification is evaluated
- Then no escalation is published

#### Scenario: Critical root event preserved

- Given a CRITICAL event is `ROOT`
- When escalation notification is evaluated
- Then the existing escalation is published

#### Scenario: Warning propagated event suppressed

- Given a WARNING event is `PROPAGATED`
- When escalation notification is evaluated
- Then no escalation is published

### Requirement: REQ-CORR-6 — Events API filtering

`backend/routers/events.py` `get_events` SHALL return authoritative events by default and SHALL accept `include=propagated` to include `PROPAGATED` events.

#### Scenario: Default API filters propagated

- Given stored events include one `ROOT` and one `PROPAGATED`
- When `GET /api/events` is called without `include`
- Then only the `ROOT` event is returned

#### Scenario: API opt-in includes propagated

- Given stored events include one `ROOT` and one `PROPAGATED`
- When `GET /api/events?include=propagated` is called
- Then both events are returned

#### Scenario: Existing tests opt in or update expectation

- Given a test expects all events from `get_events`
- When this change is applied
- Then the test either expects authoritative-only default results or calls `include=propagated`

### Requirement: REQ-CORR-7 — Frontend CONNECTS_TO grouping

`frontend/hooks/useEventCorrelation.ts:89` SHALL collapse `CONNECTS_TO` cascades like `DEPENDS_ON` and `HOSTED_ON`; downstream open CRITICAL/WARNING events SHALL be absorbed into the provider group with `cause: 'UPSTREAM_DEPENDENCY_FAILURE'`.

#### Scenario: DEPENDS_ON preserved

- Given a downstream CI depends on a provider with an open event
- When the hook groups events
- Then existing `DEPENDS_ON` collapse behavior remains unchanged

#### Scenario: HOSTED_ON preserved

- Given a hosted CI has an open event and its host has an open event
- When the hook groups events
- Then existing `HOSTED_ON` collapse behavior remains unchanged

#### Scenario: CONNECTS_TO collapses

- Given a downstream CI has an open CRITICAL/WARNING event and its `CONNECTS_TO` provider has an open event
- When the hook groups events
- Then the downstream event is absorbed into the provider group with `UPSTREAM_DEPENDENCY_FAILURE`

#### Scenario: Mixed chain deepest relationship wins

- Given one chain contains `DEPENDS_ON`, `HOSTED_ON`, and `CONNECTS_TO`
- When multiple upstream matches exist
- Then the downstream CI is grouped under the deepest matched provider relationship only

### Requirement: REQ-CORR-8 — Traversal depth and CONNECTS_TO inclusion

`find_open_parent_event` in `backend/repositories/topology_repo.py:407-443` SHALL continue to walk `[:DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3]` upstream with no depth change.

#### Scenario: One-hop parent found

- Given an upstream open parent exists one hop away
- When `find_open_parent_event(ci_id)` runs
- Then that parent event is returned

#### Scenario: Three-hop parent found

- Given an upstream open parent exists three hops away
- When `find_open_parent_event(ci_id)` runs
- Then that parent event is returned

#### Scenario: 3-hop dependency chain resolves root cause

- Given a linear dependency chain A→B→C→D where A is failing with an open event
- When D's metric crosses threshold and the collector runs
- Then D gets a `PROPAGATED` event with `root_cause_ci_id='A'` and `propagated_from` equal to A's event id

#### Scenario: Four-hop parent ignored

- Given the nearest upstream open parent is four hops away
- When correlation tagging runs
- Then no parent is selected and `root_cause_ci_id` is the event's own CI id

#### Scenario: 4-hop dependency chain exceeds traversal depth

- Given a linear dependency chain A→B→C→D→E where A is failing with an open event
- When E's metric crosses threshold and the collector runs
- Then E gets a `ROOT` event with `root_cause_ci_id='E'` (not 'A'), because the topology traversal depth is capped at 3

#### Scenario: Unrelated CI ignored

- Given another open event exists outside the CI's upstream chain
- When `find_open_parent_event(ci_id)` runs
- Then the unrelated event is not selected as parent

## Non-Goals

- AI agent event filtering is deferred to issue #311.
- Path B re-enable or deprecation is deferred to issue #311.
- Backfill migration of historical events is deferred to issue #311.
- Audit log filtering is out of scope; forensic completeness keeps both ROOT and PROPAGATED records.
- Topology traversal depth changes are out of scope.
- KPI/dashboard rebalancing is out of scope; count drift is accepted.

## Migration / Rollout Notes

No data migration required for this change. Historical events retain their original `correlation_type` values; backfill is tracked separately in #311. Rollout should communicate lower default event-feed, escalation, ITSM, and KPI counts for cascades.

## Open Questions

All questions from explore resolved in proposal; none remaining for design.

## Out of Scope

- AI agent event filtering in `backend/services/ai_chat_service.py` — tracked by #311.
- Path B (`backend/services/snmp_service.py:snmp_collector_loop`) re-enable or deprecation — tracked by #311.
- Backfill migration of historical events with wrong/empty `correlation_type` — tracked by #311.
- Audit log filtering; forensic completeness preserves both ROOT and PROPAGATED records.
- Topology traversal depth changes (`max_depth=3` stays).
- KPI/dashboard rebalancing beyond the CHANGELOG note.

## Source

Lifted from the change folder:
`openspec/changes/archive/2026-06-21-fix-310-event-correlation-rca/spec.md`

Original PR: bundled chained PR (PR 1 + PR 2 + PR 3) on `fix/310-event-correlation-rca` against `main`. Closes #310.
Follow-up work tracked by #311.

Upstream context: topology primitives (`find_open_parent_event`, `_is_authoritative_availability_event`, recovery cascades in `engines/snmp_worker.py:355-378,436-459,462-491` and `polling/event_writer.py:387-393,427-434`) already existed in isolation. The asymmetry was that the WRITE side hardcoded `correlation_type='ROOT'`, so the recovery side never had PROPAGATED descendants to cascade-close. This change closes the loop.
