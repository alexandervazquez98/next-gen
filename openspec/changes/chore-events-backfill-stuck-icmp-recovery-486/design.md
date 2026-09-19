# Design: chore(events): backfill stuck ICMP recovery events post-#485

## Purpose

Document the bounded design of the one-shot backfill script so the cascade Cypher, audit marker policy, idempotency rules, and rollback semantics are inspectable before code lands. The design is cross-cutting (touches `_recover_icmp_*` symmetry, MTTR filter, audit schema) and modifies production data, so `design.md` is required by `openspec/config.yaml` (`phase_rules.design.required_for_cross_cutting_or_risky_changes: true`).

## Architecture

```
                ┌──────────────────────────────┐
                │  CLI: backfill_stuck_icmp_   │
                │       events                 │
                └──────────────────────────────┘
                          │
   ┌──────────────────────┼──────────────────────┬─────────────────┐
   │                      │                      │                 │
   ▼                      ▼                      ▼                 ▼
--dry-run            --execute              --rollback         --inventory-only
(read-only)          (mutating)            (from snapshot)    (read-only)
   │                      │                      │                 │
   ▼                      ▼                      ▼                 ▼
inventory_buckets   1. snapshot pre-       rollback_to_pre   bucket_report.md
(in stdout +        mutation →             snapshot via
markdown report)    apply-progress.md       Cypher SET
                          │
                          ▼
                  ┌──────────────────────┐
                  │ cascade_cypher_batch │
                  │  - ROOT cascade      │
                  │  - PROPAGATED        │
                  │  - NULL-disc close   │
                  └──────────────────────┘
                          │
                          ▼
                  ┌────────────────────────┐
                  │ Audit trail            │
                  │  - backfill_origin     │
                  │  - recovery_source     │
                  │  - apply-progress.md   │
                  └────────────────────────┘
```

The CLI refuses to run `--execute` or `--rollback` without `--confirm-target=<env>` matching a configured allowlist (`BACKFILL_ALLOWED_TARGETS` env var).

## Cascade Cypher (mirror `_recover_icmp_*_events`)

For ROOT events:

```cypher
UNWIND $cascade_targets AS row
MATCH (:CI {id: row.node_id})-[:HAS_EVENT]->(e:Event {metric_id: row.metric_id})
WHERE e.status IN ['OPEN', 'ACK']
  AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
  AND e.event_type = 'THRESHOLD_BREACH'
  AND row.bucket IN ['down_ci', 'deleted_ci']
SET e.status = 'RECOVERED',
    e.recovered_at = datetime(),
    e.recovery_source = 'backfill',
    e.backfill_origin = 'chore-events-backfill-486-cascade'
WITH e, row
CALL {
    WITH e, row
    MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
    WHERE pe.propagated_from = e.id
      AND pe.root_cause_ci_id = e.ci_id
      AND pe.correlation_type = 'PROPAGATED'
      AND pe.status IN ['OPEN', 'ACK']
      AND coalesce(m.can_propagate, true) = true
    SET pe.status = 'RECOVERED',
        pe.recovered_at = datetime(),
        pe.recovery_source = 'backfill',
        pe.backfill_origin = 'chore-events-backfill-486-cascade'
    RETURN count(pe) AS propagated_recovered
}
RETURN e, row.bucket AS bucket
```

For NULL-discriminator closure (legacy):

```cypher
UNWIND $legacy_nulls AS row
MATCH (e:Event {id: row.event_id})
WHERE e.status IN ['OPEN', 'ACK']
  AND (e.event_type IS NULL OR e.metric_id IS NULL)
  AND e.opened_at < datetime('2026-08-28T00:00:00Z')
SET e.event_type = 'legacy-no-relevant',
    e.status = 'RECOVERED',
    e.recovered_at = datetime(),
    e.recovery_source = 'backfill',
    e.backfill_origin = 'chore-events-backfill-486-legacy-null-discriminator',
    e.message = coalesce(e.message, '') +
        ' [closed by chore-events-backfill-486-legacy-null-discriminator on ' +
        toString(datetime()) + ']'
RETURN e
```

## Asymmetry decision: ICMP direct-child cascade, NOT SNMP full-cascade

`_recover_snmp_collection_failures` (`backend/engines/snmp_worker.py:1297`) uses `pe.root_cause_ci_id = e.ci_id` (full-cascade: every descendant whose root cause is the recovering CI). The ICMP recovery writers use `pe.propagated_from = e.id` (direct-child only). The asymmetry is deliberate (documented in code) and preserves the ICMP-propagation semantics from the pre-#485 codebase.

**The backfill cascade MUST use the ICMP predicate (`propagated_from = e.id`) to avoid expanding scope via backfill.** A separate change can align the two cascade strategies if/when the asymmetry becomes a documented problem.

## Audit marker schema

