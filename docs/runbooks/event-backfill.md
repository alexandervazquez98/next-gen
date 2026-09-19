# Runbook: ICMP Stuck-Event Backfill (chore-events-backfill-stuck-icmp-recovery-486)

Operator procedure for running the one-shot backfill that closes pre-#485
OPEN ICMP-jitter and ICMP-packet-loss `Event` rows. The forward runtime
fix shipped in v1.17.1 (PR #485) cannot close rows where the CI is
currently DOWN, the CI was removed from the CMDB, or the event has
NULL `event_type` / `metric_id` discriminators.

This backfill is a **mutating operation**. Read the entire runbook
before running `--execute`.

## When to run

Run this backfill when:

- The Monitoring Console KPI cards show residual OPEN events for
  `icmp_jitter_ms` or `icmp_packet_loss_pct` that have not closed in
  days despite the CI being reachable (these are pre-#485 residue).
- A migration or audit shows that some CIs that were DOWN are now
  permanently decommissioned and their OPEN events must be closed.
- The audit-Legacy-Event-Discriminators workstream hands off its
  residual 153 NULL-discriminator events for closure.

## Pre-run checklist

Before invoking any mutating command:

- [ ] Confirm the target Neo4j instance is reachable from the operator host.
- [ ] Confirm `BACKFILL_ALLOWED_TARGETS` is set in the operator shell:

      ```bash
      export BACKFILL_ALLOWED_TARGETS=staging
      # or for production:
      # export BACKFILL_ALLOWED_TARGETS=prod
      ```

- [ ] Confirm the operator has Neo4j credentials in the env:

      ```bash
      export NEO4J_URI='bolt://neo4j-host:7687'
      export NEO4J_USER='<operator-user>'
      export NEO4J_PASSWORD='<from sealed secret store>'
      ```

- [ ] Pause the APScheduler `Event Prune Recovered Events` job for 24 h
      after the run so the rollback window has time to apply. Set:

      ```bash
      export BACKFILL_HOLD_PRUNE_UNTIL='2026-09-20T00:00:00Z'
      ```

      and verify the scheduler honors the flag before proceeding.

- [ ] Have the runbook author or a second operator confirm the run
      scope (which `BACKFILL_ALLOWED_TARGETS` value) before `--execute`.

## Dry-run (read-only, always run first)

```bash
python -m scripts.backfill_stuck_icmp_events \
    --dry-run \
    --output /tmp/backfill-dry-run-$(date -u +%Y%m%dT%H%M%SZ).json
```

### Interpreting the dry-run report

The report has four bucket counts:

| Bucket | Meaning | Action |
|---|---|---|
| `stuck_with_proper_discriminators` | ROOT THRESHOLD_BREACH events with valid metric_id. Subset of these will be cascade targets (down_ci or deleted_ci). | Cascade closes the down_ci / deleted_ci subset. UP CIs are left for natural recovery. |
| `stuck_null_discriminators` | Legacy events with NULL `event_type` or `metric_id`, opened before 2026-08-28. | All closed as `event_type='legacy-no-relevant'`. |
| `stuck_on_down_ci` | Events whose CI is currently DOWN (latest `:HAS_AVAILABILITY_SAMPLE` has `value=0`). | Cascade targets. |
| `stuck_on_deleted_ci` | Events whose CI no longer exists in `:CI`. | Cascade targets. |

The CI snapshot (`ci_snapshot` in the report) is the frozen availability
state used for the cascade decision. CIs that flapped between the dry-run
and the execute run are handled by re-snapshotting at execute time.

### Expected post-#485 baseline

After v1.17.1 has been running for 24-48 h:

- `stuck_with_proper_discriminators` should be small (only events on
  CIs that have been DOWN since the deploy).
- `stuck_null_discriminators` should match the count reported in
  issue #486 (153 at issue-open; may be lower if forward fix
  recovered some).
- `stuck_on_down_ci` and `stuck_on_deleted_ci` should sum to the
  cascade-target count.

## Execute (mutating)

```bash
python -m scripts.backfill_stuck_icmp_events \
    --execute \
    --confirm-target=staging \
    --output /var/log/next-gen/apply-progress-$(date -u +%Y%m%dT%H%M%SZ).json
```

The `--output` path becomes the `apply-progress.json` snapshot file.
**Do not delete it** until the post-run verification confirms the
cascade was successful and the rollback window has closed (24 h).

### What `--execute` does (in order)

1. Reads the cascade-target events (`select_cascade_targets`).
2. Reads the legacy NULL-discriminator events (`select_legacy_nulls`).
3. Writes the `apply-progress.json` snapshot atomically (temp + rename).
4. Cascades ROOT events + PROPAGATED descendants via the ICMP
   direct-child predicate (`propagated_from = e.id`). Each mutated row
   gets `backfill_origin='chore-events-backfill-486-cascade'` and
   `recovery_source='backfill'`.
5. Closes legacy NULL-discriminator events as
   `event_type='legacy-no-relevant'` with
   `backfill_origin='chore-events-backfill-486-legacy-null-discriminator'`.

Idempotency: every mutation is gated by `status IN ['OPEN', 'ACK']`. A
re-run is a no-op on already-recovered rows.

### What `--execute` does NOT do

- Does NOT modify events with `metric_id` outside `{icmp_jitter_ms,
  packet_loss_pct}` (out of scope).
- Does NOT modify RECOVERED events.
- Does NOT modify PROPAGATED events directly (only via the cascade
  through their ROOT).
- Does NOT touch the SNMP full-cascade branch — the asymmetry with the
  ICMP recovery writers is preserved.

## Post-run verification

Within 5 minutes of the execute run, re-run the dry-run and confirm:

```bash
python -m scripts.backfill_stuck_icmp_events \
    --dry-run \
    --output /tmp/backfill-post-run-$(date -u +%Y%m%dT%H%M%SZ).json
```

Expected:

- `stuck_post_485_with_proper_discriminators`: should drop to the count
  of UP-CI events (these are correctly left for natural recovery).
- `stuck_post_485_null_discriminators`: **0** (legacy bucket fully
  closed).
- `stuck_post_485_on_down_ci`: **0** (cascade closed them).
- `stuck_post_485_on_deleted_ci`: **0** (cascade closed them).

If any bucket is non-zero unexpectedly, do not panic. Inspect the
`apply-progress.json` snapshot to confirm the events were not closed,
and consult the rollback procedure below.

## Rollback procedure

If the cascade mutated the wrong rows (verified via the post-run
inventory or via operator review), rollback within the 24 h grace
window:

```bash
python -m scripts.backfill_stuck_icmp_events \
    --rollback \
    --confirm-target=staging \
    --output /var/log/next-gen/apply-progress-<timestamp>.json
```

The `--output` path here is the **snapshot file** written by the
original `--execute` run. The rollback:

1. Reads the snapshot.
2. Issues a Cypher that resets `status`, `recovered_at`, and
   `event_type` to the pre-mutation values.
3. Clears `backfill_origin` and `recovery_source`.

The rollback is self-bounded by `backfill_origin IS NOT NULL`, so a
double-rollback is a no-op.

## Audit trail queries

After the run, the audit markers make forensic queries trivial:

```cypher
// All rows mutated by any chore-events-backfill-486-* cascade:
MATCH (e:Event)
WHERE e.backfill_origin STARTS WITH 'chore-events-backfill-486-'
RETURN e.backfill_origin AS origin, count(e) AS count
ORDER BY count DESC

// Specifically the legacy-null closure:
MATCH (e:Event)
WHERE e.backfill_origin = 'chore-events-backfill-486-legacy-null-discriminator'
RETURN e.ci_id, e.metric_name, e.severity, e.recovered_at
ORDER BY e.recovered_at DESC

// Specifically the CI-DOWN / deleted-CI cascade:
MATCH (e:Event)
WHERE e.backfill_origin = 'chore-events-backfill-486-cascade'
RETURN e.ci_id, e.metric_id, e.recovered_at
ORDER BY e.recovered_at DESC
```

## MTTR impact

The MTTR query (`backend/services/event_service.py:682`) already
excludes `event_type = 'AVAILABILITY'`, which means jitter / packet_loss
THRESHOLD_BREACH events never reached MTTR. The new
`legacy-no-relevant` rows are excluded explicitly via
`AND e.event_type <> 'legacy-no-relevant'`. **MTTR aggregation is
unchanged by this backfill.**

## References

- Issue: #486
- Upstream PR: #485 (v1.17.1, ICMP recovery symmetry)
- SDD change: `openspec/changes/chore-events-backfill-stuck-icmp-recovery-486/`
- Script: `backend/scripts/backfill_stuck_icmp_events.py`
- Recovery writers mirrored: `backend/engines/snmp_worker.py:1132`, `:1177`
- MTTR query: `backend/services/event_service.py:682`
