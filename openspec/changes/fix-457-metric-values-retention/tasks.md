# Tasks: `metric_values` TimescaleDB Retention Policy (Issue #457)

**Change**: `fix-457-metric-values-retention`
**Branch**: `fix/457-metric-values-retention`
**Delivery strategy**: `single-pr` (no chained PRs, max LOC 800)
**Worktree**: `/private/tmp/next-gen-main-check/.worktrees/fix-457-metric-values-retention`
**Backbone**: design.md §Work-Unit Commit Plan (lines 421-438) — 4 commits, each ≤ 200 LOC.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 350-450 |
| 400-line budget risk | Low |
| 800-line review budget | Within budget |
| Chained PRs recommended | No |
| Suggested split | single PR — W1 → W2 → W3 → W4 |
| Delivery strategy | single-pr |
| Chain strategy | size-exception (not needed — under budget) |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units (commits inside the single PR)

| Unit | Goal | Commit message | Focused test command | Runtime harness | Rollback boundary |
|------|------|----------------|----------------------|-----------------|-------------------|
| W1 | Settings + service skeleton | `feat(retention): add metric_values retention settings + service skeleton` | `python3.11 -m pytest tests/test_retention_service.py -q` | N/A (no scheduler yet — pure unit) | Revert commit; delete `backend/services/retention_service.py` + `backend/tests/test_retention_service.py` |
| W2 | Boot-time apply + scheduler wiring | `feat(retention): wire boot-time apply + scheduler registration` | `python3.11 -m pytest tests/test_retention_service.py tests/test_main.py -q` | Manual: boot backend with `METRIC_RETENTION_ENABLED=true`; verify scheduler job id `"metric_retention_cleanup"` registered | Revert commit; main.py + metric_repo.py return to pre-change state; no SQL escape needed since policy itself is idempotent on next deploy |
| W3 | Docs + env example + spec cross-link | `docs(retention): update polling-pipeline-tuning + env.example + cap` | `python3.11 -m pytest tests/test_retention_service.py -q -k "default or override or invalid"` | N/A (docs + config only) | Revert commit; .env.example + docs revert cleanly |
| W4 | Out-of-window exclusion + rollback evidence | `chore(retention): integration smoke + verify report` | `python3.11 -m pytest tests/test_retention_service.py tests/test_main.py tests/test_event_prune_scheduler.py -q` | Optional integration gated by `RUN_TIMESCALE_INTEGRATION=1` | Revert commit; the smoke test is additive only |

## Work-unit W1: Settings + service skeleton (no scheduler wiring yet)

### Task W1.1: RED — write `test_metric_retention_settings_default_90_days`
- **Type**: RED
- **Work-unit**: W1
- **Files**: `backend/tests/test_retention_service.py` (NEW)
- **Spec**: REQ-MVR-002 scenario 1
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py::test_metric_retention_settings_default_90_days -q --tb=short` — fails (module not yet created).
- **Status**: done

### Task W1.2: RED — write `test_apply_metric_retention_idempotent_double_call`
- **Type**: RED
- **Work-unit**: W1
- **Files**: `backend/tests/test_retention_service.py`
- **Spec**: REQ-MVR-004 scenario 1
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py::test_apply_metric_retention_idempotent_double_call -q --tb=short` — fails. Test uses `MagicMock` engine whose `begin().__enter__().execute` raises `IntegrityError` once, then succeeds; asserts `add_retention_policy` called twice with identical args and no raise escapes.
- **Status**: done

### Task W1.3: RED — write `test_apply_metric_retention_30_day_override`
- **Type**: RED
- **Work-unit**: W1
- **Files**: `backend/tests/test_retention_service.py`
- **Spec**: REQ-MVR-002 scenario 2
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py::test_apply_metric_retention_30_day_override -q --tb=short` — fails. Asserts `apply_metric_retention(retention_days=30, engine=mock)` invokes SQL with interval string `"30 days"`.
- **Status**: done

### Task W1.4: GREEN — implement `MetricRetentionSettings` + `apply_metric_retention`
- **Type**: GREEN
- **Work-unit**: W1
- **Files**: `backend/services/retention_service.py` (NEW)
- **Spec**: REQ-MVR-001, REQ-MVR-002, REQ-MVR-004
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py -q --tb=short` — all green. Implementation mirrors design.md §Interfaces/Contracts: Pydantic `BaseModel` with `Field(ge=1, le=3650)` + `from_env()` classmethod + lazy singleton `get_metric_retention_settings()` + `apply_metric_retention()` wrapping `engine.begin()` with `IntegrityError`/`ProgrammingError` catches.
- **Status**: done