| Property | Type | Set on | Purpose |
|---|---|---|---|
| `backfill_origin` | string | Every row mutated by the cascade | Distinguishes backfill from runtime recovery; enables `backfill_origin IS NULL` filter for any future scope expansion. |
| `recovery_source` | string | Every row mutated by the cascade | `'backfill'` (cascade) vs runtime recovery. Future-proofing for a global `_recover_*` refactor. |
| `event_type` | string | NULL-discriminator rows only | New value `'legacy-no-relevant'`; explicit audit signal. |

`backfill_origin` values are stable strings:

- `'chore-events-backfill-486-cascade'` for CI-DOWN/Deleted cascade.
- `'chore-events-backfill-486-legacy-null-discriminator'` for legacy NULL closure.

No new Neo4j property constraints; properties are dynamic.

## Idempotency

Both cascade predicates begin with `e.status IN ['OPEN', 'ACK']`. Re-running the script after a partial apply is a no-op on already-recovered rows:

- Already RECOVERED rows: MATCH filter rejects; SET clause never fires.
- Concurrent `_recover_icmp_*_events` (runtime): the script's predicate mirrors the runtime predicate; a race where runtime fires between MATCH and SET produces double-recovery that the field-level SET operation idempotently resolves (last-write-wins on `recovered_at`).

## CI snapshot policy

The `--execute` mode issues a single query sorting `:HAS_AVAILABILITY_SAMPLE` by `collected_at DESC`, capturing `(ci_id, latest_availability)` at run start. The cascade targeting decision uses this snapshot, not live polling state.

A CI that was UP at inventory time but DOWN at run execution:

- Was targeted for natural recovery by the inventory classifier.
- Stays OPEN (not cascade-targeted) — `_recover_icmp_*_events` will close it on the next OK cycle.

A CI that was DOWN at inventory time but UP at run execution:

- Was cascade-targeted.
- Cascade fires and recovers the OPEN event.
- Slightly stale signal (the CI came back between inventory and run), but harmless: a runtime recovery would have produced the same result.

## MTTR defensive filter

`backend/services/event_service.py:682` (`get_availability_report`) currently filters `e.event_type = 'AVAILABILITY' AND e.availability_source IN ['PING', 'ICMP']`. ICMP jitter/packet_loss THRESHOLD_BREACH events are already excluded from MTTR by event_type.

The proposal adds the defensive clause `AND e.event_type <> 'legacy-no-relevant'` to:

1. Document the intended exclusion of the new `event_type` from MTTR aggregation.
2. Guard against future scope expansion of MTTR (e.g. adding THRESHOLD_BREACH events) which would otherwise silently pick up the legacy-no-relevant rows.

A regression test asserts that filtering with the clause produces unchanged MTTR for a synthetic dataset that includes both legacy-no-relevant and AVAILABILITY events.

## Snapshot and rollback contract

`apply-progress.md` written before any `--execute` mutation contains:

```yaml
run_id: <uuid>
run_at: <iso8601>
operator: <login>
ci_snapshot_at: <iso8601>
confirm_target: <env>
rows:
  - event_id: <int>
    ci_id: <string>
    metric_id: <string>
    bucket: <down_ci|deleted_ci|null_discriminator>
    status_pre: <OPEN|ACK>
    recovered_at_pre: <iso8601-or-null>
    event_type_pre: <string-or-null>
```

The `--rollback` mode reads this file and issues:

```cypher
UNWIND $rows AS row
MATCH (e:Event {id: row.event_id})
WHERE e.backfill_origin IS NOT NULL
SET e.status = row.status_pre,
    e.recovered_at = row.recovered_at_pre,
    e.event_type = row.event_type_pre,
    e.backfill_origin = NULL,
    e.recovery_source = NULL
RETURN count(e) AS rolled_back
```

The rollback is idempotent and self-bounded by `e.backfill_origin IS NOT NULL`. A double-rollback is a no-op.

## Operator safety gates

| Gate | Mechanism |
|---|---|
| Confirm target | `--confirm-target=<env>` required for `--execute`/`--rollback`; must match one of `BACKFILL_ALLOWED_TARGETS` env var values. |
| Dry-run first | Runbook step 1 must produce a dry-run report reviewed by a second operator before `--execute` is permitted in the same session. |
| Snapshot pre-mutation | `apply-progress.md` written before any Cypher SET; written atomically (rename into final path) so partial snapshots never serve as rollback inputs. |
| Grace window | `BACKFILL_HOLD_PRUNE_UNTIL` env flag pauses the prune scheduler for 24 h after `--execute` completes, giving operators a rollback window without losing data to the prune cycle. |

## Acceptance for design

- [x] Cascade Cypher shape: mirrors `_recover_icmp_*_events`.
- [x] Asymmetry preserved: backfill uses ICMP direct-child, NOT SNMP full-cascade.
- [x] Audit marker: `backfill_origin` + `recovery_source` + `event_type='legacy-no-relevant'`.
- [x] Idempotency: status filter is the gate.
- [x] CI snapshot: in-memory at run start.
- [x] MTTR defensive clause: line addition to `event_service.py:682`.
- [x] Rollback contract: snapshot file + replay Cypher.
- [x] Operator gate: `--confirm-target=<env>` argument allowlist.
