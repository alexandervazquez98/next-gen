# Tasks: Audit Legacy Event Discriminators

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 220-320 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Pure audit model and classifiers | PR 1 | Base work for service and serializer tests |
| 2 | Read-only CLI wiring | PR 1 | Depends on Unit 1 and stays within same slice |

## Phase 1: RED — Audit model and classifier tests

- [x] 1.1 Add failing coverage in `backend/tests/test_legacy_event_discriminator_audit.py` for missing `event_type`, `failure_family`, and `source_protocol` findings on one row.
- [x] 1.2 Add failing coverage for ambiguous legacy-null boundaries in `backend/tests/test_legacy_event_discriminator_audit.py` using threshold/availability and generic-vs-SNMP no-response fixtures.
- [x] 1.3 Add failing coverage for deterministic finding order and Markdown/JSON parity in `backend/tests/test_legacy_event_discriminator_audit.py`.

## Phase 2: GREEN — Service implementation

- [x] 2.1 Create `backend/services/legacy_event_discriminator_audit.py` with `LegacyEventAuditRecord`, `LegacyEventAuditFinding`, `LegacyEventAuditSummary`, and `LegacyEventAuditResult`.
- [x] 2.2 Implement `classify_legacy_event_records()` so each missing discriminator is reported independently and ambiguous legacy-null cases stay non-definitive.
- [x] 2.3 Implement `result_to_markdown()` and `result_to_json_dict()` from one ordered result model.
- [x] 2.4 Add the read-only runner in `backend/services/legacy_event_discriminator_audit.py` that accepts a DB driver and returns the audit result without writes.

## Phase 3: GREEN — CLI wiring

- [x] 3.1 Create `backend/scripts/audit_legacy_event_discriminators.py` with `--format json|markdown`, optional output path, and read-only DB loading.
- [x] 3.2 Wire the script to call the service runner and print or write the selected format.
- [x] 3.3 Keep the script exit behavior read-only and deterministic for empty or populated result sets.

## Phase 4: REFACTOR — Script and integration tests

- [x] 4.1 Extend `backend/tests/test_polling_runtime_scripts.py` or the closest existing script test file to monkeypatch `get_db` / runner and assert CLI output shape.
- [x] 4.2 Refactor `backend/tests/test_legacy_event_discriminator_audit.py` to share fixtures for record rows, report snapshots, and ordering assertions.
- [x] 4.3 Verify the final service/script contract uses the same result model for Markdown and JSON and keeps all output stable across repeated runs.
