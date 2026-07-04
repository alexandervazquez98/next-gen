# Design: Add Event Writer Lock CI Guard

## Technical Approach

Add a backend pytest guard that statically inventories production Python modules that create Neo4j `Event` nodes, then validates explicit maintainer-owned registries. Discovery is intentionally limited to emitter inventory/classification: it scans backend production files, excludes tests/support, detects `CREATE`/`MERGE`/`FOREACH` clause spans containing `:Event`, and keeps backend-relative path containment before reading registered files.

The guard does **not** claim to prove every control-flow path acquires a lock before writing. Instead, protected writers must carry reviewable evidence metadata: behavior test references and/or approved wrapper evidence. CI fails when emitters are unclassified or protected entries lack non-empty evidence.

## Architecture Decisions

| Option | Tradeoff | Decision |
|---|---|---|
| AST/control-flow proof guard | Fragile and easy to overclaim. | Reject. Use discovery plus explicit evidence metadata. |
| Registry-only guard | Simple but misses new emitters. | Reject. Static discovery is required for unclassified-emitter failures. |
| Discovery + protected/exempt registries | Maintainer-owned evidence, clear CI failures, modest upkeep. | Choose. Matches the pivoted spec and current pytest patterns. |

## Data Flow

```text
pytest
  └─ test_event_writer_lock_guard.py
       ├─ discover production backend Event emitters
       ├─ normalize/contain backend-relative registry paths
       ├─ compare discovered emitters to protected/exempt registries
       └─ validate protected evidence and exempt rationales are present
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/tests/test_event_writer_lock_guard.py` | Create/Update | Static emitter discovery, path containment, protected/exempt registries, evidence metadata validation. |
| `backend/tests/README.md` | Create/Update | Maintainer workflow: new protected writer requires classification plus evidence/test reference; new exempt emitter requires rationale. |
| `.github/workflows/backend-ci.yml` | No change | Existing backend pytest execution should run the guard. |
| Production Event writers | No change | Referenced as inventory/evidence targets only. |

## Interfaces / Contracts

Use backend-relative paths without `backend/` prefixes. Registry paths MUST reject absolute paths and `..` escapes.

```python
@dataclass(frozen=True)
class ProtectedWriterEvidence:
    path: str
    rationale: str
    evidence_tests: tuple[str, ...]
    lock_symbols_or_wrappers: tuple[str, ...]

PROTECTED_EVENT_WRITERS = {
    "services/snmp_service.py": ProtectedWriterEvidence(
        path="services/snmp_service.py",
        rationale="legacy SNMP writer for polling Event deduplication",
        evidence_tests=("tests/test_snmp_service_collection_failures.py", "tests/test_writer_advisory_lock.py"),
        lock_symbols_or_wrappers=("acquire_event_triplet_lock",),
    ),
    "engines/snmp_worker.py": ProtectedWriterEvidence(
        path="engines/snmp_worker.py",
        rationale="external SNMP worker Event writer",
        evidence_tests=("tests/test_snmp_worker.py", "tests/test_writer_advisory_lock.py"),
        lock_symbols_or_wrappers=("acquire_event_triplet_lock",),
    ),
    "polling/event_writer.py": ProtectedWriterEvidence(
        path="polling/event_writer.py",
        rationale="queue polling Event writer",
        evidence_tests=("tests/test_polling_event_writer.py", "tests/test_writer_advisory_lock.py"),
        lock_symbols_or_wrappers=("_acquire_sorted_locks",),
    ),
}

EXEMPT_EVENT_EMITTERS = {
    "engines/cli_worker.py": "CLI_POLL_ALERT operational health emitter, not polling triplet deduplication",
    "services/backup_service.py": "SYSTEM/BACKUP administrative status emitter, not metric polling deduplication",
}
```

Discovery contract: detect `:Event` creation in `CREATE`, `MERGE`, and `FOREACH` spans, including relationship-path creation such as `CREATE (ci)-[:HAS_EVENT]->(e:Event {...})`, multiline Cypher, and anonymous nodes. Read-only `MATCH (e:Event)` queries are not emitters.

Evidence contract: CI validates protected entries have non-empty `rationale`, `evidence_tests`, and `lock_symbols_or_wrappers`; exempt entries have non-empty rationale. `_acquire_unsorted_locks` may exist internally but MUST NOT be the approved wrapper evidence.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Static discovery scope | Synthetic source tests for multiline `CREATE`/`MERGE`, relationship paths, anonymous nodes, `FOREACH`, read-only `MATCH` exclusion, and tests/support exclusion. |
| Unit | Registry shape and path safety | Assert backend-relative paths, no absolute/escape paths, no protected/exempt overlap, and non-empty rationales. |
| Unit | Evidence metadata | Assert every protected writer has non-empty evidence test references and approved symbols/wrappers; reject `_acquire_unsorted_locks` alone. |
| CI | Unclassified emitters | Real backend discovery must fail with actionable output when a production emitter is absent from both registries. |
| Focused pytest | Existing behavior evidence | Run `tests/test_event_writer_lock_guard.py`, plus referenced evidence files: `test_snmp_service_collection_failures.py`, `test_snmp_worker.py`, `test_polling_event_writer.py`, `test_writer_advisory_lock.py`. |

## Migration / Rollout

No production migration required. Rollout is test/documentation only. Rollback is reverting the guard test and README changes.

## Open Questions

None.
