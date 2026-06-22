# Event Correlation RCA — Operator Notes

Operational recalibration guide for the topology-aware event correlation change shipped in issue #310. The MonitoringConsole UI already collapsed cascades client-side, but the backend data model, the events API, escalation, ITSM ticket creation, and the AI agent all change semantics. This note tells operators what moved and how to handle dashboards, downstream consumers, and incident response.

## What changed

Production event writers across all three active paths now tag cascading events with `correlation_type='PROPAGATED'`, `propagated_from=<root event id>`, and `root_cause_ci_id=<root ci id>`. The root cause keeps `correlation_type='ROOT'`, `root_cause_ci_id=<own ci id>`, and an empty `propagated_from`.

| Writer path | Location | Behavior |
| --- | --- | --- |
| Path A — legacy serial SNMP worker | `backend/engines/snmp_worker.py` (`_refresh_snmp_collection_failures`, `_refresh_icmp_availability_events`, `_refresh_icmp_latency_events`) | Tags via shared `_tag_failure_with_correlation` helper backed by `resolve_correlation_fields(ci_id, severity)`. |
| Path C — leased PostgreSQL-queue polling | `backend/polling/snmp_worker.py` (envelope construction before `event_writer.batch_update_events`) | Pre-tags every envelope; per-cycle memo cache avoids duplicate topology traversal. |
| CLI poll alerts | `backend/engines/cli_worker.py` (CLI_POLL_ALERT CREATE) | Resolves the CI owning the MetricDef, then tags with `resolve_correlation_fields`. Fail-safe ROOT on lookup errors so alerts still fire. |

`_is_authoritative_event(event)` is the canonical helper. Any code that asks "is this event a root cause or just a cascade?" should call it.

## Visible changes for operators

| Signal | Before #310 | After #310 | Why |
| --- | --- | --- | --- |
| Open-event count (MonitoringConsole, dashboards) | Every dependency member shows as an independent incident | Cascading events collapse into the root cause; one open event per dependency chain | Cascades now correctly attribute to the root cause in Neo4j. |
| Escalation count (MQTT, push, on-call) | Every CRITICAL/WARNING cascade member escalated | Only root-cause events escalate | `_is_authoritative_event` gates escalation. |
| ITSM ticket creation | One ticket per affected CI | One ticket per dependency chain (root cause) | Same gating as escalation; ticket text still references the chain. |
| `GET /api/events` default response | Returns every event with `correlation_type='ROOT'` | Returns only ROOT/authoritative events | Propagated events are filtered unless explicitly requested. |
| MonitoringConsole event stream | Visually collapsed via client-side `useEventCorrelation` | Unchanged visually | Frontend already collapsed DEPENDS_ON/HOSTED_ON/CONNECTS_TO cascades. |

## What operators should do

### Recalibrate KPI dashboards

KPI panels that count open events or escalations will drift downward by design. This is correct behavior, not a regression. Recalibrate before the next reporting cycle:

- Review any "open events by severity" panel that doesn't already deduplicate by root cause.
- Review any "escalations per hour" panel; the expected baseline drops by the cascade count.
- Review any MTTR / MTTA panel that assumes one ticket per cascade member.

If your dashboard reads from `GET /api/events` and you need the full forensic stream (ROOT + PROPAGATED), add the `include=propagated` query parameter.

### Recover the full incident chain

For full incident chain visibility — every CI in a cascade, every propagated event — query Neo4j directly or use the opt-in API path.

**Neo4j Cypher** (substitute the root event id):

```cypher
MATCH (root:Event {id: '<root_event_id>'})<-[:PROPAGATED_FROM*]-(downstream:Event)
RETURN downstream.ci_id, downstream.severity, downstream.correlation_type,
       downstream.propagated_from, downstream.root_cause_ci_id
ORDER BY downstream.created_at
```

**Events API**:

```bash
curl '/api/events?include=propagated'
```

`?include=propagated` and `?include=all` are synonyms. Unknown values (including typos like `?include=proagated`) fall back to the safe ROOT-only default.

### Triage downstream consumers

If a downstream service reports "events disappeared" after this change, the cause is almost certainly the default `GET /api/events` filter. Three actions in order:

1. Confirm the consumer wants the full stream. Most do not.
2. If they do, instruct them to add `?include=propagated`.
3. If they want ROOT only, no change is required.

### Roll back if needed

If this causes unexpected issues, revert the PR. The prior behavior (every event tagged `ROOT`) is preserved by `git revert`. No data migration required; the `correlation_type` field is forward-only.

For partial rollback — keep write-side RCA but restore the old unfiltered consumer behavior — revert `_is_authoritative_event` usage in `routers/events.py:get_events` and `services/escalation_notifier.py` while leaving Path A / Path C / CLI tagging in place. Investigate before re-reverting: the unfiltered behavior was the bug.

## What's NOT in this change

The following are intentionally deferred to issue #311 and will land in a follow-up PR:

| Concern | Status | Tracking |
| --- | --- | --- |
| AI agent event filtering in `backend/services/ai_chat_service.py` | The AI agent still surfaces ROOT and PROPAGATED events as if independent. After #310 it sees fewer events from the default events API but still treats each surviving event as an isolated incident. | #311 |
| Path B (`snmp_collector_loop`) re-enable or deprecation | Path B remains disabled as it was before this change. The architectural decision (re-enable with correlation tagging, or deprecate permanently) is a separate review. | #311 |
| Historical event backfill | Events written before this change retain their original `correlation_type` (typically `ROOT`, regardless of whether they were actually cascades). Backfill is a migration that re-runs the correlation logic against the topology at the time the event was opened. | #311 |
| Topology traversal depth (`max_depth=3`) | Unchanged. Cascades deeper than 3 hops still surface as ROOT at the depth-3 ancestor. | Not currently tracked. |
| Audit log filtering | Forensic completeness preserved. Audit logs continue to record every event regardless of `correlation_type`. | N/A |

## Reference

- Issue: https://github.com/alexandervazquez98/next-gen/issues/310
- Follow-up: https://github.com/alexandervazquez98/next-gen/issues/311
- Spec: `openspec/changes/fix-310-event-correlation-rca/spec.md` (REQ-CORR-1 through REQ-CORR-8)
- Design: `openspec/changes/fix-310-event-correlation-rca/design.md`
- Verify report: `openspec/changes/fix-310-event-correlation-rca/verify-report.md`