# Proposal: chore(events): backfill stuck ICMP recovery events post-#485

## Intent

Close the residual backlog of pre-#485 OPEN ICMP-jitter and ICMP-packet-loss `Event` rows that the forward runtime fix shipped in v1.17.1 (PR #485) cannot close on its own.

PR #485 added `_recover_icmp_jitter_events`, `_recover_icmp_packet_loss_events`, and `_inject_synthetic_breaches_for_down_cis` so future poll cycles close OPEN events when an OK sample arrives. It deliberately did not retroactively close pre-existing OPEN rows in two cases:

1. **CI is currently DOWN or removed from CMDB.** No future cycle delivers an OK sample, so the recovery writers never fire.
2. **Legacy NULL-discriminator events.** `metric_id` or `event_type` is NULL on rows created before reliable discriminator population. The recovery writers' MATCH clauses (`metric_id = row.metric_id`, `event_type = 'THRESHOLD_BREACH'`) reject these rows.

This proposal adds a bounded one-shot backfill script that closes both buckets with an audit marker (`backfill_origin`) and removes the residual OPEN rows the Monitoring Console KPI cards still track.

## Scope

### Chained PR forecast

| PR | Content | Notes |
|---|---|---|
| PR 1 | SDD artifacts only (`proposal.md`, `design.md`, `tasks.md`, `specs/.../spec.md` delta) | Docs-only; unblocks `do_not_implement_without_prior_sdd_artifacts`. |
| PR 2 | `backend/scripts/backfill_stuck_icmp_events.py` in `--dry-run` mode + focused inventory tests | Read-only on Neo4j; produces the post-#485 inventory buckets. |
| PR 3 | `backfill_stuck_icmp_events.py` cascade implementation + MTTR exclusion clause in `event_service.py:682` + cascade tests | Mutates Neo4j; gated on operator-run, `--execute` flag, snapshot pre-run. |

### In Scope

- One-shot backfill for `Event` rows where `status IN ['OPEN', 'ACK']` AND `metric_id IN [ICMP_JITTER_METRIC_ID, ICMP_PACKET_LOSS_METRIC_ID]` AND `correlation_type IS NULL OR correlation_type = 'ROOT'`.
- Cascade to PROPAGATED descendants using the same predicates as `_recover_icmp_*_events` (`propagated_from = e.id`, `root_cause_ci_id = e.ci_id`, `correlation_type = 'PROPAGATED'`, `coalesce(m.can_propagate, true) = true`).
- Audit property `backfill_origin` set on every mutated row, distinguishing cascade (CI-DOWN/Deleted) from legacy-null-discriminator closure.
- `--dry-run` and `--execute` modes on the CLI; snapshot pre-mutation written to `apply-progress.md`.
- Conservative closure of NULL-discriminator rows as `event_type = 'legacy-no-relevant'`, preserving `metric_name`, `ci_id`, `severity`, `message` for forensic review.
- MTTR defensive clause: `AND e.event_type <> 'legacy-no-relevant'` in `get_availability_report`.

### Out of Scope

