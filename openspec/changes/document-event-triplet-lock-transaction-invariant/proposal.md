# Proposal: Document Event Triplet Lock Transaction Invariant

## Intent

Prevent future Event writer concurrency regressions by documenting the `pg_advisory_xact_lock` session/transaction-lifetime invariant at the lock acquisition paths and guarding it with a static CI-friendly regression test. This is a maintenance change only; Event write behavior must remain unchanged.

## Scope

### In Scope
- Add inline invariant comments near current protected Event lock acquisition paths and wrapper paths.
- Extend the existing lock guard test area with a static regression guard for approved writer/session-lifetime patterns.
- Update the existing Event writer coordination OpenSpec/domain if specs are required.

### Out of Scope
- No runtime behavior change, lock primitive migration, or transaction redesign.
- No broad refactor of Event writers, polling topology, or session ownership.
- No new runtime integration suite unless the static guard proves insufficient.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `event-writer-coordination-observability`: clarify that transaction-scoped Event triplet locks require inline invariant documentation and CI regression coverage for protected writer paths.

## Approach

Use the conservative exploration recommendation: keep the change documentation-first and static-test-only. Tighten comments in current call/wrapper paths, then extend `backend/tests/test_event_writer_lock_guard.py` so future changes cannot move `acquire_event_triplet_lock` outside approved production writer functions or caller-owned open session paths.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/engines/snmp_worker.py` | Modified | Document lock calls that rely on the cycle-owned live SQLAlchemy session. |
| `backend/polling/event_writer.py` | Modified | Document sorted wrapper lock acquisition and caller-owned `lock_db` lifetime. |
| `backend/services/snmp_service.py` | Modified | Tighten existing near-call invariant wording only if needed. |
| `backend/tests/test_event_writer_lock_guard.py` | Modified | Add static guard for approved lock acquisition/session-lifetime patterns. |
| `openspec/specs/event-writer-coordination-observability/spec.md` | Modified | Existing domain for coordination invariant requirement. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Static guard becomes line-shape brittle | Med | Prefer AST/source containment and explicit approved wrapper metadata over exact line matching. |
| Wrapper paths create false positives | Med | Model `_acquire_sorted_locks` / `_acquire_unsorted_locks` and caller-owned `lock_db` as approved paths. |
| Comments imply stronger runtime proof than provided | Low | Phrase as invariant and regression guard, not full runtime verification. |

## Rollback Plan

Revert the comment/spec/test-only changes. Because runtime code paths are unchanged, rollback restores the previous documentation and CI guard surface without data migration.

## Dependencies

- Existing backend pytest command: `cd backend && python -m pytest`.
- Existing protected writer registry in `backend/tests/test_event_writer_lock_guard.py`.

## Success Criteria

- [ ] Relevant lock acquisition/wrapper paths state that `pg_advisory_xact_lock` is held only while the PostgreSQL session transaction remains open through the Neo4j Event write.
- [ ] Static guard fails if protected Event triplet lock acquisition is moved outside approved session/wrapper paths.
- [ ] No production behavior, lock primitive, or transaction ownership changes are introduced.
