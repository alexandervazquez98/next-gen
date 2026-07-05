# Design: Audit Legacy Event Discriminators

## Technical Approach

Create a read-only backend audit capability that separates classification from database access. A pure engine will accept event-like records, emit a single ordered result model, and serializers will render Markdown and JSON from that same model. Runtime event matching in `backend/polling/event_writer.py` and `backend/services/snmp_service.py` is intentionally untouched; their current discriminator rules are only used as audit vocabulary.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Audit core | Add `backend/services/legacy_event_discriminator_audit.py` with pure record classification plus thin read-only Cypher runner | Add admin router now; embed logic in existing `event_service.py` | Keeps Slice 1 reusable by a future admin UI without creating UI/API/mutation surface now. |
| Result model | Define typed result objects in the audit service: `LegacyEventAuditRecord`, `LegacyEventAuditFinding`, `LegacyEventAuditSummary`, `LegacyEventAuditResult` | Emit ad-hoc dicts per format | One model makes Markdown/JSON parity testable and prevents divergent reports. |
| Ambiguity handling | Report missing fields and ambiguous boundaries; never infer or recommend persisted values | Auto-fill likely `event_type` from message text | Existing Cypher still accepts legacy-null collection failures, so unsafe inference could hide generic-vs-SNMP or threshold-vs-availability collisions. |
| Runner | Add `backend/scripts/audit_legacy_event_discriminators.py` with `--format json|markdown` and optional output path | Require Docker or a new test environment | Matches existing script patterns and stays read-only. Unit tests can mock records/driver. |

## Data Flow

```text
Neo4j read-only MATCH
  -> event-like rows
  -> classify_legacy_event_records(rows)
  -> LegacyEventAuditResult
  -> result_to_markdown(result) / result_to_json_dict(result)
```

The query should return only fields required for review: event id, CI/metric ids, status, severity, message, `event_type`, `failure_family`, `source_protocol`, `availability_source`, timestamps, and optional CI/metric labels.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/services/legacy_event_discriminator_audit.py` | Create | Pure classifier, result model, Markdown/JSON serializers, and read-only Neo4j query helper. |
| `backend/scripts/audit_legacy_event_discriminators.py` | Create | CLI entry point that loads `database.get_db`, runs the audit, and prints/writes selected format. |
| `backend/tests/test_legacy_event_discriminator_audit.py` | Create | Test-first unit coverage for missing-field findings, ambiguity boundaries, deterministic ordering, and serializer parity. |
| `backend/tests/test_polling_runtime_scripts.py` | Modify | Add lightweight script tests with monkeypatched driver/result; no live DB. |

## Interfaces / Contracts

```python
def classify_legacy_event_records(records: Iterable[Mapping[str, Any]]) -> LegacyEventAuditResult: ...
def result_to_markdown(result: LegacyEventAuditResult) -> str: ...
def result_to_json_dict(result: LegacyEventAuditResult) -> dict[str, Any]: ...
def run_legacy_event_discriminator_audit(driver, *, limit: int | None = None) -> LegacyEventAuditResult: ...
```

Findings should use stable codes such as `missing_event_type`, `missing_failure_family`, `missing_source_protocol`, `ambiguous_threshold_or_availability`, and `ambiguous_collection_failure_boundary`. Sort findings by `(ci_id, metric_id, event_id, code)` so repeated runs and formats are deterministic.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Classifier flags each missing discriminator independently | Pure dict fixtures; no DB. |
| Unit | Threshold/availability and generic-vs-SNMP no-response boundaries are ambiguous, not definitive | Message/protocol/family fixtures based on existing lifecycle constants. |
| Unit | Markdown and JSON share counts/order from one result | Compare finding ids/codes/counts across serializers. |
| Script | CLI calls read-only runner and emits requested format | Monkeypatch `get_db`/runner; parse stdout. |

Strict TDD applies: future implementation starts by adding failing tests before service/script code.

## Migration / Rollout

No migration required. Slice 1 performs read-only queries only, creates no admin route, no frontend surface, no backfill, and no runtime event matching change.

## Open Questions

None.
