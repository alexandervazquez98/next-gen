# Event Lifecycle Analysis: Generation → Storage → Retrieval

## 1. Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SNMP/COLLECTOR CYCLE (every 60s)                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  snmp_service.py: run_snmp_cycle_sync()                                      │
│    → snmp_service.py: _collect_metric_sync(ci, metric_def, driver)            │
│        → returns (value, status, error_message)                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  snmp_service.py: store_metric_result(ci, metric_def, value,               │
│                                    poll_status, err_msg, driver)             │
│                                                                              │
│  1. Determine severity from criticality level (1=INFO, 2=WARNING, 3=CRIT)   │
│  2. Threshold check: if val >= metric.critical → is_breach=True             │
│                     if val >= metric.warning  → is_breach=True                │
│  3. If numeric_value: insert into PostgreSQL via insert_metric_value()       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
              is_breach = TRUE              is_breach = FALSE
                    │                               │
                    ▼                               ▼
    ┌────────────────────────────┐    ┌──────────────────────────────┐
    │ CHECK FOR EXISTING EVENT   │    │     RECOVERY PATH            │
    │ (ci_id, metric_id,        │    │                              │
    │  status IN OPEN/ACK/REC)  │    │ Only for events with         │
    └────────────────────────────┘    │ correlation_type='ROOT'     │
                    │                 │                              │
         ┌──────────┴──────────┐     │ Sets ROOT event to          │
         │                     │      │ RECOVERED, then calls:      │
    existing EXISTS    NO EXISTING   │ propagate recovery to       │
         │                     │      │ children via Cypher CALL{}  │
         ▼                     ▼      └──────────────────────────────┘
  ┌────────────┐    ┌────────────────────────────┐
  │ UPDATE     │    │ CREATE NEW Event           │
  │ last_seen, │    │                            │
  │ status=OPEN│    │ 1. resolve_event_snapshot()│
  │ recovered_ │    │    (business context)      │
  │ at=NULL    │    │                            │
  └────────────┘    │ 2. Topology correlation    │
                    │    find_open_parent_event() │
                    │    → PROPAGATED if parent   │
                    │    → ROOT if no parent      │
                    │                            │
                    │ 3. CREATE (e:Event)        │
                    │    MERGE (ci)-[:HAS_EVENT]->(e) │
                    │    MERGE (e)-[:TRIGGERED_BY]->(metric) │
                    └────────────────────────────┘
                                    │
                                    ▼
                    ┌────────────────────────────────────────────┐
                    │          Neo4j Event Node                   │
                    │  • id, ci_id, metric_id                    │
                    │  • status (OPEN/ACK/CLOSED/RECOVERED)       │
                    │  • severity (CRITICAL/WARNING/INFO)        │
                    │  • message, created_at, last_seen          │
                    │  • propagated_from, correlation_type        │
                    │  • root_cause_ci_id, business_service_*     │
                    │  • comments[] (audit trail)                 │
                    └────────────────────────────────────────────┘
                                    ▲
                                    │
┌──────────────────────────────────────────────────────────────────────────────┐
│                    API RETRIEVAL LAYER                                        │
│                                                                               │
│  GET  /events                    → event_service.get_events()                 │
│  GET  /events/{event_id}         → event_service.get_event_detail()           │
│  GET  /events/related/{ci_id}    → event_service.get_related_events()         │
│  POST /events/{event_id}/ack      → event_service.ack_event()                  │
│  POST /events/{event_id}/close    → event_service.close_event()               │
│  POST /events/{event_id}/comment  → event_service.add_event_comment()        │
│  POST /events/prune               → event_service.prune_recovered_events()     │
│  GET  /events/bulk/stream-progress → SSE streaming batch pruner              │
│  POST /events/{event_id}/diagnose  → event_service.run_event_diagnostic()     │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2. Which Database Stores Events

**Neo4j ONLY** — `nexgen_neo4j` container.

No `events` table exists in PostgreSQL (`nexgen_auth`, `nexgen_postgres`). The search for `INSERT INTO events` returned no results.

| DB | Contains Events? |
|----|-----------------|
| Neo4j (`nexgen_neo4j`) | ✅ YES — 3,337 Event nodes |
| PostgreSQL (`nexgen_auth`) | ❌ NO |
| PostgreSQL (`nexgen_postgres`) | ❌ NO |
| TimescaleDB (`nexgen_postgres`) | ❌ NO |

