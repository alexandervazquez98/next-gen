# Apply Progress: Recommend Legacy Event Backfill

## Status

PR 3 CLI recommendation mode and runtime script coverage are complete. The Slice 2 recommendation change remains read-only/report-first with no apply, backfill, migration, or mutation execution path.

## Completed Tasks

- [x] 1.1 Confirmed worktree `feat/issue-155-backfill-recommendation-core` was based on updated `origin/main` with PR #361 commit `7f0e9a1` for the first implementation slice.
- [x] 1.2 Confirmed target OpenSpec artifacts are present.
- [x] 2.1 Added failing-first unit coverage for `build_legacy_event_backfill_recommendation()`, bucket counts, schema version, Markdown/JSON parity, deterministic output, and read-only advisory wording.
- [x] 2.2 Added failing-first runtime script coverage for recommendation JSON output, recommendation Markdown output, stable bucket ordering, and explicit rejection of `--apply`.
- [x] 3.1 Implemented `LegacyEventBackfillRecommendation` plus `RECOMMENDATION_SCHEMA_VERSION`.
- [x] 3.2 Added bucket aggregation, conservative scale guidance, idempotency/rollback notes, and deterministic JSON/Markdown renderers.
- [x] 3.3 Wired `backend/scripts/audit_legacy_event_discriminators.py` with `--report recommendation` to render advisory recommendation Markdown/JSON from the existing read-only audit result.
- [x] 4.1 Refined service names, docstrings, and shared renderer/model structure while preserving existing audit behavior.
- [x] 4.2 Locked runtime-script stable output ordering and mutation-shaped option rejection in `backend/tests/test_polling_runtime_scripts.py`.
- [x] 4.3 Re-read the OpenSpec proposal, spec, design, tasks, and previous apply progress; confirmed the implemented PR 3 scope remains read-only recommendation reporting only.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | N/A | Preconditions | `git log` confirmed PR #361 on base during prior slice | N/A | Confirmed | N/A | N/A |
| 1.2 | N/A | Preconditions | OpenSpec artifacts read before implementation | N/A | Confirmed | N/A | N/A |
| 2.1 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | ✅ 6/6 existing tests passed before production edits in prior slice | ✅ Import failed for missing recommendation API | ✅ 9/9 passed | ✅ bucket, parity, advisory, and determinism cases | ✅ tests remained green after cleanup |
| 2.2 | `backend/tests/test_polling_runtime_scripts.py` | Runtime script | ✅ 11/11 selected existing recommendation/audit tests passed before PR 3 edits | ✅ 3 new tests failed before CLI wiring (`--report` unsupported; `--apply` raised parser exit) | ✅ 5/5 runtime script recommendation/audit tests passed | ✅ JSON stdout, Markdown output-file, stable bucket order, advisory wording, and `--apply` rejection covered | ✅ Black reformatted test file; 14/14 selected tests still passed |
| 3.1 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | ✅ 6/6 existing tests passed before production edits in prior slice | ✅ tests referenced missing schema/model API first | ✅ 9/9 passed | ✅ multiple record classifications exercised | ✅ Black/Ruff clean |
| 3.2 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | ✅ 6/6 existing tests passed before production edits in prior slice | ✅ JSON/Markdown/guidance tests failed before implementation | ✅ 9/9 passed | ✅ same model rendered through JSON and Markdown | ✅ shared dataclass serializers extracted |
| 3.3 | `backend/tests/test_polling_runtime_scripts.py` | Runtime script | ✅ 11/11 selected existing recommendation/audit tests passed before PR 3 edits | ✅ `--report recommendation` tests failed before implementation | ✅ 5/5 runtime script recommendation/audit tests passed | ✅ Recommendation JSON and Markdown paths both exercised | ✅ Rendering selection centralized in script main |
| 4.1 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | ✅ 9/9 passing before format/refactor checks in prior slice | ✅ covered by behavior-preserving tests | ✅ 9/9 passed | ✅ deterministic output case | ✅ Black/Ruff clean |
| 4.2 | `backend/tests/test_polling_runtime_scripts.py` | Runtime script | ✅ 5/5 runtime script recommendation/audit tests green before formatting | ✅ parser rejection case covered mutation-shaped option | ✅ 14/14 selected tests passed with service tests included | ✅ stable bucket labels and explicit no-`--apply` report assertion | ✅ Ruff and Black clean |
| 4.3 | OpenSpec artifacts | Scope review | Proposal/spec/design/tasks/progress re-read before completion | N/A | Confirmed read-only recommendation-only scope | N/A | N/A |

## Verification

- `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m pytest tests/test_polling_runtime_scripts.py tests/test_legacy_event_discriminator_audit.py -k 'legacy_event_discriminator_audit or recommendation' -q` — 14 passed, 8 deselected.
- `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m ruff check scripts/audit_legacy_event_discriminators.py tests/test_polling_runtime_scripts.py` — passed.
- `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m black --check scripts/audit_legacy_event_discriminators.py tests/test_polling_runtime_scripts.py` — passed.

## Remaining Tasks

None for the assigned PR 3 scope.

## Deviations

None. PR 3 intentionally changed only the CLI script, runtime script tests, and OpenSpec progress artifacts; the recommendation core was not modified.

## Risks

- `main()` now converts parser `SystemExit` into return code `2` so runtime tests can assert rejection of mutation-shaped options without invoking a process boundary. This preserves CLI exit behavior through `raise SystemExit(main())` when the script is executed directly.
- The recommendation report remains advisory only; any Slice 3 mutation/backfill still requires a separate reviewed design and implementation.