### Task W1.5: REFACTOR — extract SQL into module-level constant
- **Type**: REFACTOR
- **Work-unit**: W1
- **Files**: `backend/services/retention_service.py`
- **Spec**: REQ-MVR-001
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py -q --tb=short` — still green after extracting `_RETENTION_POLICY_SQL` (the `SELECT add_retention_policy('metric_values', INTERVAL :interval, if_not_exists => TRUE)` string) into a module-level constant for clarity.
- **Status**: done

### Task W1.6: VERIFY — work-unit W1 acceptance
- **Type**: VERIFY
- **Work-unit**: W1
- **Files**: `backend/tests/test_retention_service.py`
- **Spec**: REQ-MVR-001, REQ-MVR-002, REQ-MVR-004
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py -q --tb=short` — full W1 suite passes (3 RED → GREEN, idempotent + 30-day + default 90-day scenarios).
- **Status**: done

## Work-unit W2: Scheduler wiring + boot-time apply

### Task W2.1: RED — write `test_metric_retention_scheduler_registration_when_enabled`
- **Type**: RED
- **Work-unit**: W2
- **Files**: `backend/tests/test_metric_retention_scheduler.py` (NEW — design-pattern file mirrors `test_event_prune_scheduler.py`)
- **Spec**: REQ-MVR-003 scenario 1
- **Verify**: `cd backend && python3.11 -m pytest tests/test_metric_retention_scheduler.py::test_metric_retention_scheduler_registration_when_enabled -q --tb=short` — fails. Test patches `main.backup_scheduler` with `MagicMock` + patches `_METRIC_RETENTION_ENABLED=True`; asserts `add_job` called once with `id="metric_retention_cleanup"`, `CronTrigger` from crontab `"0 */6 * * *"`, `coalesce=True`, `max_instances=1`, `replace_existing=True`.
- **Status**: done

### Task W2.2: RED — write `test_metric_retention_scheduler_NOT_registered_when_disabled`
- **Type**: RED
- **Work-unit**: W2
- **Files**: `backend/tests/test_metric_retention_scheduler.py`
- **Spec**: REQ-MVR-003 scenario 2
- **Verify**: `cd backend && python3.11 -m pytest tests/test_metric_retention_scheduler.py::test_metric_retention_scheduler_NOT_registered_when_disabled -q --tb=short` — fails. Sets `METRIC_RETENTION_ENABLED=false` via `monkeypatch.setenv`; asserts `backup_scheduler.add_job` never called with `id="metric_retention_cleanup"`.
- **Status**: done

### Task W2.3: GREEN — implement `run_metric_retention_cleanup` + register on `backup_scheduler`
- **Type**: GREEN
- **Work-unit**: W2
- **Files**: `backend/services/retention_service.py`, `backend/main.py`
- **Spec**: REQ-MVR-001 scenario 2, REQ-MVR-003
- **Verify**: `cd backend && python3.11 -m pytest tests/test_metric_retention_scheduler.py::test_metric_retention_scheduler_registration_when_enabled tests/test_metric_retention_scheduler.py::test_metric_retention_scheduler_NOT_registered_when_disabled -q --tb=short` — both green. Adds `run_metric_retention_cleanup()` to `retention_service.py` (honors kill-switch, queries `timescaledb_information.jobs`, re-applies if missing) and `_register_metric_retention_job()` helper in `main.py` next to `_register_event_prune_job`, wired into startup after the event-prune job registration.
- **Status**: done

### Task W2.4: GREEN — wire boot-time apply in `metric_repo.create_hypertable`
- **Type**: GREEN
- **Work-unit**: W2
- **Files**: `backend/repositories/metric_repo.py`
- **Spec**: REQ-MVR-001 scenario 1, REQ-MVR-006
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py tests/test_metric_retention_scheduler.py -q --tb=short` — full W2 suite green. After `SELECT create_hypertable(...)` succeeds, call `apply_metric_retention(engine=db.get_bind(), retention_days=get_metric_retention_settings().retention_days)` inside the existing try block; wrap in try/except so a retention-apply failure logs WARNING and does NOT crash startup (REQ-MVR-003).
- **Status**: done

### Task W2.5: VERIFY — work-unit W2 acceptance
- **Type**: VERIFY
- **Work-unit**: W2
- **Files**: `backend/tests/test_retention_service.py`, `backend/tests/test_metric_retention_scheduler.py`
- **Spec**: REQ-MVR-001, REQ-MVR-003
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py tests/test_metric_retention_scheduler.py -q --tb=short` — all green. Confirms scheduler knobs + boot-time wiring coexist with no regressions in existing audit/event-prune tests.
- **Status**: done

## Work-unit W3: Docs, env example, settings wiring

### Task W3.1: DOCS — rewrite `polling-pipeline-tuning.md` line 109 caveat
- **Type**: DOCS
- **Work-unit**: W3
- **Files**: `docs/polling-pipeline-tuning.md`
- **Spec**: REQ-MVR-006 (forward-looking semantics)
- **Verify**: `python3.11 -c "import pathlib; p=pathlib.Path('docs/polling-pipeline-tuning.md'); lines=p.read_text().splitlines(); print(lines[108]); assert 'wait for evidence' not in p.read_text().lower(); assert 'metric_values' in p.read_text().lower() and '#457' in p.read_text()"` — passes. Replaces the line 109 "wait for evidence" caveat with a cross-reference to issue #457 + REQ-MVR-006 forward-only semantics; preserves compression + downsampling deferral.
- **Status**: done