Metric numeric values ARE stored in **PostgreSQL** (`insert_metric_value()`) for time-series queries.

## 3. Event Node Properties and Relationships

### Neo4j Event Node Properties
```json
{
  "id": "randomUUID()",
  "ci_id": "CI node id",
  "metric_id": "MetricDef node id",
  "status": "OPEN | ACK | CLOSED | RECOVERED",
  "severity": "CRITICAL | WARNING | INFO",
  "message": "Human-readable description",
  "created_at": "datetime()",
  "last_seen": "datetime()",
  "ack": false,
  "ack_at": "datetime() | null",
  "ack_by": "username | null",
  "closed_at": "datetime() | null",
  "closed_by": "username | null",
  "recovered_at": "datetime() | null",
  "comments": ["list of audit messages"],
  "business_service_id": "snapshot",
  "business_service_name": "snapshot",
  "business_service_tier": "snapshot",
  "owner_t1/2/3": "snapshot",
  "impacted_users": "snapshot",
  "site": "snapshot (ci.location_name)",
  "service_catalog_id": "snapshot",
  "service_category": "snapshot",
  "service_tier": "snapshot",
  "sla_minutes": "snapshot",
  "propagated_from": "parent_event_id | null",
  "correlation_type": "ROOT | PROPAGATED",
  "root_cause_ci_id": "ci id of root cause | null"
}
```

### Relationships
| From | Type | To | Notes |
|------|------|----|-------|
| CI | `HAS_EVENT` | Event | Ci creates events |
| Event | `TRIGGERED_BY` | MetricDef | What metric caused event |

**Current counts:**
- 3,064 events have `TRIGGERED_BY` relationship
- 273 events have **NO** `TRIGGERED_BY` (orphaned)

## 4. Gaps, Bugs, and Inconsistencies Found

### BUG #1: Orphan Events Without MetricDef Link (273 events, 8.2%)
**Severity: HIGH**

Events with IDs like `backup-20260503060000`, `backup-20260504060000`, etc. have:
- `status = OPEN`
- No `TRIGGERED_BY` relationship to MetricDef
- Created at 06:00:00 daily — suggests a backup job is creating them

These events:
- Cannot be retrieved via `get_events()` endpoint (the query uses `MATCH (e:Event)<-[:HAS_EVENT]-(ci:CI) MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)` which REQUIRES the TRIGGERED_BY relationship)
- Would cause `get_event_detail()` to fail since it also requires `TRIGGERED_BY`
- Break the audit trail - no way to know what metric triggered them

**Root cause:** Unknown code path creates Event nodes directly without setting `metric_id` or linking to MetricDef.

### BUG #2: Very Low Propagation Rate
**Severity: MEDIUM**

Only **13** events have `correlation_type = 'PROPAGATED'` out of 3,337 total events.

The infrastructure for `can_propagate`, `find_open_parent_event()`, and propagation during recovery is fully implemented, but almost no events are being propagated. Either:
1. Most CIs don't have parent CI relationships (DEPENDS_ON/HOSTED_ON/CONNECTS_TO)
2. The propagation check has a bug
3. Parent events aren't being found properly

### Observation #3: Business Context Snapshot Drift
When an Event is created, `resolve_event_snapshot()` captures the BusinessService and ServiceCatalog state at that moment. The `_build_business_context()` function later uses `_pick_value()` to merge snapshot vs resolved values, with a `source_state` of `"snapshot"`, `"resolved"`, or `"mixed"`.

This means events can carry stale business service info. This is by design but worth noting.

### Observation #4: Prune Logic Is Conservative
`prune_recovered_events()` only closes events where:
- `status = 'RECOVERED'`
- `ack IS NULL OR ack = false` (not acknowledged)
- `comments IS NULL OR size(comments) = 0` (no comments added)

This means manually acknowledged or commented RECOVERED events survive the prune — they must be explicitly closed.

## 5. How Recovered/Closed Events Are Handled

