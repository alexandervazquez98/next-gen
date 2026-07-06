# Design: Recommend Legacy Event Backfill

## Technical Approach

Add a report-only recommendation layer on top of the Slice 1 legacy event discriminator audit model. The new code composes `LegacyEventAuditResult` and its ordered findings into a deterministic `LegacyEventBackfillRecommendation`, then renders Markdown and JSON from that same recommendation object. The recommendation never mutates data, never exposes `--apply`, and never approves Slice 3; it only tells reviewers whether a guarded backfill is worth planning.

Implementation should happen on top of PR #361/Slice 1, because the target files exist in the issue worktree but are not present on the current `fix/pingcheck-packet-loss` checkout.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Recommendation core | Extend `backend/services/legacy_event_discriminator_audit.py` with recommendation dataclasses/functions that consume `LegacyEventAuditResult` | Duplicate audit classification in a new service | Reusing Slice 1 keeps ambiguity rules single-sourced and prevents drift between audit and recommendation output. |
| Versioning | Add a constant such as `RECOMMENDATION_SCHEMA_VERSION = "legacy-event-backfill-recommendation.v1"` in the recommendation payload | Use package version or AI/model wording | The version describes deterministic report schema/logic, not an AI model, so tests can assert exact output compatibility. |
| Buckets | Derive `safe_candidates`, `ambiguous_records`, and `no_touch_records` from audit findings and record coverage | Treat every missing discriminator as safe to backfill | Conservative buckets protect reviewers from over-trusting inferred legacy semantics. Ambiguous records stay excluded from safe candidates. |
| Output | Render `recommendation_to_json_dict()` and `recommendation_to_markdown()` from one dataclass | Build Markdown and JSON separately | One model enforces parity for counts, bucket labels, guidance, and review-gate language. |
| CLI | Add `--report recommendation` or equivalent explicit mode to `audit_legacy_event_discriminators.py`; keep existing audit behavior | Create migration/backfill command | A thin script mode fits current runtime script tests while avoiding any mutation-shaped API. |

## Data Flow

```text
Neo4j READ session
  -> run_legacy_event_discriminator_audit(driver, limit)
  -> LegacyEventAuditResult
  -> build_legacy_event_backfill_recommendation(audit_result, limit)
  -> Markdown + JSON serializers from the same recommendation model
```

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/services/legacy_event_discriminator_audit.py` | Modify | Add recommendation dataclasses, schema version, bucket aggregation, scale guidance, JSON/Markdown renderers. |
| `backend/scripts/audit_legacy_event_discriminators.py` | Modify | Expose recommendation output without apply/write flags; reuse existing driver and output-path pattern. |
| `backend/tests/test_legacy_event_discriminator_audit.py` | Modify | Add failing-first unit tests for buckets, schema version, guidance, deterministic output, and mutation-safety. |
| `backend/tests/test_polling_runtime_scripts.py` | Modify | Add monkeypatched CLI tests proving recommendation JSON/Markdown output and no apply option. |

## Interfaces / Contracts

```python
RECOMMENDATION_SCHEMA_VERSION = "legacy-event-backfill-recommendation.v1"

def build_legacy_event_backfill_recommendation(
    audit: LegacyEventAuditResult, *, inspected_limit: int | None = None
) -> LegacyEventBackfillRecommendation: ...

def recommendation_to_json_dict(model: LegacyEventBackfillRecommendation) -> dict[str, Any]: ...
def recommendation_to_markdown(model: LegacyEventBackfillRecommendation) -> str: ...
```

The model should include: `schema_version`, candidate counts, confidence bucket labels, representative finding codes, batching guidance, rate/limit assumptions, idempotency expectations, rollback constraints, operational risks, and `slice3_review_gate` with advisory-only wording.

## Scale and Operations Guidance

The recommendation should count inspected records and bucket totals, then state that production execution needs bounded batches, operator-reviewed limits, retry-safe idempotency keys, and observability before Slice 3. Default guidance should be conservative: process only safe candidates, exclude ambiguous/no-touch records, require dry-run evidence, and assume rollback after mutation is constrained because previous discriminator values may be unknown at scale.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Fixed fixtures map to safe, ambiguous, and no-touch counts deterministically | Pure dict fixtures through Slice 1 classifier plus recommendation builder. |
| Unit | Markdown and JSON contain matching version, counts, buckets, guidance, and review gate | Normalize strings and compare against one model. |
| Unit | Read-only boundary has no apply/write/backfill/migration authorization | Parser tests and mutation-clause assertions; no Docker. |
| Script | CLI emits recommendation JSON/Markdown and output files | Monkeypatch driver/runner like existing runtime script tests. |

Strict TDD applies: add failing tests before implementation.

## Migration / Rollout

No migration required. Slice 2 is read-only/report-first. Rollback is reverting code/artifacts. Slice 3 requires a separate reviewed design before any mutation.

## Open Questions

None.
