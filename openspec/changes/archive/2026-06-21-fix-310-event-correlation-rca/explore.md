# Explore: fix-310-event-correlation-rca — production collector hardcodes ROOT, breaking topology-based RCA

## Change

`fix-310-event-correlation-rca`

GitHub Issue: [#310](https://github.com/alexandervazquez98/next-gen/issues/310)

## Goal

Restore topology-based root cause analysis (RCA) for events produced by the production SNMP/ICMP collector paths, so downstream consumers (AI agent, MQTT escalation pipeline, ITSM ticket creation, audit logs, `GET /api/events`) treat cascading failures as one incident with the root-cause CI/event flagged — matching what the MonitoringConsole already shows via client-side grouping.

## Current behavior observed

### What already exists and is correct in isolation

The system already has the primitives needed for topology-based RCA:

- `backend/repositories/topology_repo.py:407-443` — `find_open_parent_event(ci_id, max_depth=3)` walks `:DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3` upstream from a CI and returns the first `OPEN`/`ACK` parent event with `parent_event_id`, `root_cause_ci_id`, and `correlation_type`.
- `backend/services/snmp_service.py:543-558` — `snmp_collector_loop` (the in-process, **currently disabled** collector) calls `find_open_parent_event` and correctly tags new events as `correlation_type='PROPAGATED'` with `propagated_from` + `root_cause_ci_id`, honoring `metric_def.can_propagate`.
- `backend/services/event_service.py:466-474` — `_is_authoritative_availability_event` defines the pattern that should be reused: `event_type == 'AVAILABILITY' AND availability_source ∈ {PING, ICMP} AND correlation_type != 'PROPAGATED'`.
- `backend/services/event_service.py:173-207` — `_public_event_summary` exposes the `propagated` flag to API consumers when `correlation_type == 'PROPAGATED'`.
- `backend/tests/test_event_correlation.py` (447 lines, sections 4.1–4.5) — proves the RCA logic in isolation: `find_open_parent_event` traversal depth/rel types, ROOT vs PROPAGATED assignment, recovery cascades, 3-level CI chains, and the API `propagated=true` exposure.
- `backend/engines/snmp_worker.py:355-378, 436-459, 462-491` — the **recovery** paths in the legacy worker correctly cascade-recover PROPAGATED descendants when the ROOT recovers (lines 369-375, 450-456, 482-488). The asymmetry: WRITE paths are broken, RECOVERY paths already work.
- `backend/polling/event_writer.py:107-110, 278-346, 387-434` — the new event writer **preserves** correlation metadata when present and **propagates recovery cascades** for ROOT events (lines 387-393, 427-434). It does not **compute** the correlation — it only reads `metadata.correlation_type`, which no producer sets.

### What is broken (the audit-confirmed gap)

- `backend/engines/snmp_worker.py:271-272, 326, 405-406` — ICMP availability, ICMP latency, and SNMP collection-failure events hardcode `correlation_type: 'ROOT'`, `root_cause_ci_id: row.node_id`. The CREATE branches always treat the failing CI as the root cause.
- `backend/engines/cli_worker.py:350-361` — CLI metric alert events are created as `type: 'CLI_POLL_ALERT'` with no `correlation_type` at all (third legacy path, even more broken than the SNMP paths).
- `backend/polling/event_writer.py:211-214` — defaults `correlation_type` to `'ROOT'` from `metadata` when the producer hasn't tagged the envelope.
- `backend/polling/snmp_worker.py` (the new leased producer, `run_leased_snmp_worker_once`) never pre-tags envelopes with `correlation_type` or `propagated_from`. `polling/snmp_executor.py` also doesn't touch correlation. The leased path therefore inherits the ROOT default from `event_writer.build_event_rows`.
- `docker-compose.yml:81` — `DISABLE_BACKEND_COLLECTOR=true` keeps the only fully RCA-correct path (Path B: `snmp_collector_loop` in `snmp_service.py`) dormant in production.
- `frontend/hooks/useEventCorrelation.ts:87-112` — client-side grouping only matches `DEPENDS_ON` and `HOSTED_ON`; it ignores `CONNECTS_TO`, so network-only topologies get no UI grouping. The hook reads server data without trusting backend `propagated` flags, masking the server-side gap.
- `backend/services/escalation_notifier.py:53-91` — does not filter on `correlation_type`; publishes to `alerts/human/escalation` for any CRITICAL event passed in, so ROOT and cascading PROPAGATED events both trigger escalations.
- `backend/routers/events.py` `get_events` — returns the full event list without correlating/folding by `root_cause_event_id` or `propagated_from`.
- `backend/services/ai_chat_service.py:320-338` — exposes `correlation_type` and `root_cause_ci_id` in the compact event summary, but downstream prompt/behavior toward grouped-vs-separate incidents has not been audited.

### Three event-write paths

| Path | Active in prod? | Does RCA at write time? | Hardcoded ROOT? |
|---|---|---|---|
| **A**: `backend/engines/snmp_worker.py:poll_snmp` (legacy, in-process or `snmp-engine` service) | **YES** | NO | **YES** — CREATE branches at lines 266-273, 320-327, 401-407 hardcode `correlation_type: 'ROOT'`, `root_cause_ci_id: row.node_id` |
| **B**: `backend/services/snmp_service.py:snmp_collector_loop` (in-process) | **NO** (disabled via `DISABLE_BACKEND_COLLECTOR=true` at `docker-compose.yml:81` and `main.py:299-304`) | YES — lines 543-558 call `find_open_parent_event` and tag `correlation_type='PROPAGATED'` when a parent event exists | NO |
| **C**: `backend/polling/snmp_worker.py:run_leased_snmp_worker_once` + `polling/event_writer.py:batch_update_events` | **YES when `POLLING_SNMP_LEASED_WORKER=true`** | NO — `polling/snmp_worker.py` and `polling/snmp_executor.py` never set `correlation_type`; writer preserves metadata but defaults to `'ROOT'` at line 211 | **YES** (writer default at line 211) |

### Three downstream consumers that do not filter PROPAGATED

- `backend/services/escalation_notifier.py:53-91` — `notify_critical_event_escalation` builds and publishes to MQTT for every CRITICAL event it receives; no `correlation_type` check, so cascading events trigger duplicate escalations.
- `backend/routers/events.py` `get_events` (and any aggregate event-feed consumer) — returns events without grouping by `root_cause_event_id` / `propagated_from`.
- `backend/services/ai_chat_service.py` (compact event summary at lines 320-338, harness results built around lines 320+) — surfaces `correlation_type` / `root_cause_ci_id` in payloads, but downstream prompt instructions and `event_list` / `availability_check` templates do not currently group by `root_cause_event_id`, so the AI may treat ROOT + cascading as two unrelated incidents.

### Recovery side is already correlation-aware (asymmetry finding)

The legacy worker's **recovery** queries (`engines/snmp_worker.py:355-378`, `:436-459`, `:462-491`) and `polling/event_writer.py:387-393, 427-434` already cascade-recover PROPAGATED descendants when the ROOT recovers. They filter on `coalesce(e.correlation_type, 'ROOT') = 'ROOT'` and look up `pe.propagated_from = e.id AND pe.correlation_type = 'PROPAGATED'`. The asymmetry: the recovery code expects WRITE-side PROPAGATED events to exist; the WRITE side never produces them. Fixing only the WRITE side closes the loop.

## Problem statement

The system has the right primitives for topology-based RCA, but every production write path tags new events as `ROOT` regardless of whether a parent CI already has an open event. The result:

- MonitoringConsole UI masks the bug via client-side grouping (`useEventCorrelation.ts:87-115`).
- AI agent, MQTT escalation pipeline, ITSM ticket creation, audit logs, and `GET /api/events` all see two unrelated incidents when CI E fails downstream of CI A.
- Recovery cascades are correctly wired, so once the WRITE side is fixed, PROPAGATED descendants will automatically be closed when their root cause resolves — no separate fix needed on the recovery side.

## User-visible symptom

Operators see the right thing in MonitoringConsole (client-side grouping), but:

- Every CRITICAL event in a cascade fires its own MQTT escalation and ITSM ticket.
- The AI agent may propose closing both events independently, even though one root cause could resolve the chain.
- Audit logs and `GET /api/events` show duplicate unrelated incidents.
- Network-only topologies (CONNECTS_TO-only) get no UI grouping at all because `useEventCorrelation.ts:89` ignores that relationship.

## Implementation shape for later phases

Suggested scope (proposal/spec/design will refine):

1. **Centralize correlation computation.** Extract a helper next to `_is_authoritative_availability_event` (or a new `event_correlation.py`) that, given a `(ci_id, metric_def)`, calls `find_open_parent_event` and returns `(correlation_type, propagated_from, root_cause_event_id, root_cause_ci_id)`, honoring `can_propagate`. The pattern already exists at `snmp_service.py:543-558`.
2. **Patch Path A** — `engines/snmp_worker.py` CREATE branches at lines 266-273, 320-327, 401-407 — compute correlation instead of hardcoding `ROOT`.
3. **Patch Path C** — `polling/snmp_worker.py` / `polling/snmp_executor.py` — call the helper before enqueuing or before writing, so the envelope reaches `event_writer.build_event_rows` already tagged.
4. **Optionally patch Path B's dormancy** — leave `DISABLE_BACKEND_COLLECTOR=true` for now (operational decision; explicit out-of-scope).
5. **Optional:** extend `useEventCorrelation.ts` to include `CONNECTS_TO` so network-only topologies also get UI grouping; align with the backend `find_open_parent_event` traversal.
6. **Decide whether downstream consumers should filter PROPAGATED** (escalation_notifier, get_events, AI prompt). This is the consumer-side question — see Open Questions.
7. **Add tests** that exercise the production collector write paths (Path A and Path C) and assert PROPAGATED tagging across 1-, 2-, and 3-deep chains, plus a `can_propagate=false` opt-out case.

## Non-goals

- Do not redesign the correlation engine or migrate from a generic helper to a complex rule engine.
- Do not remove the `_is_authoritative_availability_event` helper; the new helper is for write-time correlation, not read-time grouping.
- Do not change the topology traversal direction or max depth (3) without a separate change.
- Do not re-enable `snmp_collector_loop` (Path B) by default; that is an operational decision owned elsewhere.
- Do not modify `polling/event_writer.py`'s recovery cascade logic — it is correct.
- Do not add a backfill migration for existing inconsistent `correlation_type` data unless explicitly approved; this is a behavior fix going forward.
- Do not touch the CLI poll alert path (`engines/cli_worker.py:341-365`) in this change unless scope is expanded — it is a separate event type with no correlation today and is not on the SNMP/ICMP path. Flag as a known third gap.

## Risks

- **Topology traversal cost.** `find_open_parent_event` runs a Cypher `*1..3` traversal per new event. Under burst conditions (many CIs failing simultaneously), this adds load on Neo4j. Mitigation: cache or rate-limit; observe in verify phase.
- **Recovery cascade loop.** If a CI has both a parent and a child with concurrent writes, a recovery round-trip could chain. Mitigation: the existing `propagated_from = e.id` filter in recovery queries already breaks loops; verify with a test.
- **Telemetry drift.** Switching write paths from ROOT to PROPAGATED changes downstream counts. KPI dashboards that count "open events" or "CRITICAL events" will see different numbers (one root, many cascades). Mitigation: surface `root_cause_event_id` so dashboards can roll up.
- **CONNECTS_TO semantics.** Treating CONNECTS_TO as an upstream dependency means a single network link can cause many CI nodes to be tagged PROPAGATED. Mitigation: keep traversal depth at 3 and consider a `network_propagation` flag on the relationship.
- **Tests can't observe production.** Existing unit tests cover the topology helper in isolation. New tests should mock `find_open_parent_event` inside the engine modules to assert the engine calls it with the right args.
- **Consumer-side drift.** Filtering PROPAGATED in escalation_notifier may break operator expectations (no more dual alerts). Mitigation: leave behavior unchanged unless the proposal explicitly opts in.

## Open questions for proposal / spec / design

1. **Should we re-enable Path B (`snmp_collector_loop`) or fix Path A inline? Or both?** Operationally, re-enabling Path B is one config flag. Code-wise, Path A is the actively used path. The proposal should pick one primary fix and whether Path B becomes a fallback.
2. **Generic helper vs. extend `_is_authoritative_availability_event`?** The existing helper is read-side (groups authoritative events). The new write-side correlation helper is a separate concern. A single `_compute_event_correlation(ci_id, metric_def)` helper colocated with `find_open_parent_event` (or a new `services/event_correlation_service.py`) keeps responsibilities clean. Spec phase should pick.
3. **Should `CONNECTS_TO` be in the topology RCA traversal, or stay network-only (no impact propagation)?** The backend `find_open_parent_event` already includes it; the frontend hook does not. Aligning them is in-scope for the hook, but the backend traversal is currently network-inclusive.
4. **Do we need a migration for existing events with inconsistent `correlation_type`?** If events were created as ROOT in the past, they may be missing `propagated_from` and `root_cause_ci_id`. A backfill could recompute. Out of scope unless explicitly approved.
5. **What is the relationship between `correlation_type` and `can_propagate`?** Should a metric's `can_propagate=false` opt-out also block events from being marked PROPAGATED on that metric? The current code in `snmp_service.py:548` gates on `can_propagate`; the new helper should preserve this.
6. **Should `escalation_notifier` filter PROPAGATED events to avoid duplicate escalations?** Same question for `get_events` rollup and the AI agent's `event_list` harness. Either filter at the source (consumer-side) or expose `propagated=true` and let consumers decide. Spec phase should decide.
7. **How do we test E2E that the production collector now performs RCA?** The current tests use direct calls to `find_open_parent_event`. New tests should mock `find_open_parent_event` inside the engine modules (engines/snmp_worker.py, polling/snmp_worker.py) and assert CREATE-branch correlation_type/propagated_from/root_cause_ci_id.
8. **CLI poll alert gap (`engines/cli_worker.py:350-361`).** Should this change also tag CLI_POLL_ALERT events with correlation_type, or explicitly defer to a follow-up change? Recommend defer.
9. **Should the MonitoringConsole UI hook (`useEventCorrelation.ts`) trust backend `propagated` flags or continue computing client-side?** Today it computes client-side from topology links. With backend correlation, the hook could short-circuit when `propagated=true` is set. UX implication: faster render, less link data shipped.
10. **Are there metrics/KPIs that count open events and will break when the same incident now produces one ROOT + N PROPAGATED instead of N independent ROOTs?** Surface to the user so they can adjust dashboards if needed.

## Recommended next phase

Proceed to proposal with a first slice focused on:

- Introduce a single write-side correlation helper.
- Patch Path A (legacy `engines/snmp_worker.py` CREATE branches).
- Patch Path C (`polling/snmp_worker.py` / `polling/snmp_executor.py` pre-tag, or `event_writer.build_event_rows` enrichment).
- Add tests asserting PROPAGATED tagging across 1/2/3-deep chains and `can_propagate=false` opt-out.
- Update `useEventCorrelation.ts` to include `CONNECTS_TO` (small frontend change).
- Defer: Path B re-enable, CLI poll alert path, escalation_notifier filtering, backfill migration.

Verify phase will run existing `backend/tests/test_event_correlation.py`, new tests for the production collector paths, and a smoke test in the MonitoringConsole UI.