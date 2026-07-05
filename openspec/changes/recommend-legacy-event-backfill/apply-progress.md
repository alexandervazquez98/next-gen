# Apply Progress: Recommend Legacy Event Backfill

## Status

PR 1 recommendation core/model/renderers is complete. CLI wiring and runtime script coverage remain for PR 2.

## Completed Tasks

- [x] 1.1 Confirmed worktree `feat/issue-155-backfill-recommendation-core` is based on updated `origin/main` with PR #361 commit `7f0e9a1`.
- [x] 1.2 Confirmed target OpenSpec artifacts are present.
- [x] 2.1 Added failing-first unit coverage for `build_legacy_event_backfill_recommendation()`, bucket counts, schema version, Markdown/JSON parity, deterministic output, and read-only advisory wording.
- [x] 3.1 Implemented `LegacyEventBackfillRecommendation` plus `RECOMMENDATION_SCHEMA_VERSION`.
- [x] 3.2 Added bucket aggregation, conservative scale guidance, idempotency/rollback notes, and deterministic JSON/Markdown renderers.
- [x] 4.1 Refined service names, docstrings, and shared renderer/model structure while preserving existing audit behavior.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | N/A | Preconditions | `git log` confirmed PR #361 on base | N/A | Confirmed | N/A | N/A |
| 1.2 | N/A | Preconditions | OpenSpec artifacts read before implementation | N/A | Confirmed | N/A | N/A |
| 2.1 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | ✅ 6/6 existing tests passed before production edits | ✅ Import failed for missing recommendation API | ✅ 9/9 passed | ✅ bucket, parity, advisory, and determinism cases | ✅ tests remained green after cleanup |
| 3.1 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | ✅ 6/6 existing tests passed before production edits | ✅ tests referenced missing schema/model API first | ✅ 9/9 passed | ✅ multiple record classifications exercised | ✅ Black/Ruff clean |
| 3.2 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | ✅ 6/6 existing tests passed before production edits | ✅ JSON/Markdown/guidance tests failed before implementation | ✅ 9/9 passed | ✅ same model rendered through JSON and Markdown | ✅ shared dataclass serializers extracted |
| 4.1 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | ✅ 9/9 passing before format/refactor checks | ✅ covered by behavior-preserving tests | ✅ 9/9 passed | ✅ deterministic output case | ✅ Black/Ruff clean |

## Verification

- `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m pytest tests/test_legacy_event_discriminator_audit.py -q` — 9 passed.
- `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m ruff check services/legacy_event_discriminator_audit.py tests/test_legacy_event_discriminator_audit.py` — passed.
- `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m black --check services/legacy_event_discriminator_audit.py tests/test_legacy_event_discriminator_audit.py` — passed.

## Remaining PR 2 Tasks

- [ ] 2.2 Add failing CLI/runtime tests in `backend/tests/test_polling_runtime_scripts.py` for recommendation mode and absence of mutation-shaped options.
- [ ] 3.3 Wire `backend/scripts/audit_legacy_event_discriminators.py` to emit recommendation-only report output.
- [ ] 4.2 Complete runtime-script stable ordering and mutation-shaped option assertions for the CLI slice.
- [ ] 4.3 Re-read OpenSpec artifacts after PR 2 and confirm the final change remains read-only recommendation scope only.

## Deviations

None. PR 1 intentionally leaves CLI/runtime script work for PR 2 per stacked-to-main boundary.

## Risks

- Recommendation safety currently depends on consuming `LegacyEventAuditResult`; PR 2 must preserve the same read-only boundary when exposing CLI output.
- The audit model does not carry full safe-record identities, so PR 1 reports safe candidate counts conservatively from total records minus records with findings.
