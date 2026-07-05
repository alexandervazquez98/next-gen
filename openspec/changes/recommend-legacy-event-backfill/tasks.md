# Tasks: Recommend Legacy Event Backfill

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~260-520 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1: recommendation core; PR 2: CLI + runtime script + tests |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Recommendation model and renderers | PR 1 | Base from updated `origin/main` with PR #361 merged |
| 2 | CLI wiring and runtime script coverage | PR 2 | Base from PR 1 branch or stacked-to-main boundary if chosen |

## Phase 1: Setup / Preconditions

- [ ] 1.1 Create or switch to a clean worktree from updated `origin/main` that includes merged PR #361 before editing any files.
- [ ] 1.2 Confirm the target OpenSpec artifacts are present: `proposal.md`, `specs/legacy-event-backfill-recommendation/spec.md`, and `design.md`.

## Phase 2: RED — Tests First

- [ ] 2.1 Add failing unit tests in `backend/tests/test_legacy_event_discriminator_audit.py` for `build_legacy_event_backfill_recommendation()`, bucket counts, schema version, Markdown/JSON parity, and read-only advisory wording.
- [ ] 2.2 Add failing CLI/runtime tests in `backend/tests/test_polling_runtime_scripts.py` for `backend/scripts/audit_legacy_event_discriminators.py` recommendation mode and absence of any `--apply` path.

## Phase 3: GREEN — Core Implementation

- [ ] 3.1 Implement `LegacyEventBackfillRecommendation` plus `RECOMMENDATION_SCHEMA_VERSION` in `backend/services/legacy_event_discriminator_audit.py`.
- [ ] 3.2 Add bucket aggregation, batching guidance, idempotency/rollback notes, and deterministic `recommendation_to_json_dict()` / `recommendation_to_markdown()` helpers.
- [ ] 3.3 Wire `backend/scripts/audit_legacy_event_discriminators.py` to emit recommendation-only report output with no write, backfill, or migration execution.

## Phase 4: REFACTOR / Verify

- [ ] 4.1 Refine names, docstrings, and shared render logic in `backend/services/legacy_event_discriminator_audit.py` without changing behavior.
- [ ] 4.2 Update tests to lock stable output ordering and explicit rejection of mutation-shaped options in `backend/tests/test_legacy_event_discriminator_audit.py` and `backend/tests/test_polling_runtime_scripts.py`.
- [ ] 4.3 Re-read the OpenSpec change artifacts and confirm the tasks still match the read-only recommendation scope only.
