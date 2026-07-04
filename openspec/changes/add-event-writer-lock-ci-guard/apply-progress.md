# Apply Progress: Add Event Writer Lock CI Guard

## Summary

Pivoted issue #334 away from fragile AST/control-flow lock-before-write proof. The guard now keeps production Event emitter discovery and explicit protected/exempt classification, then validates maintainer-owned protected writer evidence metadata: non-empty rationale, existing `backend/tests/` evidence references, and approved lock symbol/wrapper entries. Follow-up cleanup reworded stale proposal/exploration claims to match the metadata-wrapper contract and used the test root constant in evidence path resolution. Production Event writer logic was not modified.

## Completed Tasks

- [x] 1.1 Discovery helper tests for multiline `CREATE`/`MERGE`, relationship/path creation, anonymous nodes, `FOREACH`, read-only `MATCH`, and test/support exclusions.
- [x] 1.2 Discovery exclusions for `backend/tests/`, support paths, and read-only `MATCH (e:Event)` queries remain covered.
- [x] 1.3 Classification checks keep exactly-one registry membership and actionable unclassified emitter failure messages.
- [x] 2.1 Replaced lock-before-write AST/control-flow proof checks with explicit protected evidence metadata validation.
- [x] 2.2 Registered `services/snmp_service.py`, `engines/snmp_worker.py`, and `polling/event_writer.py` as protected writers with rationale, evidence tests, and lock symbols/wrappers.
- [x] 2.3 Evidence test references must be non-empty existing files under `backend/tests/`; absolute paths, `..`, and non-test roots are rejected.
- [x] 2.4 Protected writers require lock symbol/wrapper evidence; `_acquire_sorted_locks` is accepted for `polling/event_writer.py`, while `_acquire_unsorted_locks` alone is rejected.
- [x] 3.1 Exempt entries for `engines/cli_worker.py` and `services/backup_service.py` keep non-empty operational rationales.
- [x] 3.2 Protected/exempt registry paths are backend-relative and contained under `backend/` before resolution/read use.
- [x] 3.3 Protected/exempt overlap checks remain in place.
- [x] 4.1 Updated `backend/tests/README.md` for protected registration, evidence test references, approved wrapper evidence, exemptions, and unclassified-emitter failures.
- [x] 4.2 Reworded this progress artifact to remove stale AST/control-flow proof claims and document the evidence metadata pivot.

## Remaining Tasks

- [x] 4.3 Focused verification completed in CI: GitHub Actions `backend-tests` passed after local Docker/testcontainers was unavailable.

## Environment Prepared

- Created local backend virtual environment at `backend/.venv` using `/Users/macbook/.local/bin/python3.11` (Python 3.11.15).
- Bootstrapped pip with `backend/.venv/bin/python -m ensurepip --upgrade` and upgraded pip.
- Installed backend dependencies from existing project files: `backend/requirements.txt` and `backend/requirements-dev.txt`.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ `python -m pytest ...` blocked: `python` missing; `python3 -m pytest ...` blocked: no pytest | ✅ Existing discovery tests preserved before guard pivot | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Multiline `CREATE`/`MERGE`, relationship path, anonymous node, and `FOREACH` cases | ✅ Kept focused discovery helpers |
| 1.2 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Existing exclusion tests preserved | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Production writer vs tests/support path cases plus read-only `MATCH` case | ➖ None needed |
| 1.3 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Existing classification tests preserved | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Current discovery classification and synthetic unclassified emitter case | ✅ Failure message remains actionable |
| 2.1 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Metadata validation tests written before removing AST/control-flow acceptance contract | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Current protected entries plus missing metadata negative case | ✅ Replaced AST helpers with metadata validator |
| 2.2 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Protected-entry shape assertions written first | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ All three required protected writers asserted exactly | ✅ `ProtectedWriterEvidence` dataclass introduced |
| 2.3 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Evidence path containment test written first | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Valid test path plus absolute, `..`, and non-tests-root rejection cases | ✅ `_evidence_test_to_file` extracted |
| 2.4 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Sorted-vs-unsorted wrapper test written first | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Accepted `_acquire_sorted_locks` and rejected `_acquire_unsorted_locks` alone | ➖ None needed |
| 3.1 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Exempt rationale test preserved | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Both current exempt emitters validated | ➖ None needed |
| 3.2 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Registry containment tests preserved before metadata rewrite | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Valid backend-relative path plus absolute and traversal rejections | ✅ Shared registry path resolver retained |
| 3.3 | `backend/tests/test_event_writer_lock_guard.py` | Unit/static | ⚠️ pytest unavailable | ✅ Overlap classification behavior preserved | ⚠️ Manual zero-arg invocation passed; pytest blocked | ✅ Overlap and unclassified checks via `ClassificationResult` | ➖ None needed |
| 4.1 | `backend/tests/README.md` | Docs | N/A | ✅ Documentation acceptance driven by spec/task review before README edit | ✅ README updated | ✅ Protected, evidence-test, wrapper, exemption, and failure workflow sections covered | ✅ Removed stale control-flow proof wording |
| 4.2 | `openspec/changes/add-event-writer-lock-ci-guard/apply-progress.md` | Docs/artifact | N/A | ✅ Progress update requirement identified before rewriting stale artifact | ✅ Artifact updated | ✅ Summary, completed tasks, TDD table, issues, and deviations all reflect pivot | ✅ Merged previous completed state with new pivot progress |
| 4.3 | `backend/tests/test_event_writer_lock_guard.py`, `backend/tests/test_writer_advisory_lock.py`, `backend/tests/test_polling_event_writer.py` | Verification | CI backend lane | ✅ Local venv and pytest prepared from existing dependency files | ✅ GitHub Actions `backend-tests` passed after local Docker/testcontainers was unavailable | ✅ CI provided Docker/testcontainers-capable runner coverage | ➖ No production code modified |

