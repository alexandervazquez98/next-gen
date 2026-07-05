# Proposal: Audit Legacy Event Discriminators

## Intent
Deliver Slice 1 of issue #155: a read-only audit that identifies legacy `Event` rows missing or risking incorrect discriminator values before any backfill/admin workflow is designed. The goal is operator-safe visibility, not mutation.

## Scope

### In Scope
- Build a reusable read-only audit engine for legacy event discriminator analysis.
- Produce Markdown for human review plus JSON for tooling/admin-UI reuse.
- Classify likely gaps for `event_type`, `failure_family`, and `source_protocol`, including threshold/availability legacy-null rows and generic-vs-SNMP no-response ambiguity.
- Add focused tests first for classification and report serialization.

### Out of Scope
- Backfill, migration, mutation, or admin apply workflow.
- Admin UI/API endpoints.
- Changing runtime event matching semantics.

## Capabilities

### New Capabilities
- `legacy-event-discriminator-audit`: Read-only classification and reporting for legacy `Event` discriminator risks, with Markdown and JSON outputs.

### Modified Capabilities
- None.

## Approach
- Create a pure audit engine that accepts event-like records/query results and returns structured findings.
- Keep database access thin and separated from classification so tests can cover rules without services.
- Generate deterministic Markdown and JSON from the same result model.
- Treat ambiguous legacy-null rows as findings requiring human review instead of silently inferring unsafe values.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/services/` | New | Reusable audit/classification engine and report model. |
| `backend/scripts/` | New | Read-only entry point to run the audit and emit Markdown/JSON. |
| `backend/tests/` | New | Strict-TDD coverage for classification, ambiguity boundaries, and report output. |
| `openspec/changes/audit-legacy-event-discriminators/` | New | SDD proposal/spec/design/tasks artifacts. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Ambiguous legacy text is over-classified | Medium | Report uncertainty explicitly; do not mutate data. |
| Audit engine becomes UI-specific | Low | Keep output as domain result model plus serializers. |
| Large datasets make audit slow | Medium | Design query boundaries and summary counts before future apply/admin work. |

## Rollback Plan
Remove the new read-only audit engine, script, tests, and OpenSpec change artifacts. No data rollback is required because Slice 1 performs no writes.

## Dependencies
- Existing `Event` discriminator fields and runtime helper constants.
- Existing local/shared test setup only; no new Docker or service environment.

## Success Criteria
- [ ] Tests define and verify read-only classification before implementation.
- [ ] Audit emits both Markdown and JSON from the same result model.
- [ ] Findings cover missing discriminators, threshold/availability legacy-null risks, and generic-vs-SNMP no-response ambiguity.
- [ ] No database writes, backfill, admin UI, or runtime behavior changes are introduced.