- Forward runtime recovery (shipped in #485 / v1.17.1).
- Human triage per NULL-discriminator event (153 events; handed off as a separate workstream).
- Changes to prune cadence or retention.
- Changes to MTTR calculation logic beyond the defensive filter.
- Backfill of non-ICMP events (this issue is ICMP-jitter + ICMP-packet-loss only).
- Reconstruction of `metric_id` / `event_type` for legacy rows (conservative close-only policy).

## Capabilities

### Modified Capabilities

- `event-prune-recovery-lifecycle`: Adds `legacy-no-relevant` as an explicit `event_type` value that must be excluded from MTTR aggregation. Adds the audit property `backfill_origin` documented for forensic queries.

### New Capabilities

- `event-backfill-stuck-icmp-recovery`: Bounded one-shot script + reusable inventory helpers for ICMP-jitter/packet-loss OPEN backlog.

## Approach

### 1. Inventory (PR2, dry-run-only)

A pure-read Neo4j query produces four buckets that drive the cascade decision:

- `stuck_with_proper_discriminators` — events with `event_type='THRESHOLD_BREACH'` and `metric_id` set.
- `stuck_null_discriminators` — events with either `event_type IS NULL` or `metric_id IS NULL`.
- `stuck_on_currently_down_ci` — events whose CI has `availability=0` in its latest `:HAS_AVAILABILITY_SAMPLE`.
- `stuck_on_deleted_ci` — events whose `ci_id` has no matching `:CI`.

Bucket 1 splits at run time into cascade-target (currently DOWN/deleted) and natural-recovery-target (currently UP). PR3 cascade only mutates cascade-target rows.

### 2. Cascade (PR3, execute-mode)

For each cascade-target ROOT event:

- Set `status = 'RECOVERED'`, `recovered_at = datetime()` (run time), `recovery_source = 'backfill'`, `backfill_origin = 'chore-events-backfill-486-cascade'`.
- Cascade to PROPAGATED descendants using the predicate set in `_recover_icmp_*_events` (NOT the `_recover_snmp_collection_failures` full-cascade; the asymmetry is deliberate).
- Within the same transaction, write `apply-progress.md` with `(event_id, ci_id, metric_id, action, ts)` tuples for rollback.

For each null-discriminator event opened before 2026-08-28 (the PR #432 merge date):

- Set `event_type = 'legacy-no-relevant'`, `status = 'RECOVERED'`, `recovered_at = datetime()`, `backfill_origin = 'chore-events-backfill-486-legacy-null-discriminator'`.
- Preserve `metric_name`, `ci_id`, `severity`, `failure_family` (whatever is present), and `message` — append a short audit suffix.

### 3. Idempotency

Both cascade branches filter `status IN ['OPEN', 'ACK']` — re-running the script after a partial apply is a no-op on already-recovered rows.

### 4. CI snapshot

The cascade takes a frozen snapshot of `(ci_id, latest_availability)` at run start via `ORDER BY s.collected_at DESC LIMIT 1` per CI. A CI that was UP at the time of the inventory query but DOWN at run execution is still treated as cascade-target (rollback path documented).

## Affected Areas

| Area | Files | Impact |
|---|---|---|
| OpenSpec artifacts | `openspec/changes/chore-events-backfill-stuck-icmp-recovery-486/` | New (4 files). |
| Spec delta | `openspec/specs/event-prune-recovery-lifecycle/spec.md` | ADDED Requirements scenarios. |
| Script | `backend/scripts/backfill_stuck_icmp_events.py` | New CLI with `--dry-run`/`--execute`/`--rollback`/`--confirm-target=<env>` modes. |
| Tests | `backend/tests/test_backfill_stuck_icmp_events.py` | New — inventory buckets, cascade, MTTR defensive filter. |
| MTTR query | `backend/services/event_service.py:682` | One-line defensive clause. |
| Runbook | `docs/runbooks/event-backfill.md` | Operator procedure for the run. |
| Neo4j schema | `:Event.backfill_origin`, `:Event.recovery_source` (dynamic properties) | Documented in spec delta; no migration needed. |
| Frontend | none | KPI cards self-resolve once OPEN backlog clears. |
| API surface | none | Existing `/api/events` query already exposes RECOVERED. |
| TimescaleDB | none | No new metrics. |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Cascade Cypher fires on stale CI availability (CI flapped between inventory and run). | Medium | Frozen snapshot at run start; `apply-progress.md` audit; rollback command documented. |
| PROPAGATED cascade accidentally recovers events that should not recover (cross-root contamination). | Medium | Cascade predicate mirrors `_recover_icmp_*_events` byte-for-byte; tests assert isolation. |
| `legacy-no-relevant` enters a query that enumerates event_types and breaks. | Low | Spec scenario asserts the new event_type is excluded from MTTR; regression test on `get_availability_report`. |
| Re-running the script after partial completion double-applies. | Low | Filters `status IN ['OPEN', 'ACK']`; tests assert idempotent. |
| `_recover_icmp_*_events` (forward fix) fires concurrently with backfill on live Neo4j. | Low | Backfill is one-shot run by operator at low-usage time; advisory triplet lock is per-(ci_id, metric_id) and unaffected; spec delta notes the timing assumption. |
| Operator runs `--execute` against the wrong Neo4j database. | Medium | CLI requires `--confirm-target=<env>` argument matching a configured allowlist; refuses otherwise. |

## Rollback Plan

1. **Pre-run snapshot.** `apply-progress.md` records `(event_id, ci_id, metric_id, event_type, status_pre, recovered_at_pre, backfill_origin_set)` for every row the script intends to mutate.
2. **Post-run rollback command.** `python -m backfill_stuck_icmp_events --rollback --snapshot=<apply-progress.md> --confirm-target=<env>` replays a Cypher that resets `status`, `recovered_at`, `event_type`, and clears `backfill_origin` for every mutated row.
3. **Operator grace window.** Production runbooks require a 24 h window after the backfill run during which no prune cycles execute (configurable via `BACKFILL_HOLD_PRUNE_UNTIL` env flag).

## Dependencies

- **Hard upstream.** PR #485 (v1.17.1) merged 2026-09-18, released as v1.17.1.
- **Hard upstream.** `event-prune-recovery-lifecycle` spec already declares the RECOVERED lifecycle contract; this proposal extends it.
- **No new dependencies.** No Python packages, no Docker images, no Neo4j migrations, no TimescaleDB migrations.

## Success Criteria

- [ ] PR1 (docs) merged.
- [ ] PR2 dry-run script reports `stuck_post_485_with_proper_discriminators`, `stuck_post_485_null_discriminators`, `stuck_post_485_on_down_ci`, `stuck_post_485_on_deleted_ci` in the target environment and produces zero data mutations.
- [ ] PR3 cascade applied against the target environment: the post-backfill inventory shows `stuck_post_485 = 0` and `null_discriminators = 0` (the legacy bucket is fully closed).
- [ ] `get_availability_report` continues to return MTTR values unchanged for the 2026-09 / 2026-10 window.
- [ ] `apply-progress.md` snapshot is written before any data mutation.
- [ ] `--rollback` reproduces the pre-run state on a fixture test.
- [ ] CHANGELOG entry under next PATCH (target v1.17.5) under `### Chores` referencing #486 and the PR number.

## References

- Issue: #486
- Upstream PR: #485 (v1.17.1, "ICMP event recovery symmetry")
- Recovery writers: `backend/engines/snmp_worker.py:1132`, `:1177`
- Synthetic breach injector: `backend/engines/snmp_worker.py:1220`
- SNMP full-cascade writer (NOT mirrored by backfill): `backend/engines/snmp_worker.py:1297`
- MTTR query: `backend/services/event_service.py:682`
- Spec target: `openspec/specs/event-prune-recovery-lifecycle/spec.md`
- Precedent archive: `openspec/changes/archive/2026-09-17-fix-484-event-recovery-jitter-packet-loss/`
- Config: `openspec/config.yaml` (`review_budget_changed_lines: 400`, `strict_tdd.test_first_required: true`)
