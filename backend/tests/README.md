# Backend Test Guards

## Event writer lock guard

`test_event_writer_lock_guard.py` is a CI guard for production backend modules that create Neo4j `Event` nodes. It statically scans production `backend/**/*.py` files, excludes test/support plus local/generated trees (for example `.venv`, `venv`, `env`, caches, and vendor-style directories), and fails when an Event emitter is not explicitly classified.

The guard protects the cross-writer Event de-duplication policy by requiring every polling Event writer to carry explicit, reviewable lock evidence metadata. It does not attempt to prove every control-flow path statically.

### Registering a protected writer

When adding a production polling writer that creates `Event` nodes:

1. Add a `ProtectedWriterEvidence` entry to `PROTECTED_EVENT_WRITERS` using the backend-relative module path as the registry key.
2. Include a short non-empty `rationale` that explains the writer role.
3. Add one or more `evidence_tests` references. Each reference must be non-empty, relative to `backend/tests/`, and point to an existing test file. Absolute paths and `..` traversal are rejected.
4. Add one or more `lock_symbols_or_wrappers` values that identify the lock primitive or approved production wrapper used by the writer. Every claimed symbol/wrapper must also appear in the protected source file so registry metadata cannot claim lock evidence that the module does not contain.

Registry paths must remain normalized backend-relative paths. Absolute paths, `..` traversal, and paths that resolve outside `backend/` are rejected before the guard reads protected files.

For `polling/event_writer.py`, `_acquire_sorted_locks` is the approved wrapper evidence because it deduplicates and sorts triplets before calling the advisory-lock helper. `_acquire_unsorted_locks` is an internal callee and must not be the only registered wrapper evidence.

### Registering an exempt emitter

Only exempt an Event emitter when it is not part of polling triplet de-duplication. Add the backend-relative path to `EXEMPT_EVENT_EMITTERS` with a rationale that explains why the Event does not need the triplet lock.

Current exemptions:

- `engines/cli_worker.py` emits `CLI_POLL_ALERT` events for repeated NaN CLI extraction health.
- `services/backup_service.py` emits admin backup status events for the `SYSTEM/BACKUP` operational path.

### Failure workflow

If CI reports an unclassified emitter, choose exactly one path:

- Protected: register it in `PROTECTED_EVENT_WRITERS` with rationale, evidence test references, and lock symbol/wrapper evidence.
- Exempt: register it in `EXEMPT_EVENT_EMITTERS` with a narrow operational rationale.

Do not add a module to both registries.