### Recovery Path (when metric returns to OK)
```
store_metric_result() with is_breach = FALSE
    │
    ▼
MATCH (n:CI {id: $nid})-[:HAS_EVENT]->(e:Event {metric_id: $mid})
WHERE e.status IN ['OPEN', 'ACK'] AND e.correlation_type = 'ROOT'
SET e.status = 'RECOVERED', e.recovered_at = datetime(), e.message = $msg
    │
    ├──► Then via Cypher CALL{}:
    │    MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
    │    WHERE pe.root_cause_ci_id = e.ci_id
    │      AND pe.correlation_type = 'PROPAGATED'
    │      AND pe.status IN ['OPEN', 'ACK']
    │      AND m.can_propagate = true
    │    SET pe.status = 'RECOVERED', pe.recovered_at = datetime()
    │
    ▼
    Event is now RECOVERED, waiting for prune
```

### Prune Path (closing RECOVERED events)
```
POST /events/prune  →  prune_recovered_events()
    │
    ▼
MATCH (e:Event)
WHERE e.status = 'RECOVERED'
  AND (e.ack IS NULL OR e.ack = false)
  AND (e.comments IS NULL OR size(e.comments) = 0)
SET e.status = 'CLOSED', e.closed_at = datetime(), e.closed_by = $user
```

### Manual Close Path
```
POST /events/{event_id}/close  →  close_event()
    │
    ▼
Validate: requires "Causa raíz:" and "Nota:" in comment_message
         (or forced=True with reason)
    │
    ▼
MATCH (e:Event {id: $eid})
SET e.status = 'CLOSED', e.closed_at = datetime(), e.closed_by = $user
SET e.comments = e.comments + audit_message
```

## 6. Whether Events Are Properly Linked to CIs and Metrics

### CI Link: ✅ YES
`(ci:CI)-[:HAS_EVENT]->(e:Event)` — Every event creation creates this link via `MERGE (n)-[:HAS_EVENT]->(e)`.

### MetricDef Link: ⚠️ PARTIAL
`(e:Event)-[:TRIGGERED_BY]->(m:MetricDef)` — Created for 3,064 out of 3,337 events (91.8%).

**273 events (8.2%) are orphaned** — no TRIGGERED_BY relationship, no metric_id field set properly. These events:
- Cannot be queried via any API endpoint
- Cannot be diagnosed
- Break `get_event_detail()` which does `OPTIONAL MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)` then uses `metric_data.get("name")` which would fail for orphan events

### Propagation Links: ⚠️ WEAK
`(pe:Event {correlation_type='PROPAGATED'})-[:TRIGGERED_BY]->(m:MetricDef)` — only 13 propagated events exist.

`find_open_parent_event()` traverses via `DEPENDS_ON|HOSTED_ON|CONNECTS_TO` relationships up to 3 levels deep. The `root_cause_ci_id` is set to track the ultimate root cause CI.

---

## Summary Table

| Aspect | Status | Details |
|--------|--------|---------|
| Events stored in | Neo4j only | 3,337 total nodes |
| PostgreSQL events | None | No events table |
| CI → Event link | ✅ Working | `HAS_EVENT` relationship |
| Event → MetricDef link | ⚠️ 91.8% | 273 orphaned events without `TRIGGERED_BY` |
| Propagation | ⚠️ Rare | Only 13 PROPAGATED events |
| Recovery auto-propagation | ✅ Implemented | Cypher CALL{} block |
| Orphan event source | ❓ Unknown | IDs like `backup-YYYYMMDDHHMMSS` |
| Prune cleanup | ✅ Working | Conservative (requires no ack/comments) |
| Business context snapshot | ✅ By design | Stored at creation, can drift |

---

## Code References

| File | Function | Lines | Purpose |
|------|----------|-------|---------|
| `backend/services/snmp_service.py` | `store_metric_result()` | 277–490 | Core event generation & threshold logic |
| `backend/services/snmp_service.py` | `resolve_event_snapshot()` | 68–108 | Capture business context at event creation |
| `backend/services/snmp_service.py` | line ~440 | `find_open_parent_event()` call | Topology correlation |
| `backend/services/event_service.py` | `get_events()` | 394–416 | API: list events |
| `backend/services/event_service.py` | `ack_event()` | 476–502 | API: acknowledge |
| `backend/services/event_service.py` | `close_event()` | 505–545 | API: manual close |
| `backend/services/event_service.py` | `prune_recovered_events()` | 566–584 | API: bulk close RECOVERED |
| `backend/routers/events.py` | Router | 10–245 | All event API endpoints |
| `backend/repositories/topology_repo.py` | `find_open_parent_event()` | 369–408 | Parent event traversal |
