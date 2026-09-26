# Tasks: raven(event) integration runtime slices (#441, #445, #440)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1900 across 3 issues |
| 400-line budget risk | Low (small PRs) |
| Chained PRs recommended | No |
| Suggested split | 1-2 PRs per issue |
| Delivery strategy | single-pr per issue (or chained if >400 LOC) |
| Files changed | ~11 new |

```text
Decision needed before apply: yes (Raven code location, auth scheme, audit storage)
Chained PRs recommended: no
Chain strategy: single-pr
400-line budget risk: low
```

## Suggested Work Units

### #441 JSON export contract (tracker `feat/441-event-export-contract`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W1 | Schema, endpoint/CLI, examples for OPEN/ACK/RECOVERED, backward-compat doc | `pytest backend/tests/test_event_export_contract.py -q` | `curl http://localhost:18000/api/events/export?status=OPEN` and inspect payload | revert `backend/schemas/event_export.py`, `backend/routers/event_export.py`, tests, docs |

### #445 Raven normalizer + CLI (tracker `feat/445-raven-normalizer-cli`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W2 | Field mapping, dedupe, reference resolution via #442 | `pytest backend/tests/test_raven_ingest_normalizer.py -q` | manual: feed sample next-gen event, observe Raven-shape output | revert normalizer, service, tests |
| W3 | CLI `raven event ingest --source next-gen`, batch, partial failure | `pytest backend/tests/test_raven_ingest_cli.py -q` | manual: pipe sample events to CLI, verify count + error reporting | revert CLI, tests |

### #440 Raven operator boundary (tracker `feat/440-raven-operator-boundary`)

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------------|-----------------|-------------------|
| W4 | Approval gate, dry-run default, audit emission | `pytest backend/tests/test_raven_operator_boundary.py backend/tests/test_raven_audit_emission.py -q` | manual: attempt external write, verify dry-run default and audit row | revert boundary service, router, tests |
| W5 | Rejection-with-reason, audit row completeness | (covered by W4 tests, possibly extended) | manual: reject a write with a reason, verify reason in audit | revert reason handling; W4 unaffected |

## Phase 1: Pre-flight (all slices)

- [ ] 1.1 Confirm Raven code lives in this repo or in a separate Raven repo (affects file paths)
- [ ] 1.2 Confirm authentication scheme between next-gen and Raven
- [ ] 1.3 Confirm audit storage (shared `audit_service` or Raven-specific table)
- [ ] 1.4 Confirm export transport (HTTP REST + CLI dump, or just one)

## Phase 2: #441 JSON export contract

### PR1 (schema + endpoint + docs)
- [ ] 2.1 RED tests in `backend/tests/test_event_export_contract.py`: schema validation for OPEN, ACK, RECOVERED; required fields present; `raw` carries verbatim next-gen payload
- [ ] 2.2 `backend/schemas/event_export.py` (or extension): Pydantic models for export shape with version
- [ ] 2.3 `backend/routers/event_export.py` (or extend events router): export endpoint
- [ ] 2.4 `docs/itsm/event-export-contract.md`: schema documentation + 3 examples + backward-compat policy
- [ ] 2.5 Confirm `/api/events` existing shape remains unchanged
- [ ] 2.6 GREEN tests; full backend suite green

## Phase 3: #445 Raven normalizer + CLI

### PR1 (normalizer + dedupe)
- [ ] 3.1 RED tests in `backend/tests/test_raven_ingest_normalizer.py`: field mapping (next-gen → Raven), severity/status mapping, dedupe key, reference resolution via #442, unknown-reference typed error
- [ ] 3.2 `backend/normalizers/next_gen_event_normalizer.py`: mapping logic
- [ ] 3.3 `backend/services/raven_ingest_service.py` (or equivalent): orchestrate normalize → resolve → persist-via-Raven-API (no direct DB)
- [ ] 3.4 GREEN tests

### PR2 (CLI + batch)
- [ ] 4.1 RED tests in `backend/tests/test_raven_ingest_cli.py`: stdin/file ingestion, batch partial failure, count + first error reporting, idempotent on dedupe key
- [ ] 4.2 `backend/cli/raven_event_ingest.py`: CLI implementation with `--source next-gen --stdin | --file <path>`
- [ ] 4.3 GREEN tests; full backend suite green; PR1 unaffected

## Phase 4: #440 Raven operator boundary

### PR1 (approval gate + audit)
- [ ] 5.1 RED tests in `backend/tests/test_raven_operator_boundary.py`: default dry-run, approval gate enforced, no bypass paths
- [ ] 5.2 RED tests in `backend/tests/test_raven_audit_emission.py`: audit row contains actor, source, target event id, payload hash, timestamp, before/after
- [ ] 5.3 `backend/services/raven_operator_boundary.py`: gate logic
- [ ] 5.4 `backend/routers/raven_recommendations.py` (or extension): surface recommendations in UX
- [ ] 5.5 GREEN tests

### PR2 (rejection with reason)
- [ ] 6.1 RED tests: rejection requires free-text reason; reason becomes part of audit row
- [ ] 6.2 Reason handling in boundary service
- [ ] 6.3 GREEN tests; full backend suite green; PR1 unaffected

## Critical sequencing

- Phase 3 depends on #442 (slice 1) merged — normalizer resolves references via #442
- Phase 4 depends on Phase 3 merged — boundary gates the writes that Phase 3 normalizes
- Phase 2 (#441) is independent but provides the export contract that Phase 3 consumes

## Cross-references

- Slice 1: #442 (approved) — alias/reference resolution
- Reference UX pattern: #154 (approved) — stale-event reminders shows recommendations UX
- Source proposal: `openspec/changes/feat-raven-event-integration-runtime/proposal.md`