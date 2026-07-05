# Apply Progress: Audit Legacy Event Discriminators

## Status

Complete: implementation tasks 1.1 through 4.3 are complete, fresh review remediation is applied, and focused pytest passed using an existing worktree venv runner from the main workspace. System `python`/`python3` remain blocked, but verification no longer depends on them.

## Completed Tasks

- [x] 1.1 Add failing coverage for missing discriminator findings.
- [x] 1.2 Add failing coverage for ambiguous legacy-null boundaries.
- [x] 1.3 Add failing coverage for deterministic finding order and Markdown/JSON parity.
- [x] 2.1 Create the audit result model in `backend/services/legacy_event_discriminator_audit.py`.
- [x] 2.2 Implement independent missing discriminator and ambiguous legacy-null classification.
- [x] 2.3 Implement Markdown and JSON serializers from one ordered model.
- [x] 2.4 Add a read-only driver runner.
- [x] 3.1 Create the CLI with `--format json|markdown`, optional output path, and DB loading.
- [x] 3.2 Wire the script to call the service runner and print/write output.
- [x] 3.3 Keep CLI behavior deterministic for empty or populated result sets.
- [x] 4.1 Extend script tests with monkeypatched driver/runner coverage.
- [x] 4.2 Refactor audit tests around shared row and assertion helpers.
- [x] 4.3 Preserve the same result model across Markdown and JSON output.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | N/A (new) | ✅ Written first | ✅ Implementation passed focused pytest | ✅ Missing `event_type`, `failure_family`, and `source_protocol` plus complete-row negative case | ✅ Shared `legacy_record()` and finding helpers |
| 1.2 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | N/A (new) | ✅ Written first | ✅ Implementation passed focused pytest | ✅ Threshold/availability and generic-vs-SNMP boundary fixtures | ✅ Ambiguous findings share model helpers |
| 1.3 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | N/A (new) | ✅ Written first | ✅ Implementation passed focused pytest | ✅ Reversed input ordering and repeated JSON serialization checks | ✅ Stable helper assertions for finding keys/codes |
| 2.1-2.4 | `backend/tests/test_legacy_event_discriminator_audit.py` | Unit | N/A (new service) | ✅ Service tests existed before production service file | ✅ Implementation passed focused pytest | ✅ Runner, serializer, classifier, empty/complete cases covered | ✅ Pure functions and dataclasses isolate behavior |
| 3.1-3.3 | `backend/tests/test_polling_runtime_scripts.py` | Unit | Existing script test file extended and focused pytest passed | ✅ CLI tests written before CLI script | ✅ Implementation passed focused pytest | ✅ JSON stdout and Markdown output path cases | ✅ Thin CLI delegates to service model |
| 4.1-4.3 | Both focused test files | Unit | Existing script test file read before modification | ✅ Coverage added before script implementation | ✅ Implementation passed focused pytest | ✅ Format parity/order and monkeypatched CLI coverage | ✅ No DB/Docker dependency introduced |

## Tests Run

- Fresh review remediation:
  - `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m pytest tests/test_legacy_event_discriminator_audit.py -q` — RED evidence: 1 failed, 5 passed; new read-transaction assertion failed before implementation.
  - `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m pytest tests/test_legacy_event_discriminator_audit.py tests/test_polling_runtime_scripts.py -k 'legacy_event_discriminator_audit or audit_legacy_event_discriminators' -q` — passed: 8 passed, 8 deselected in 1.04s.
- `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/issue-334-event-writer-lock-ci-guard/backend/.venv/bin/python -m pytest tests/test_legacy_event_discriminator_audit.py tests/test_polling_runtime_scripts.py -k 'legacy_event_discriminator_audit or audit_legacy_event_discriminators' -q` — passed: 7 passed, 8 deselected in 0.63s.
- Earlier attempts with system `python`/`python3` were blocked by local xcode-select/developer-tools issues; those are environment issues, not test failures.

## Files Changed

- `backend/tests/test_legacy_event_discriminator_audit.py` — created strict-TDD unit tests for classifier, serializers, deterministic ordering, and read-only runner.
- `backend/tests/test_legacy_event_discriminator_audit.py` — fresh remediation added empty-result JSON/Markdown assertions, mutation-clause safety assertions for `SET`, `DELETE`, `CREATE`, `MERGE`, `REMOVE`, and `DETACH`, and explicit read transaction/read access assertions.
- `backend/services/legacy_event_discriminator_audit.py` — created pure audit model, classifier, Markdown/JSON serializers, and read-only Neo4j runner; fresh remediation now opens Neo4j sessions with `READ_ACCESS` when available and executes via `execute_read`/`read_transaction` before falling back to `session.run`.
- `backend/scripts/audit_legacy_event_discriminators.py` — created CLI entry point.
- `backend/tests/test_polling_runtime_scripts.py` — added monkeypatched CLI tests.
- `openspec/changes/audit-legacy-event-discriminators/tasks.md` — marked tasks complete.
- `openspec/changes/audit-legacy-event-discriminators/apply-progress.md` — persisted this progress report.

## Deviations

None — the implementation follows the design scope and remains read-only with no admin UI/API, no backfill, no runtime matching changes, and no new Docker/test environment. Fresh remediation kept compatibility when Neo4j read-access constants or transaction helpers are unavailable.

## Remaining Work

No implementation tasks remain. Focused verification passed with the existing venv runner; broader suite execution remains outside this slice.
