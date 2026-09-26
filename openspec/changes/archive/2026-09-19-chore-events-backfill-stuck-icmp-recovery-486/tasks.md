# Tasks: chore(events): backfill stuck ICMP recovery events post-#485

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 800-1000 (across 3 chained PRs) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 docs-only → PR 2 dry-run script + inventory tests → PR 3 cascade + MTTR + cascade tests |
| Delivery strategy | auto-forecast |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | OpenSpec change skeleton (`proposal.md` + `design.md` + `tasks.md` + spec delta) | PR 1 | Docs-only. Unblocks `do_not_implement_without_prior_sdd_artifacts`. |
| 2 | `backend/scripts/backfill_stuck_icmp_events.py` in `--dry-run` mode + inventory queries + tests | PR 2 | Read-only on Neo4j; produces the post-#485 inventory buckets. |
| 3 | Cascade implementation (`--execute`), `--rollback`, MTTR clause in `event_service.py`, cascade tests, runbook | PR 3 | Mutates Neo4j; gated on operator-run + snapshot pre-run. |

PR1 boundary: this PR is complete when `openspec/changes/chore-events-backfill-stuck-icmp-recovery-486/` artifacts are review-ready. Code lands in PR2/PR3.

## Phase 1: SDD Skeleton (PR 1)

- [ ] 1.1 Write `proposal.md` referencing #486 and PR #485 with chained PR forecast and decisions table.
- [ ] 1.2 Write `design.md` documenting cascade Cypher, asymmetry decision, audit markers, idempotency, CI snapshot policy, MTTR defensive clause, snapshot/rollback contract.
- [ ] 1.3 Write `tasks.md` with work units 1–3 and phase breakdown (this file).
- [ ] 1.4 Write spec delta at `openspec/changes/chore-events-backfill-stuck-icmp-recovery-486/specs/event-prune-recovery-lifecycle/spec.md` adding the `legacy-no-relevant` event_type exclusion and `backfill_origin` audit marker.
- [ ] 1.5 Self-review for line-budget compliance: PR1 ≤ 400 lines (docs-only, expected ~350).

## Phase 2: Dry-run Inventory (PR 2)

- [ ] 2.1 RED test: `backend/tests/test_backfill_stuck_icmp_events.py::test_inventory_buckets` asserts four bucket counts on a fixture of mixed OPEN/RECOVERED/closed events.
- [ ] 2.2 RED test: `test_dry_run_makes_no_mutations` asserts `--dry-run` mode issues only read Cypher and persists no event mutations.
- [ ] 2.3 RED test: `test_ci_snapshot_freezes_at_run_start` asserts the snapshot captures availability state at the moment the script begins, not at the moment a particular CI is processed.
- [ ] 2.4 Implement `backend/scripts/backfill_stuck_icmp_events.py` with `--dry-run` mode producing the four bucket counts via read-only Neo4j queries.
- [ ] 2.5 GREEN: tests pass; `apply-progress.md` is not written in dry-run mode.

## Phase 3: Cascade Apply (PR 3)

- [ ] 3.1 RED test: `test_cascade_targets_root_event_only` asserts only cascade-bucket ROOT events transition; non-cascade ROOT events untouched.
- [ ] 3.2 RED test: `test_cascade_propagated_descendants` asserts `propagated_from = e.id` predicate mirrors `_recover_icmp_*_events`; cross-root PROPAGATED rows untouched.
- [ ] 3.3 RED test: `test_legacy_null_discriminator_closure` asserts `event_type='legacy-no-relevant'` is set, original `metric_name`/`ci_id`/`severity` preserved.
- [ ] 3.4 RED test: `test_snapshot_rollback_roundtrip` asserts `--rollback` reproduces pre-mutation state from `apply-progress.md`.
- [ ] 3.5 RED test: `test_mttr_unchanged_with_legacy_no_relevant` on `get_availability_report` with a fixture including `'legacy-no-relevant'` rows.
- [ ] 3.6 RED test: `test_confirm_target_required` asserts `--execute` and `--rollback` refuse without `--confirm-target=<env>` matching `BACKFILL_ALLOWED_TARGETS`.
- [ ] 3.7 Implement cascade mode in `backend/scripts/backfill_stuck_icmp_events.py`: snapshot write → cascade Cypher → NULL-discriminator closure → audit confirmation. Implement `--rollback` mode from snapshot.
- [ ] 3.8 Add defensive MTTR clause to `backend/services/event_service.py:687` (`AND e.event_type <> 'legacy-no-relevant'`).
- [ ] 3.9 GREEN: full backend suite `cd backend && python -m pytest` passes.
- [ ] 3.10 Operator runbook at `docs/runbooks/event-backfill.md`: pre-run checklist, dry-run report interpretation, execute confirmation, post-run verification, rollback procedure.

## Phase 4: Release

- [ ] 4.1 CHANGELOG entry under next PATCH (target v1.17.5) under `### Chores` referencing #486 and PR2/PR3 numbers.
- [ ] 4.2 Operator-validated run against target environment produces `stuck_post_485 = 0` and `null_discriminators = 0`.
- [ ] 4.3 Verify `get_availability_report` returns unchanged MTTR for 2026-09 / 2026-10 window.
- [ ] 4.4 Archive the change directory under `openspec/changes/archive/2026-MM-DD-chore-events-backfill-stuck-icmp-recovery-486/`.