### Task W3.2: CONFIG — add env vars to `.env.example`
- **Type**: CONFIG
- **Work-unit**: W3
- **Files**: `.env.example`
- **Spec**: REQ-MVR-002, REQ-MVR-003
- **Verify**: `grep -n "METRIC_RETENTION_ENABLED" .env.example` returns 1 line; `grep -n "METRIC_RETENTION_DAYS" .env.example` returns 1 line; `grep -n "# --- Metric values retention ---" .env.example` returns 1 line. Adds a `# --- Metric values retention ---` header block containing `METRIC_RETENTION_ENABLED=true` and `METRIC_RETENTION_DAYS=90` (defaults match service constants).
- **Status**: done

### Task W3.3: CONFIG — extend `backend/config.py` with `MetricRetentionSettings` sub-block
- **Type**: CONFIG
- **Work-unit**: W3
- **Files**: `backend/config.py`
- **Spec**: REQ-MVR-002, REQ-MVR-003
- **Verify**: `cd backend && python3.11 -c "from config import MetricRetentionSettings, Settings; s=Settings(); assert hasattr(s, 'metric_retention'); assert s.metric_retention.retention_days in (1,3650,90); print('ok')"` — exits 0. Mirrors the `EventPruneSettings` (config.py:253) precedent: `class MetricRetentionSettings(BaseModel)` with bounded int + `from_env()` classmethod; expose as `Settings.metric_retention` sub-settings block (re-export from `services/retention_service.py`).
- **Status**: done

## Work-unit W4: Out-of-window exclusion + rollback evidence

### Task W4.1: RED — write `test_apply_metric_retention_excludes_out_of_window_rows`
- **Type**: RED
- **Work-unit**: W4
- **Files**: `backend/tests/test_retention_service.py`
- **Spec**: REQ-MVR-005 scenario 1, REQ-MVR-006
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py::test_apply_metric_retention_excludes_out_of_window_rows -q --tb=short` — fails (no implementation yet). Test stubs a `timescaledb_information.jobs` query + a `metric_values` SELECT-after-policy filter via `unittest.mock`; inserts a row with `time = now() - 100 days`; asserts the row is NOT returned after `apply_metric_retention(retention_days=30)` is invoked.
- **Status**: done

### Task W4.2: GREEN — refine `apply_metric_retention` if needed
- **Type**: GREEN
- **Work-unit**: W4
- **Files**: `backend/services/retention_service.py`
- **Spec**: REQ-MVR-005, REQ-MVR-006
- **Verify**: `cd backend && python3.11 -m pytest tests/test_retention_service.py::test_apply_metric_retention_excludes_out_of_window_rows -q --tb=short` — green. Most likely the existing `apply_metric_retention` already satisfies this; verify by re-running the suite and only patching if the test demands additional defensive handling.
- **Status**: done

### Task W4.3: VERIFY — work-unit W4 acceptance + full touched-file sweep
- **Type**: VERIFY
- **Work-unit**: W4
- **Files**: `backend/tests/test_retention_service.py`, `backend/tests/test_metric_retention_scheduler.py`, `backend/tests/test_event_prune_scheduler.py`
- **Spec**: REQ-MVR-005, REQ-MVR-006
- **Verify**: First focused: `cd backend && python3.11 -m pytest tests/test_retention_service.py -q -k "out_of_window or idempotent or override or scheduler or default" --tb=short` — all green. Then full touched-file sweep: `cd backend && python3.11 -m pytest tests/test_retention_service.py tests/test_metric_retention_scheduler.py tests/test_event_prune_scheduler.py -q --tb=short` — all green (25 passed); confirms no regression in the precedent scheduler tests.
- **Status**: done

## Final Block

- **Total task count**: 17 (W1: 6, W2: 5, W3: 3, W4: 3)
- **Estimated LOC**: 350-450 authored (under the 800 review budget)
- **Per-commit LOC**: W1 ≤ 200, W2 ≤ 200, W3 ≤ 100, W4 ≤ 100
- **Total review effort**: 1 PR, 4 commits
- **Risk to deliverability**: low — every pattern is mirrored from existing precedents (`EventPruneSettings`, `run_audit_retention_cleanup`, `_register_event_prune_job`); no novel infra; threat matrix is `N/A`.
- **TDD discipline**: every work-unit follows RED → GREEN → REFACTOR → VERIFY strictly. RED tests land before any production code; no GREEN implementation precedes its RED test.
- **Out-of-scope guard**: do NOT touch compression policies, downsampling, continuous aggregates, chunk-drop backfill, or any other retention window; do NOT modify `proposal.md`, `design.md`, or `specs/metric-values-retention/spec.md`.
