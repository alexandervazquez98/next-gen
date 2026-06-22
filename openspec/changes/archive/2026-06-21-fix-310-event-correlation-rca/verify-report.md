# Verification Report: fix-310-event-correlation-rca — PR 1 + PR 2 Combined

## Verdict

**PASS WITH WARNINGS** — PR 1 + PR 2 satisfy all eight `REQ-CORR-*` requirements with runtime test evidence. Targeted backend tests for the 72 new/changed correlation tests pass, and the full frontend suite passes. The full backend suite still exits non-zero with 63 known pre-existing failures, so the overall result remains warnings-only rather than a clean pass.

## Inputs Read

- `openspec/changes/fix-310-event-correlation-rca/spec.md`
- `openspec/changes/fix-310-event-correlation-rca/design.md`
- `openspec/changes/fix-310-event-correlation-rca/tasks.md`
- Prior `openspec/changes/fix-310-event-correlation-rca/verify-report.md`
- Engram apply-progress: `sdd/fix-310-event-correlation-rca/apply-progress` (#2412)
- Strict TDD module: `/home/alex/.claude/skills/sdd-verify/strict-tdd-verify.md`

## Completeness Table

| Area | Status | Evidence |
|---|---:|---|
| T1-T14 | PASS | Tasks are marked complete through PR 2; T15 remains pending for PR 3 documentation. |
| T15 | WARNING | Explicitly pending/out of scope for PR 3: CHANGELOG + ops dashboard recalibration note. |
| Requirements REQ-CORR-1..8 | PASS | Each requirement has source evidence and passing targeted runtime tests. |
| Backend targeted tests | PASS | 72/72 new PR 1 + PR 2 tests passed. |
| Backend full suite | WARNING | `63 failed, 1167 passed, 1 skipped`; failures are known pre-existing auth/permission/RTU/etc. failures. |
| Frontend full suite | PASS | `58 passed` files, `485 passed` tests. |

## Build / Test Evidence

| Command | Result | Summary |
|---|---:|---|
| `uv run pytest backend/tests/test_path_a_rca_chain.py -v` | PASS | 12 passed, 91 warnings |
| `uv run pytest backend/tests/test_polling_event_writer_chain.py -v` | PASS | 6 passed, 1 warning |
| `uv run pytest backend/tests/test_cli_worker_correlation.py -v` | PASS | 4 passed, 1 warning |
| `uv run pytest backend/tests/test_event_authoritative.py -v` | PASS | 10 passed, 1 warning |
| `uv run pytest backend/tests/test_resolve_correlation_fields.py -v` | PASS | 10 passed, 1 warning |
| `uv run pytest backend/tests/test_escalation_notifier.py -v` | PASS | 7 passed, 1 warning |
| `uv run pytest backend/tests/test_events_api_filter.py -v` | PASS | 9 passed, 5 warnings |
| `uv run pytest backend/tests/test_path_a_rca_chain.py::TestDepthCoverageExtension -v` | PASS | 2 passed, 19 warnings |
| `uv run pytest backend/tests/test_path_a_rca_chain.py::TestFanOutChain backend/tests/test_path_a_rca_chain.py::TestThreeHopChain backend/tests/test_path_a_rca_chain.py::TestMixedSeveritiesRegression -v` | PASS | 10 passed, 73 warnings |
| `uv run pytest backend/tests/test_correlation_cache.py -v` | PASS | 8 passed, 1 warning |
| `pnpm --dir frontend run test:run hooks/useEventCorrelation_connects_to.test.ts` | PASS | 1 file passed, 6 tests passed |
| `uv run pytest backend/tests/ -q --no-header` | WARNING | 63 failed, 1167 passed, 1 skipped, 409 warnings; full output: `/home/alex/.local/share/opencode/tool-output/tool_eed5391f3001yagk4Cr3OxH3Gi` |
| `pnpm --dir frontend run test:run` | PASS | 58 files passed, 485 tests passed; full output: `/home/alex/.local/share/opencode/tool-output/tool_eed537613001t5zuuDPcgx95DA` |

## Spec Compliance Matrix

| Requirement | Status | Runtime Evidence | Source Evidence |
|---|---:|---|---|
| REQ-CORR-1 — Path A write-side correlation | PASS | `test_path_a_rca_chain.py` → 12/12 passed | `backend/engines/snmp_worker.py` uses `resolve_correlation_fields` via `_tag_failure_with_correlation`; Cypher writes row correlation params. |
| REQ-CORR-2 — Path C write-side correlation | PASS | `test_polling_event_writer_chain.py` → 6/6 passed | `backend/polling/snmp_worker.py` pre-tags envelope metadata before `event_writer.batch_update_events`; `event_writer.py` preserves fields. |
| REQ-CORR-3 — CLI poll alerts correlation | PASS | `test_cli_worker_correlation.py` → 4/4 passed | `backend/engines/cli_worker.py` resolves the MetricDef-owning CI and writes `CLI_POLL_ALERT` correlation fields. |
| REQ-CORR-4 — authoritative event helper | PASS | `test_event_authoritative.py` → 10/10 passed | `_is_authoritative_event` returns false only for `PROPAGATED`, including mixed-case. |
| REQ-CORR-5 — escalation gating | PASS | `test_escalation_notifier.py` → 7/7 passed | `backend/services/escalation_notifier.py` delegates to `_is_authoritative_event` and suppresses propagated events. |
| REQ-CORR-6 — events API filtering | PASS | `test_events_api_filter.py` → 9/9 passed | `GET /api/events` defaults to authoritative-only; `include=propagated` and `include=all` opt in. |
| REQ-CORR-7 — frontend CONNECTS_TO grouping | PASS | `useEventCorrelation_connects_to.test.ts` → 6/6 passed | `frontend/hooks/useEventCorrelation.ts` includes `CONNECTS_TO` with `DEPENDS_ON`/`HOSTED_ON`. |
| REQ-CORR-8 — traversal depth and relationship types | PASS | `TestDepthCoverageExtension` → 2/2 passed | `topology_repo.find_open_parent_event` still traverses `DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3`; true 3-hop found, 4-hop ignored. |

## Correctness Table

| Check | Status | Evidence |
|---|---:|---|
| Multi-CI Path A centerpiece | PASS | `TestFanOutChain`, `TestThreeHopChain`, `TestMixedSeveritiesRegression` all pass (10 tests). |
| Memo cache T12 | PASS | `test_correlation_cache.py` 8/8 passed. |
| API default is breaking but intentional | PASS | `test_events_api_filter.py` validates authoritative-only default and opt-in all/propagated behavior. |
| PR 2 new tests | PASS | 32/32 pass: 26 backend + 6 frontend. |
| PR 1 new tests | PASS | 40/40 pass: Path A chain, authoritative helper, resolver, cache. |

## Design Coherence

| Design Item | Status | Evidence |
|---|---:|---|
| Shared resolver in `event_service.py` | PASS | Implemented and used by Path A, Path C, and CLI alert path. |
| Fail-safe ROOT behavior | PASS | Resolver/cache and producer tests cover fallback semantics. |
| Per-cycle memo cache | PASS | Path A/Path C plumb cache; `test_correlation_cache.py` locks TTL behavior. |
| Authoritative consumer gate | PASS | Escalation and events API use authoritative semantics; frontend grouping remains presentation-only. |
| T15 rollout note | WARNING | Still pending for PR 3 by user direction. |

## Strict TDD Compliance

| Check | Result | Details |
|---|---:|---|
| TDD evidence reported | PASS | Engram apply-progress #2412 contains PR 2 TDD cycle evidence; tasks.md contains PR 1/2 commit mapping. |
| Commit list observable | PASS | `git log main..HEAD --oneline` shows 27 expected commits on `fix/310-event-correlation-rca`. |
| RED→GREEN pairs | PASS | 8 primary pairs: T1/T2, T3/T4, T5/T6, T7, T8, T9, T10, T11. |
| RED commit test-only check | PASS | RED commits touched test files only: `40f29be`, `2649bde`, `4056497`, `5256b2a`, `d8b03d8`, `118c293`, `51211e6`, `a0ccf67`. |
| GREEN commit production check | PASS | GREEN commits touched production files for the corresponding requirement. |
| Refactor/fix/artifact commits | PASS | 11 commits are fixture/test-fix/cache/artifact/follow-up commits. |
| Deviations | WARNING | T12 cache implementation and tests were bundled in `a422656`; T11 GREEN also adjusted one frontend test scenario to match the actual hook grouping contract. |
| Assertion quality | PASS | Targeted tests assert concrete behavior: correlation fields, root IDs, propagated parent IDs, query filter text, router kwargs, and grouped event membership. |

## Test Layer Distribution

| Layer | Tests | Files | Tools |
|---|---:|---:|---|
| Backend unit/service/API-style | 54 | 7 | pytest |
| Backend integration with `MockNeo4jDriver` | 18 | 2 | pytest |
| Frontend hook unit | 6 | 1 | vitest |
| E2E | 0 | 0 | Not used in this change |
| **Total targeted PR 1 + PR 2** | **78** | **10** | |

Note: the 78 targeted runs include 6 existing centerpiece class tests selected separately; the net new PR 1 + PR 2 test count remains 72 (40 + 32).

## Changed File Coverage

Coverage analysis skipped — no coverage command was provided in the verification preflight. This is informational and non-blocking.

## LOC Delta vs Forecast

`git diff --stat main..HEAD`: **3539 insertions**, **1747 deletions**, 37 files changed, vs cumulative forecast **820-1030**.

| Category | Lines | Classification |
|---|---:|---|
| Production code for this change | 365 insertions / 28 deletions across 7 files | Within budget |
| Tests/fixtures | 2546 insertions | WARNING — mandated by strict TDD and user-directed coverage |
| OpenSpec artifacts | 613 insertions for active change | Required SDD artifacts |
| Unrelated archived/deleted main deltas visible in `main..HEAD` | 0 insertions / 1489 deletions plus workflow/docs deltas | WARNING — diff includes branch/base divergence from archived frontend volume renewal artifacts, not PR 1/2 runtime scope |

The over-budget finding is a **WARNING, not CRITICAL**: production code remains within budget; the overage is dominated by mandated test/fixture code and SDD artifacts.

## Out-of-Scope Confirmation

Confirmed not touched in `git diff main..HEAD`:

- `docker-compose.yml`
- `backend/main.py`
- `backend/services/ai_chat_service.py`
- `backend/services/snmp_service.py` / Path B collector
- backend migration/backfill files

`git diff --name-only main..HEAD -- docker-compose.yml backend/main.py backend/services/ai_chat_service.py backend/services/snmp_service.py backend/migrations` returned no files. The broader stat does show unrelated deleted frontend volume renewal scripts/artifacts from branch/base divergence; these are not backfill migration scripts and do not affect the #310 runtime scope.

## Issues

### CRITICAL

None.

### WARNING

1. Full backend suite still exits non-zero with 63 known pre-existing failures (auth/permission expected status mismatches, RTU repository/router failures, dictionary service failures, one existing event-correlation isolation failure). These are not PR 1/2 regressions.
2. Cumulative LOC exceeds the 820-1030 forecast, but production code is within budget; mandated test/fixture and SDD artifact volume explain the overage.
3. Strict TDD deviations: T12 cache landed as implementation+tests in one commit, and T11 GREEN adjusted one frontend test scenario while adding the production change.
4. T15 documentation/ops note remains pending for PR 3.

### SUGGESTION

1. PR 3 should add the CHANGELOG/ops note and mention lower open-event/KPI/escalation/ITSM counts after cascade deduplication.
2. Consider a drive-by follow-up for the pre-existing `backend/tests/test_cli_worker.py` sys.path issue currently masked by collection order.

## Final Recommendation

**next_recommended: apply** — run PR 3 for T15 (CHANGELOG + ops dashboard recalibration note), then verify/archive the completed change.
