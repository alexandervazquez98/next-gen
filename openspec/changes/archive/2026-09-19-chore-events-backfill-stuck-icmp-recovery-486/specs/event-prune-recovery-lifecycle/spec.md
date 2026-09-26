# Delta for event-prune-recovery-lifecycle

## ADDED Requirements

### Requirement: Legacy-No-Relevant Event Type Excluded from MTTR

Legacy NULL-discriminator `Event` rows closed by the backfill path (`chore-events-backfill-stuck-icmp-recovery-486` or successor) carry `event_type = 'legacy-no-relevant'`. These rows MUST be excluded from `get_availability_report` MTTR aggregation. The existing `e.event_type = 'AVAILABILITY'` filter already excludes them; the additional `e.event_type <> 'legacy-no-relevant'` clause in `backend/services/event_service.py:682` makes the exclusion explicit and protects against future MTTR scope expansion (e.g. inclusion of THRESHOLD_BREACH events).

#### Scenario: Legacy-no-relevant rows excluded from MTTR

- GIVEN a fixture of recovered events where some have `event_type = 'AVAILABILITY'` and others have `event_type = 'legacy-no-relevant'`
- WHEN `get_availability_report` runs against the fixture
- THEN only `event_type = 'AVAILABILITY'` rows contribute to `mttr_seconds`
- AND `legacy-no-relevant` rows are excluded from the `repair_seconds` aggregation

### Requirement: Backfill Audit Marker on Mutated Rows

Every `Event` row mutated by the backfill cascade MUST set `backfill_origin` to a stable string identifying the change. The cascade MUST also set `recovery_source = 'backfill'`. Re-running the cascade MUST NOT mutate rows whose `backfill_origin` matches the current change identifier, ensuring idempotency across retries and operator re-runs.

The `backfill_origin` values are:

- `'chore-events-backfill-486-cascade'` for ROOT and PROPAGATED rows recovered by the CI-DOWN/CI-Deleted cascade.
- `'chore-events-backfill-486-legacy-null-discriminator'` for legacy NULL-discriminator rows closed as `legacy-no-relevant`.

#### Scenario: Backfill sets audit marker on root

- GIVEN an OPEN `Event` row matching cascade criteria
- WHEN the cascade executes
- THEN `backfill_origin` is set to `'chore-events-backfill-486-cascade'`
- AND `recovered_at` is set to the run timestamp
- AND `recovery_source` is set to `'backfill'`

#### Scenario: Backfill sets audit marker on legacy NULL-discriminator

- GIVEN an OPEN legacy `Event` row with `event_type IS NULL` opened before 2026-08-28
- WHEN the backfill executes
- THEN `event_type` is set to `'legacy-no-relevant'`
- AND `backfill_origin` is set to `'chore-events-backfill-486-legacy-null-discriminator'`
- AND `metric_name` and `ci_id` are preserved

#### Scenario: Re-run is idempotent

- GIVEN cascade already ran and set `backfill_origin` on a set of rows
- WHEN the cascade re-runs against the same data
- THEN no rows are re-mutated
- AND no `backfill_origin` values change
- AND the cascade report counts the same rows as already-recovered (no-op)

### Requirement: Backfill Recovers PROPAGATED Descendants via Direct-Child Predicate

When backfilling a ROOT `Event`, the cascade MUST recover its PROPAGATED descendants using the same predicate as `_recover_icmp_jitter_events` (`backend/engines/snmp_worker.py:1132`) and `_recover_icmp_packet_loss_events` (`backend/engines/snmp_worker.py:1177`): `pe.propagated_from = e.id AND pe.root_cause_ci_id = e.ci_id AND pe.correlation_type = 'PROPAGATED' AND coalesce(m.can_propagate, true) = true`. The backfill MUST NOT use the `_recover_snmp_collection_failures` full-cascade predicate (`backend/engines/snmp_worker.py:1297`, `pe.root_cause_ci_id = e.ci_id`), preserving the deliberate ICMP-direct-child asymmetry.

#### Scenario: Cascade recovers direct PROPAGATED descendants

- GIVEN a ROOT OPEN `Event` with two PROPAGATED descendants (one direct child, one cross-root via different root)
- WHEN the cascade runs
- THEN the direct PROPAGATED descendant transitions to RECOVERED
- AND the cross-root PROPAGATED descendant is NOT touched

#### Scenario: Cascade respects can_propagate=false

- GIVEN a ROOT OPEN `Event` with a PROPAGATED descendant whose `MetricDef.can_propagate = false`
- WHEN the cascade runs
- THEN the descendant is NOT recovered (the metric is explicitly not propagating)

### Requirement: Backfill Snapshot and Rollback Contract

The backfill script MUST write `apply-progress.md` before any data mutation, recording `(event_id, ci_id, metric_id, bucket, status_pre, recovered_at_pre, event_type_pre)` for every row it intends to mutate. The `--rollback` mode MUST read this file and reset each mutated row to its pre-mutation state, clearing `backfill_origin` and `recovery_source`. The rollback MUST self-bound by `e.backfill_origin IS NOT NULL` so a double-rollback is a no-op. The script MUST refuse to run `--execute` or `--rollback` without `--confirm-target=<env>` matching `BACKFILL_ALLOWED_TARGETS`.

#### Scenario: Rollback reproduces pre-mutation state

- GIVEN a snapshot in `apply-progress.md` for a set of mutated rows
- WHEN the operator runs `--rollback --snapshot=<file> --confirm-target=<env>`
- THEN every mutated row returns to its `status_pre`, `recovered_at_pre`, `event_type_pre` values
- AND `backfill_origin` and `recovery_source` are NULL on every rolled-back row

#### Scenario: Execute refuses without confirm-target

- GIVEN `--execute` mode is requested
- WHEN `--confirm-target=<env>` is not provided or does not match `BACKFILL_ALLOWED_TARGETS`
- THEN the script exits non-zero with an error message naming the required flag
- AND no data mutation is attempted