## Test Summary

- **Total tests written/kept**: 11 pytest tests in `backend/tests/test_event_writer_lock_guard.py` focused on discovery, classification, registry safety, and evidence metadata.
- **Total tests passing**: Local guard pytest passed 11/11. Focused local pytest reached 43 passed / 4 Docker-environment failures, then GitHub Actions `backend-tests` passed on the PR branch.
- **Layers used**: Unit/static (11), Integration (0), E2E (0).
- **Approval tests**: None — no production refactoring tasks.
- **Pure functions created**: Discovery, classification, backend path containment, evidence test path containment, and evidence metadata validation helpers.

## Tests Run

- `cd backend && python -m pytest tests/test_event_writer_lock_guard.py` → blocked: `python: command not found`.
- `cd backend && python3 -m pytest tests/test_event_writer_lock_guard.py` → blocked: `No module named pytest`.
- `cd backend && python3 -m py_compile tests/test_event_writer_lock_guard.py` → passed.
- `cd backend && PYTHONPATH=tests python3 - <<'PY' ...` direct invocation of all 11 guard test functions with temporary directories for `tmp_path` cases → passed.
- `cd backend && python -m pytest tests/test_event_writer_lock_guard.py tests/test_writer_advisory_lock.py tests/test_polling_event_writer.py` → blocked: `python: command not found`.
- `cd backend && python3 -m pytest tests/test_event_writer_lock_guard.py tests/test_writer_advisory_lock.py tests/test_polling_event_writer.py` → blocked: `No module named pytest`.
- `cd backend && PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile tests/test_event_writer_lock_guard.py` → passed.
- `cd backend && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 - <<'PY' ...` metadata/classification smoke check → passed.
- `cd backend && /Users/macbook/.local/bin/python3.11 -m venv .venv && ./.venv/bin/python -m ensurepip --upgrade && ./.venv/bin/python -m pip install --upgrade pip && ./.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt` → passed; installed project runtime and dev/test dependencies locally.
- `cd backend && ./.venv/bin/python -m pytest tests/test_event_writer_lock_guard.py tests/test_writer_advisory_lock.py tests/test_polling_event_writer.py` → executed real pytest; 47 collected, 43 passed, 4 failed. Failing tests: `test_concurrent_writers_block_on_lock`, `test_unsorted_lock_acquisition_deadlocks`, `test_sorted_lock_acquisition_prevents_deadlock`, and `test_full_poll_cycle_no_duplicates`; each failed while `testcontainers` tried to create `PostgresContainer("postgres:15-alpine")` because Docker daemon access failed with `docker.errors.DockerException: Error while fetching server API version: ('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))`.
- `cd backend && docker info` → blocked: `zsh:1: command not found: docker`, confirming this environment cannot currently satisfy the testcontainers/Postgres integration dependency.
- GitHub Actions PR #353 `backend-tests` → passed after updating the branch with `main`.

## Deviations from Design

None — implementation matches the pivoted design: discovery remains static inventory/classification only, and protected writer acceptance is explicit metadata validation rather than AST/control-flow proof.

## Issues Found

- Focused local pytest was blocked only by missing Docker/testcontainers support on this machine; CI provided the required runner capability and passed `backend-tests`.

## Workload / PR Boundary

- Mode: single PR with accepted size-exception boundary.
- Current work unit: pivot guard to discovery + registry evidence metadata, with README and OpenSpec progress updates.
- Boundary: test/documentation/OpenSpec only; production Event writer logic unchanged.
- Estimated review budget impact: focused pivot delta within the approved single-PR boundary.
