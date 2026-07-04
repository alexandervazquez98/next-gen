# Tasks: Add Event Writer Lock CI Guard

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | Initial forecast 250-450 pivot delta; actual PR exceeded 800 lines and used a maintainer-approved size exception |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR with maintainer-approved size exception |
| Delivery strategy | exception-ok |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Pivot guard to discovery + registry evidence metadata | PR 1 | Keep tests and README with the guard; no production writer changes. |

## Phase 1: Preserve Discovery and Classification Foundation

- [x] 1.1 Keep `backend/tests/test_event_writer_lock_guard.py` production-only Event emitter discovery for `CREATE`, `MERGE`, relationship/path, anonymous, multiline, and `FOREACH` Event creation.
- [x] 1.2 Keep discovery exclusions for `backend/tests/`, support/non-production paths, and read-only `MATCH (e:Event)` queries.
- [x] 1.3 Keep protected/exempt classification checks so each discovered production emitter appears in exactly one registry and new unclassified emitters fail with the module path.

## Phase 2: Pivot Protected Writer Evidence Contract

- [x] 2.1 Replace lock-before-write AST/control-flow proof tasks in `backend/tests/test_event_writer_lock_guard.py` with explicit evidence metadata validation.
- [x] 2.2 Define protected writer entries for `services/snmp_service.py`, `engines/snmp_worker.py`, and `polling/event_writer.py` with non-empty rationale, `evidence_tests`, and `lock_symbols_or_wrappers`.
- [x] 2.3 Validate every `evidence_tests` reference is non-empty and resolves to an existing file under `backend/tests/`; reject absolute paths and `..` escapes.
- [x] 2.4 Validate every protected writer has non-empty lock symbol/wrapper evidence; accept `_acquire_sorted_locks` for `polling/event_writer.py` and reject `_acquire_unsorted_locks` alone.

## Phase 3: Registry Safety and Exemptions

- [x] 3.1 Keep exempt entries for `engines/cli_worker.py` and `services/backup_service.py` with non-empty operational rationales.
- [x] 3.2 Validate all protected and exempt registry paths are backend-relative, contained under `backend/`, and resolve before any file read.
- [x] 3.3 Keep overlap checks so a path cannot be both protected and exempt.

## Phase 4: Documentation and Verification

- [x] 4.1 Update `backend/tests/README.md` to document protected registration, evidence test references, approved wrapper evidence, exempt rationale workflow, and unclassified-emitter failures.
- [x] 4.2 Remove or reword `apply-progress.md` claims that AST/control-flow proof is the desired final scope; note the pivot to evidence metadata if this artifact remains part of the review packet.
- [x] 4.3 Verify with CI backend pytest after local Docker/testcontainers was unavailable; GitHub Actions `backend-tests` passed.
