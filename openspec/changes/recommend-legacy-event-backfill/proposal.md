# Proposal: Recommend Legacy Event Backfill

## Intent

Produce a read-only, reviewer-facing recommendation report for issue #155 Slice 2 that determines whether legacy event discriminator records are ready for a future production-scale backfill. This turns Slice 1 audit evidence into migration readiness guidance without changing data.

## Scope

### In Scope
- Generate Markdown and JSON report outputs only.
- Estimate candidate counts and classify safe, ambiguous, and no-touch confidence buckets.
- Recommend batching, idempotency expectations, rollback constraints, and operational risk for a possible Slice 3 backfill.
- Preserve read-only Neo4j access and mutation-query safeguards.

### Out of Scope
- No `--apply`, writes, backfill execution, migration execution, or event mutation.
- No automatic remediation of ambiguous records.
- No Slice 3 implementation decision before report review.

## Capabilities

### New Capabilities
- `legacy-event-backfill-recommendation`: Read-only analysis and report generation for production-scale legacy event discriminator backfill readiness.

### Modified Capabilities
- None.

## Approach

Build on the Slice 1 legacy event discriminator audit path. Add a recommendation-oriented report summarizing candidate populations, confidence levels, ambiguity/no-touch reasons, proposed batch sizing/rate limits, retry/idempotency assumptions, rollback limitations after mutation, and operator-facing risk. Tests should prove the path is read-only and emits stable Markdown plus JSON evidence.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `openspec/changes/recommend-legacy-event-backfill/` | New | SDD planning artifacts for Slice 2. |
| `backend/services/legacy_event_discriminator_audit.py` | Modified | Extend or compose audit results into recommendation categories. |
| `backend/scripts/audit_legacy_event_discriminators.py` | Modified | Expose report-only recommendation outputs without apply flags. |
| `backend/tests/test_legacy_event_discriminator_audit.py` | Modified | Add read-only, scale-readiness, Markdown, and JSON assertions. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Report implies mutation safety too strongly | Medium | Separate recommendation from approval to mutate. |
| Large production datasets make counts expensive | Medium | Recommend bounded queries, batching assumptions, and operator review. |
| Ambiguous records get over-classified | High | Keep ambiguous/no-touch buckets explicit and conservative. |

## Rollback

Rollback is deleting or reverting the report-only code and artifacts. Since no data is written, no database rollback is required. Future Slice 3 rollback must be designed separately because event mutations may be hard to reverse at scale.

## Dependencies

- Slice 1 audit behavior from PR #361.
- Read-only Neo4j access suitable for count and classification queries.

## Success Criteria

- [ ] Report produces Markdown and JSON with candidate counts, confidence buckets, no-touch groups, batching guidance, rollback constraints, idempotency expectations, and operational risk.
- [ ] Tests prove no write, merge, delete, set, create, or apply path exists in Slice 2.
- [ ] Reviewers can decide whether Slice 3 should implement a guarded backfill.
