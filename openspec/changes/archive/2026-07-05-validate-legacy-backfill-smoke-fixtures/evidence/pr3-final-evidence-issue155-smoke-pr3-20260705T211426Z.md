# PR3 Final Evidence: Issue #155 Smoke Fixtures

## Scope

- Run id: `issue155-smoke-pr3-20260705T211426Z`
- Scope: shared local Neo4j only.
- Production mutation: none.
- Backfill/migration apply path: not used; no `--apply` command was run.
- Environment: approved root checkout test-env sample was sourced; no denied `.env` file was read.
- No Docker or new test environment was added.

## Runtime Artifacts

- Validation manifest: `pr3-validation-smoke-issue155-smoke-pr3-20260705T211426Z.json`
- Sanitized smoke-scoped audit evidence: `pr3-smoke-audit-issue155-smoke-pr3-20260705T211426Z.json`
- Failure-safe verification evidence: `pr3-failure-safe-verification-issue155-smoke-pr3-20260705T211426Z.json`

## Seeded Fixture Plan

- Seeded marker-scoped `Event` nodes: 3
- Marker: `issue155_smoke=true`
- Run id field: `issue155_smoke_run_id=issue155-smoke-pr3-20260705T211426Z`

| Event id | Expected bucket | Actual bucket |
| --- | --- | --- |
| `issue155-smoke-pr3-20260705T211426Z-safe` | `safe_candidates` | `safe_candidates` |
| `issue155-smoke-pr3-20260705T211426Z-ambiguous` | `ambiguous_records` | `ambiguous_records` |
| `issue155-smoke-pr3-20260705T211426Z-no-touch` | `no_touch_records` | `no_touch_records` |

## Sanitized Audit Output

- Persisted schema: `issue155_smoke_scoped_audit_v1`
- Persisted scope: smoke fixture findings only; non-smoke finding details omitted.
- Smoke findings persisted: 6
- Smoke event ids with findings: `issue155-smoke-pr3-20260705T211426Z-ambiguous`, `issue155-smoke-pr3-20260705T211426Z-no-touch`
- Safe fixture has no audit finding by design and is validated through direct classifier reuse.

## Classification Comparison

- Expected counts: `{'ambiguous_records': 1, 'no_touch_records': 1, 'safe_candidates': 1}`
- Actual counts: `{'ambiguous_records': 1, 'no_touch_records': 1, 'safe_candidates': 1}`
- Mismatches: `[]`
- Valid for planning: `True`
- Aggregate recommendation gap: `gap_recorded` — aggregate recommendation JSON does not expose per-record smoke fixture ids, so smoke-only validation uses sanitized audit JSON for ambiguous/no-touch records and direct classifier reuse for the safe record.

## Cleanup Proof

- Cleanup verified: `True`
- Deleted marker-scoped records: `3`
- Remaining marked records for this run id: `0`
- Cleanup query remained marker/run-id scoped and verified zero remaining marked nodes after deletion.

## Failure-Safe Verification

- Focused unit command: `python3 openspec/changes/validate-legacy-backfill-smoke-fixtures/evidence/test_validate_smoke_fixtures.py`
- Result: `Ran 24 tests in 0.169s; OK`
- Covered failure paths: audit/report error, classifier/validation error, cleanup failure after prior error, and cleanup verification failure after prior audit/classifier errors.
- Evidence: `pr3-failure-safe-verification-issue155-smoke-pr3-20260705T211426Z.json`

## Final Status

PR3 evidence is complete and tied to run id `issue155-smoke-pr3-20260705T211426Z`. The evidence is local-only and does not support any production-scale conclusion beyond the smoke-fixture validation slice.
