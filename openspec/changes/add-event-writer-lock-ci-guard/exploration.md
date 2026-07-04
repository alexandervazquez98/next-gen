## Exploration: Add Event writer lock CI guard

### Current State
The v1.13.5 duplication fix centralized the advisory-lock primitive in `backend/services/event_lock.py`. This exploration originally looked for direct import/call-path evidence, but the final pivoted contract supersedes that framing: the guard inventories emitters and validates protected-writer evidence metadata rather than proving every lock-before-write control-flow path.

Current protected writer evidence to preserve in metadata:

| Writer | Event write evidence | Lock evidence |
|---|---|---|
| `backend/services/snmp_service.py` | `CREATE (e:Event {` in `store_metric_result` around lines 609 and 650. | Protected metadata should cite behavior tests and approved lock symbol evidence such as `acquire_event_triplet_lock`; the guard should not claim full AST/control-flow proof. |
| `backend/engines/snmp_worker.py` | Multiple batched `CREATE (created:Event {` blocks in collection failure, ICMP availability, and ICMP latency refresh helpers. | Protected metadata should cite behavior tests and approved lock symbol evidence such as `acquire_event_triplet_lock`; the guard should not assert direct call proximity for every Cypher block. |
| `backend/polling/event_writer.py` | Batched `CREATE (created:Event {` blocks for collection failure and non-collection breaches around lines 347 and 399. | Protected metadata should cite behavior tests and the approved wrapper `_acquire_sorted_locks`; `_acquire_unsorted_locks` alone is not approved wrapper evidence. |

Additional Event emitters exist and need explicit classification before a broad guard lands:

- `backend/engines/cli_worker.py` creates `CLI_POLL_ALERT` Events for repeated NaN CLI metrics and currently does not call `acquire_event_triplet_lock`.
- `backend/services/backup_service.py` creates backup status Events (`ci_id='SYSTEM'`, `metric_id='BACKUP'`) and currently does not call `acquire_event_triplet_lock`.

Those two modules may be legitimate out-of-scope operational emitters rather than polling dedup writers, but a naïve repository-wide grep for `CREATE ... :Event` would fail on the current codebase unless it has an allowlist or scope filter.

### Affected Areas
- `backend/tests/` — best home for a CI-running pytest guard because backend CI already runs `python -m pytest` for backend changes.
- `backend/tests/README.md` — absent today; the change can create it or use an equivalent backend test document to explain the guard and registration workflow.
- `backend/services/snmp_service.py` — known protected writer that should appear in the guard registry with evidence metadata.
- `backend/engines/snmp_worker.py` — known protected writer with several Event write sites and approved `acquire_event_triplet_lock` symbol evidence in the metadata contract.
- `backend/polling/event_writer.py` — known protected batch writer whose registry evidence should use the approved `_acquire_sorted_locks` wrapper.
- `.github/workflows/backend-ci.yml` — already runs backend pytest with coverage on backend Python changes; no workflow change appears necessary if the guard is a normal test under `backend/tests/`.

### Existing Tests and CI Coverage
- `backend/tests/test_writer_advisory_lock.py` verifies the helper SQL shape and includes integration-style proofs for lock behavior and the three-writer concurrency model, but it does not discover future writer modules.
- `backend/tests/test_snmp_service_collection_failures.py`, `backend/tests/test_snmp_worker.py`, and `backend/tests/test_polling_event_writer.py` patch `acquire_event_triplet_lock` for specific writer behavior, but those tests are per-writer and will not fail when a new writer appears.
- `backend/tests/test_neo4j_write_guard.py` has structural ordering coverage for `snmp_worker` fallback behavior, not a repository-wide writer inventory.
- `backend/pytest.ini` discovers `tests/test_*.py`, so a new `test_event_writer_lock_guard.py` will run in normal backend pytest.
- `.github/workflows/backend-ci.yml` runs `python -m pytest --cov=. --cov-report=xml --cov-report=term-missing` from `backend/` when backend Python files change, and `pytest --collect-only` in the verify job.

### Approaches
1. **Explicit writer registry** — Add a test-owned registry of known polling Event writer module paths and assert each registered module carries explicit evidence metadata.
   - Pros: clear intent, low flake risk, stable against formatting, easy documentation.
   - Cons: does not automatically fail when a new unregistered Event writer is added unless paired with discovery.
   - Effort: Low.

2. **Static AST/grep discovery guard** — Scan `backend/**/*.py` for Neo4j Event creation patterns (`CREATE`/`MERGE` with `:Event`) and assert each discovered module is classified as protected or explicitly allowlisted as non-polling/out-of-scope. Direct import/call-path assertions from this option are superseded by the final metadata-wrapper contract.
   - Pros: catches future writers automatically; best fit for the acceptance criterion that a new writer fails CI unless registered/locked.
   - Cons: needs careful false-positive handling for tests, backup/CLI operational Events, fallback query duplicates, and multiline Cypher strings.
   - Effort: Medium.

3. **Hybrid registry + static discovery** — Keep an explicit registry of protected polling Event writers and an allowlist of documented non-polling emitters, then statically discover Event-emitting modules and fail if any discovered production module is neither protected nor allowlisted. For protected modules, assert Event creation evidence plus non-empty behavior test references and approved lock symbol/wrapper metadata.
   - Pros: satisfies automatic future-writer failure while preserving readable intent and avoiding current false positives.
   - Cons: introduces a small maintenance contract: new emitters must be classified as protected or intentionally exempt.
   - Effort: Medium.

### Recommendation
Use the hybrid approach in the proposal phase. The guard should live as a regular pytest file, likely `backend/tests/test_event_writer_lock_guard.py`, with:

- `PROTECTED_EVENT_WRITERS = {"services/snmp_service.py", "engines/snmp_worker.py", "polling/event_writer.py"}`.
- `NON_POLLING_EVENT_EMITTERS = {"engines/cli_worker.py", "services/backup_service.py"}` with short rationale comments.
- Static discovery over production `backend/**/*.py`, excluding `tests/`, archived/generated areas if any, and `services/event_lock.py`.
- A pattern robust enough to find multiline Cypher string Event writes.
- Assertions that every protected writer has Event creation evidence, behavior test references, and approved lock symbol/wrapper metadata, and every discovered Event emitter is classified.

This keeps the test passing against the current codebase while making a newly added Event writer fail CI until it is either protected with the advisory lock or deliberately classified as an exempt/non-polling emitter.

### Risks
- The issue statement lists three writers, but broad discovery sees `cli_worker.py` and `backup_service.py`; proposal/spec must decide whether these are exempt operational emitters or should be brought under the same lock policy later.
- Static text matching can miss dynamically built Cypher or produce false positives from comments/tests if exclusions are too weak.
- Import-only checks are insufficient for `event_writer.py` because production uses wrapper functions; the guard should accept approved wrapper metadata, especially `_acquire_sorted_locks`, rather than requiring direct calls near every Cypher string.
- The backend CI path filter means the full pytest guard runs for backend Python changes; non-backend-only PRs may only exercise collect-only unless backend files changed.

### Ready for Proposal
Yes — tell the user that the proposal should define a hybrid CI guard: static Event-writer discovery plus an explicit protected/exempt registry, documented in `backend/tests/README.md` or equivalent. The key validation to settle next is classification of `cli_worker.py` and `backup_service.py` as intentional non-polling emitters versus separate follow-up debt.
