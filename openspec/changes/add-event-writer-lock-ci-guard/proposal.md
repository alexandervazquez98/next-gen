# Proposal: Add Event Writer Lock CI Guard

## Intent

Prevent future Neo4j `Event` writers from bypassing the event-triplet advisory lock policy. CI should discover production backend Event emitters and fail when a module is neither registered as protected with explicit evidence metadata nor explicitly exempt.

## Scope

### In Scope
- Add a backend pytest guard that statically discovers production Event-emitting modules.
- Maintain an explicit protected-writer registry and exempt-emitter registry.
- Assert protected writers include Event creation evidence plus explicit evidence metadata: behavior test references and approved lock symbols or wrappers.
- Document the registration workflow in `backend/tests/README.md`.

### Out of Scope
- Changing production Event writer logic.
- Locking operational emitters unless evidence proves they require the same policy now.
- Workflow changes beyond normal backend pytest CI execution.

## Capabilities

### New Capabilities
- `event-writer-lock-guard`: CI-enforced inventory and advisory-lock policy for backend Neo4j `Event` emitters.

### Modified Capabilities
- None.

## Approach

Use a hybrid static-discovery and registry guard:
- Discover backend production Python modules containing Neo4j `Event` creation patterns, excluding tests and non-production paths.
- Register protected writers: `backend/services/snmp_service.py`, `backend/engines/snmp_worker.py`, `backend/polling/event_writer.py`.
- Register documented exempt operational emitters: `backend/engines/cli_worker.py` and `backend/services/backup_service.py`, unless implementation evidence shows they must be protected now.
- Fail CI when a discovered emitter is unclassified, or a protected writer lacks explicit evidence metadata. Wrapper-based evidence such as `_acquire_sorted_locks` may satisfy the contract when it is the approved production wrapper for that writer.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/tests/test_event_writer_lock_guard.py` | New | Static discovery, protected/exempt registry, and assertions. |
| `backend/tests/README.md` | New/Modified | Guard purpose, classification workflow, exemption rationale. |
| `.github/workflows/backend-ci.yml` | Existing | No planned change; backend pytest should run the guard. |
| `backend/services/snmp_service.py`, `backend/engines/snmp_worker.py`, `backend/polling/event_writer.py` | Referenced | Protected writer inventory. |
| `backend/engines/cli_worker.py`, `backend/services/backup_service.py` | Referenced | Exempt operational emitter inventory. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Static discovery false positives | Med | Scope to production backend files and robust multiline Cypher patterns. |
| Guard misses dynamic query construction | Low | Document classification rule and keep protected registry explicit. |
| Exemptions hide dedup debt | Med | Require rationale and keep exemptions narrow. |

## Rollback Plan

Revert the guard test and README changes. No production code or data migration is expected.

## Dependencies

- Existing backend pytest CI.
- Existing `backend/services/event_lock.py` advisory-lock primitive.

## Success Criteria

- [ ] CI fails when a new backend production module creates Neo4j `Event` nodes and is not classified.
- [ ] CI fails when a protected Event writer lacks explicit behavior-test and approved lock symbol/wrapper evidence metadata.
- [ ] The three polling writers are registered as protected.
- [ ] `cli_worker.py` and `backup_service.py` are documented as exempt operational emitters with rationale.
- [ ] `backend/tests/README.md` explains how to register protected or exempt emitters.
