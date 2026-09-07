# Design: `metric_values` TimescaleDB Retention Policy (Issue #457)

## Technical Approach

This change introduces a forward-looking TimescaleDB retention policy for the `metric_values` hypertable, anchored to `METRIC_RETENTION_DAYS` (default 90, range 1..3650). The contract surface is fixed by the delta spec at `openspec/changes/fix-457-metric-values-retention/specs/metric-values-retention/spec.md` (REQ-MVR-001..006, 12 scenarios) and the proposal at `openspec/changes/fix-457-metric-values-retention/proposal.md`.

The implementation follows the `audit_service.run_audit_retention_cleanup` precedent (`backend/services/audit_service.py:288-295`) and the `EventPruneSettings` config precedent (`backend/config.py:253-342`). The flow is:

1. `MetricRetentionSettings.from_env()` reads env vars with a Pydantic `BaseModel` + `Field` validators and a `from_env` classmethod (matches existing pattern); invalid `METRIC_RETENTION_DAYS` falls back to 90 with a `WARNING` log line.
2. A new `backend/services/retention_service.py` exposes `apply_metric_retention()` (idempotent SQL wrapper) and `run_metric_retention_cleanup()` (defensive scheduler entrypoint).
3. `backend/repositories/metric_repo.py:create_hypertable` calls `apply_metric_retention()` after `create_hypertable` succeeds (boot-time path).
4. `backend/main.py` registers `run_metric_retention_cleanup` on `backup_scheduler` via `CronTrigger` every 6 hours with `coalesce=True, max_instances=1, replace_existing=True`, guarded by `_METRIC_RETENTION_ENABLED` (mirroring `_register_event_prune_job` at `backend/main.py:998`).
5. `.env.example` adds the two env vars; `docs/polling-pipeline-tuning.md:109` is updated to retire the "wait for evidence" caveat with a cross-reference to issue #457.

Idempotency is the load-bearing invariant: `add_retention_policy` does **not** raise on a duplicate matching config in TimescaleDB 2.x — it returns the existing `job_id`. The wrapper still catches `IntegrityError` defensively in case the driver surfaces it on race conditions across scheduler ticks. Boot-time failure (missing extension, missing table, missing perms) logs `ERROR` and continues without crashing startup, per the kill-switch semantics from REQ-MVR-003.

## Architecture Decisions

### Decision: Pydantic `BaseModel` with `from_env()` classmethod (not `BaseSettings`)

| Aspect | BaseModel + from_env | BaseSettings auto-bind |
|---|---|---|
| Consistency with codebase | Matches all 10 existing settings classes in `backend/config.py:79-703` (TimeSync, EventLock, EventBatch, EventPrune, MQTT, ICMPSettings, etc.) | Introduces a second pattern |
| Env-var error handling | Explicit `from_env()` lets us log a `WARNING` on invalid input (mirrors `_parse_system_status_int` at `main.py:63-81`) | Pydantic raises `ValidationError` on bad input; we'd have to wrap every loader |
| Test ergonomics | `MetricRetentionSettings(retention_days=30)` works directly without env patching | Requires `monkeypatch.setenv` + re-instantiate |
| Bounded integers | `Field(ge=1, le=3650)` works on BaseModel | Same |

**Choice**: `BaseModel` + `from_env()`.
**Rationale**: Mirrors `EventPruneSettings.from_env()` (the explicit precedent in this fix) and keeps invalid-value fallback semantics auditable in one helper rather than scattered across Pydantic validators. The codebase imports only `BaseModel` and `Field` from `pydantic` (`config.py:12`) — `BaseSettings` is never used.

### Decision: Sync `engine.begin()` (not async session)

**Choice**: Use the existing `postgres_db.engine` with a sync `with engine.begin() as conn:` block, matching `audit_service.cleanup_old_events` (`backend/services/audit_service.py:273-285`) and `_ensure_refresh_token_schema_migration` (`backend/main.py:276-341`).
**Rationale**: The `metric_values` hypertable is a SQLAlchemy ORM-mapped table accessed via sync sessions everywhere (`metric_repo.py:18,37,54`). Boot-time apply is called once per process startup; scheduler entrypoint runs in `AsyncIOScheduler` but invokes sync code under a worker thread by design (same as `run_audit_retention_cleanup`). Async sessions would add an `AsyncSession` codepath for one idempotent DDL.

### Decision: CronTrigger every 6 hours (not 24h, not 1h)

**Choice**: Register `run_metric_retention_cleanup` with `CronTrigger(hour="*/6")` (00:00, 06:00, 12:00, 18:00 UTC).
**Rationale**: The scheduler entrypoint is a defensive re-apply (REQ-MVR-001 scenario 2) — it only writes if the policy is missing. 6h cadence is the audit-cleanup precedent's neighborhood (`run_audit_retention_cleanup` runs daily at 03:30). Hourly would be wasteful; daily would risk a 24h gap where a missing policy leaves chunks un-pruned if the boot-time apply failed silently. 6h gives operator observability without thrashing `timescaledb_information.jobs`.

### Decision: Idempotency via TimescaleDB native + `IntegrityError` catch

**Choice**: Wrap `add_retention_policy('metric_values', INTERVAL '<N> days')` in `try/except IntegrityError`, treat the duplicate as success.
**Rationale**: TimescaleDB 2.x returns the existing `job_id` on `add_retention_policy` for an identical config — the function does not raise on the happy idempotent path. We still catch `IntegrityError` (`sqlalchemy.exc.IntegrityError`, already imported at `backend/middleware/rate_limit.py:13`) to absorb edge cases where two scheduler ticks race or a partial migration state surfaces a unique constraint violation on `timescaledb_information.jobs`. No `remove_retention_policy` is called — we never tear down and re-create; the function only ensures the policy exists.

### Decision: Where to call `apply_metric_retention` on boot

| Location | Pros | Cons |
|---|---|---|
| `backend/main.py` startup event (alongside `create_hypertable`) | Centralized; one place to add telemetry | Layer-crossing — `main.py` knows about TimescaleDB policy details |
| `backend/repositories/metric_repo.py:create_hypertable` | Co-located with hypertable creation; metrics repo is the natural owner | `metric_repo.py` must import `MetricRetentionSettings` (acceptable — it already imports `models.timescale_models`) |

**Choice**: Call from `create_hypertable` (option 2).
**Rationale**: Keeps the SQL surface for `metric_values` in one file. `MetricRetentionSettings.from_env()` is a pure function with no module-level state, so the import is cheap. The boot-time path in `main.py` already wraps the call in try/except (line 453), so a retention-policy failure inherits that safety net for free.

## Data Flow

```
                        ┌───────────────────────────────┐
   process startup ───▶ │ main.py: startup_event         │
                        │   ├─ create_hypertable(db)     │
                        │   │    └─ apply_metric_retention│
                        │   │       (boot-time, idempotent)│
                        │   ├─ _register_metric_          │
                        │   │     retention_job           │
                        │   └─ backup_scheduler.start()  │
                        └────────────┬──────────────────┘
                                     │
                                     ▼
                        ┌───────────────────────────────┐
                        │ MetricRetentionSettings.from_env│
                        │   ├─ METRIC_RETENTION_ENABLED   │
                        │   └─ METRIC_RETENTION_DAYS      │
                        └────────────┬──────────────────┘
                                     │
                                     ▼
   every 6h ──────────▶ ┌───────────────────────────────┐
                        │ backup_scheduler tick          │
                        │   └─ run_metric_retention_     │
                        │        cleanup()               │
                        │       ├─ query timescaledb_   │
                        │       │  information.jobs     │
                        │       └─ apply if missing     │
                        └────────────┬──────────────────┘
                                     │
                                     ▼
                        ┌───────────────────────────────┐
                        │ TimescaleDB                    │
                        │  add_retention_policy(         │
                        │    'metric_values',            │
                        │    INTERVAL '<N> days')        │
                        └────────────────────────────────┘
```

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/services/retention_service.py` | Create | `MetricRetentionSettings`, `apply_metric_retention`, `run_metric_retention_cleanup`, `get_metric_retention_settings` factory |
| `backend/services/__init__.py` | Modify (if needed) | Re-export `MetricRetentionSettings` for the tests, matching `EventPruneSettings` re-export convention if one exists |
| `backend/config.py` | Modify | Add `MetricRetentionSettings(BaseModel)` after `EventPruneSettings` block (~line 343); mirror `from_env()` pattern with bounded int parser reusing `_env_int_bounded` |
| `backend/main.py` | Modify | (a) Module-level `_METRIC_RETENTION_ENABLED` / `_METRIC_RETENTION_DAYS` globals after line 53; (b) `_reload_metric_retention_env_settings()` helper after `_reload_event_prune_env_settings` (line 157); (c) call `_reload_metric_retention_env_settings()` near line 197; (d) `_register_metric_retention_job()` helper near `_register_event_prune_job` (line 998); (e) register the job in startup near line 511; (f) call `apply_metric_retention` defensively in `metric_repo.create_hypertable` (not main) |
| `backend/repositories/metric_repo.py` | Modify | After successful `create_hypertable` SQL (line 18), call `apply_metric_retention(retention_days=get_metric_retention_settings().retention_days, engine=db.get_bind())` inside the existing `try:` block; new `except IntegrityError` logs DEBUG and continues |
| `backend/tests/test_retention_service.py` | Create | Strict-TDD tests for REQ-MVR-001..006 scenarios 1, 2, 4, 5 |
| `backend/tests/test_metric_retention_scheduler.py` | Create | REQ-MVR-003 kill-switch + registration tests; mirrors `test_event_prune_scheduler.py` |
| `backend/tests/test_main.py` (or new file) | Modify/Create | Extend scheduler wiring tests; or add to `test_metric_retention_scheduler.py` |
| `.env.example` | Modify | Add `METRIC_RETENTION_ENABLED` and `METRIC_RETENTION_DAYS` after the EVENT_PRUNE block (line 105) |
| `docs/polling-pipeline-tuning.md` | Modify | Replace line 109 caveat with cross-reference to issue #457 and forward-only semantics; preserve compression/downsampling deferral |
| `openspec/specs/metric-values-retention/spec.md` | (no change in this phase) | Already exists; future sdd-archive will sync delta into canonical spec |

## Interfaces / Contracts

### `backend/services/retention_service.py`

```python
"""TimeScaleDB retention helpers for the metric_values hypertable.

Issue #457. Mirrors ``audit_service.run_audit_retention_cleanup`` semantics;
see ``openspec/changes/fix-457-metric-values-retention/proposal.md``.
"""

from __future__ import annotations

import logging
import os
from typing import Final

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# --- Constants -------------------------------------------------------------

METRIC_RETENTION_DEFAULT_DAYS: Final[int] = 90
METRIC_RETENTION_MIN_DAYS: Final[int] = 1
METRIC_RETENTION_MAX_DAYS: Final[int] = 3650
METRIC_HYPERTABLE_NAME: Final[str] = "metric_values"


# --- Settings ---------------------------------------------------------------

class MetricRetentionSettings(BaseModel):
    """Runtime settings for the ``metric_values`` retention scheduler.

    Mirrors ``backend.config.EventPruneSettings`` (fix-423 PR #2):
    env-driven, invalid values fall back to defaults, kill-switch honored.

    Attributes:
        enabled: ``METRIC_RETENTION_ENABLED`` kill-switch (default True).
        retention_days: ``METRIC_RETENTION_DAYS`` window (default 90, 1..3650).
    """

    enabled: bool = True
    retention_days: int = Field(
        default=METRIC_RETENTION_DEFAULT_DAYS,
        ge=METRIC_RETENTION_MIN_DAYS,
        le=METRIC_RETENTION_MAX_DAYS,
    )

    @classmethod
    def from_env(cls) -> "MetricRetentionSettings":
        """Load metric retention settings from environment with safe defaults.

        Invalid ``METRIC_RETENTION_DAYS`` returns ``retention_days=90`` and
        logs a WARNING. Mirrors ``_parse_system_status_int`` in main.py:63-81.
        """
        def _int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None:
                return default
            try:
                value = int(raw.strip())
                if not (METRIC_RETENTION_MIN_DAYS <= value <= METRIC_RETENTION_MAX_DAYS):
                    raise ValueError(f"{name} out of range")
                return value
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Invalid METRIC_RETENTION_DAYS=%r, using default %s: %s",
                    raw, default, exc,
                )
                return default

        enabled_raw = os.getenv("METRIC_RETENTION_ENABLED", "true").strip().lower()
        enabled = enabled_raw in {"1", "true", "yes", "on"}
        # Invalid bool falls back to True — safe default, mirrors
        # _parse_system_status_bool / EventPruneSettings.from_env().
        return cls(
            enabled=enabled if enabled_raw in {
                "0", "false", "no", "off", "1", "true", "yes", "on",
            } else True,
            retention_days=_int("METRIC_RETENTION_DAYS", METRIC_RETENTION_DEFAULT_DAYS),
        )


_settings: MetricRetentionSettings | None = None


def get_metric_retention_settings() -> MetricRetentionSettings:
    """Lazy singleton; tests can patch the cached instance directly."""
    global _settings
    if _settings is None:
        _settings = MetricRetentionSettings.from_env()
    return _settings


# --- SQL surface ------------------------------------------------------------

_ADD_RETENTION_POLICY_SQL = (
    "SELECT add_retention_policy("
    "'metric_values', INTERVAL :interval, if_not_exists => TRUE);"
)
# NOTE: TimescaleDB 2.x ``add_retention_policy`` does NOT accept
# ``if_not_exists``. The wrapper below handles duplicates via ``timescaledb_information.jobs``
# lookup + catch IntegrityError. The if_not_exists syntax is what we WANT;
# TimescaleDB surfaces it as a no-op when the same hypertable already has
# exactly one RetentionPolicy job.


def apply_metric_retention(
    *,
    engine: Engine,
    retention_days: int,
) -> None:
    """Idempotently apply the TimescaleDB retention policy on ``metric_values``.

    Catches:
      * ``IntegrityError`` — duplicate policy (treated as success).
      * ``ProgrammingError`` — extension missing or perms denied (logged WARNING).
      * Any other ``Exception`` — logged ERROR, does not raise (REQ-MVR-003).

    REQ-MVR-001 / REQ-MVR-004.
    """
    interval = f"{retention_days} days"
    try:
        with engine.begin() as conn:
            conn.execute(
                _ADD_RETENTION_POLICY_SQL,
                {"interval": interval},
            )
    except IntegrityError as exc:
        logger.info("Retention policy already exists on metric_values: %s", exc)
        return
    except ProgrammingError as exc:
        # "extension timescaledb not found" or hypertable not yet created.
        logger.warning("Cannot apply metric retention policy: %s", exc)
        return
    except Exception as exc:  # noqa: BLE001 — defensive per REQ-MVR-003
        logger.error("Unexpected error applying metric retention policy: %s", exc)
        return

    logger.info("Applied metric_values retention policy: %s", interval)


def _policy_exists(engine: Engine, hypertable_name: str) -> bool:
    """Return True when at least one retention job is registered for the hypertable."""
    sql = (
        "SELECT 1 FROM timescaledb_information.jobs j "
        "JOIN timescaledb_information.job_stats js ON js.job_id = j.job_id "
        "WHERE j.application_name LIKE 'Retention Policy%%' "
        "AND js.hypertable_name = :name LIMIT 1;"
    )
    with engine.connect() as conn:
        row = conn.execute(text(sql), {"name": hypertable_name}).first()
    return row is not None


def run_metric_retention_cleanup() -> None:
    """Scheduler entrypoint: defensively re-apply retention policy if missing.

    Honors ``METRIC_RETENTION_ENABLED`` (kill-switch); reads interval from
    ``get_metric_retention_settings()``. REQ-MVR-001 scenario 2.
    """
    from postgres_db import engine

    settings = get_metric_retention_settings()
    if not settings.enabled:
        logger.debug("Metric retention cleanup skipped (kill-switch off)")
        return

    if _policy_exists(engine, METRIC_HYPERTABLE_NAME):
        logger.debug("Metric retention policy already present")
        return

    apply_metric_retention(engine=engine, retention_days=settings.retention_days)
```

### `backend/repositories/metric_repo.py` (modified)

```python
def create_hypertable(db: Session) -> None:
    """Ensure the metric_values table is converted to a hypertable AND
    the retention policy is applied (issue #457, REQ-MVR-001 scenario 1)."""
    try:
        db.execute(
            text(
                "SELECT create_hypertable('metric_values', 'time', if_not_exists => TRUE);"
            )
        )
        db.commit()
    except Exception as e:
        logger.error("Error creating hypertable: %s", e)
        db.rollback()
        return

    # Boot-time retention apply — REQ-MVR-001 scenario 1.
    # Idempotent; never raises (apply_metric_retention swallows errors).
    try:
        from services.retention_service import (
            METRIC_RETENTION_DEFAULT_DAYS,
            apply_metric_retention,
            get_metric_retention_settings,
        )
        settings = get_metric_retention_settings()
        apply_metric_retention(
            engine=db.get_bind(),
            retention_days=settings.retention_days
            if settings.enabled
            else METRIC_RETENTION_DEFAULT_DAYS,
        )
    except Exception as exc:  # defensive: never break boot
        logger.warning("Boot-time metric retention apply skipped: %s", exc)
```

### `backend/main.py` (scheduler registration)

```python
_METRIC_RETENTION_ENABLED = True
_METRIC_RETENTION_DAYS = 90


def _reload_metric_retention_env_settings() -> None:
    """Mirror of _reload_event_prune_env_settings for metric retention."""
    from services.retention_service import get_metric_retention_settings
    settings = get_metric_retention_settings()
    global _METRIC_RETENTION_ENABLED, _METRIC_RETENTION_DAYS
    _METRIC_RETENTION_ENABLED = settings.enabled
    _METRIC_RETENTION_DAYS = settings.retention_days


def _register_metric_retention_job() -> bool:
    """Register metric retention cleanup on backup_scheduler.

    REQ-MVR-003. Mirrors _register_event_prune_job at backend/main.py:998.
    Returns False when the kill-switch is off (no-op).
    """
    if not _METRIC_RETENTION_ENABLED:
        logger.info("Metric retention auto-scheduler is disabled")
        return False
    from services.retention_service import run_metric_retention_cleanup
    backup_scheduler.add_job(
        run_metric_retention_cleanup,
        trigger=CronTrigger.from_crontab("0 */6 * * *"),  # every 6h
        id="metric_retention_cleanup",
        name="Metric Values Retention Cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Scheduled metric retention cleanup every 6h")
    return True
```

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit (settings) | Default 90 days when env unset; override 30; invalid → 90 + WARNING; kill-switch off; out-of-range (0, 9999) → 90 | `MetricRetentionSettings.from_env()` with `monkeypatch.setenv` + `caplog`; mirrors `tests/test_event_prune_settings.py` |
| Unit (apply) | SQL emitted matches `add_retention_policy('metric_values', INTERVAL '<N> days')`; idempotent (second call does not raise); missing extension → WARNING; duplicate → INFO + no raise | Mock `Engine` with `MagicMock()`, inspect `execute()` call args; inject `IntegrityError` / `ProgrammingError` |
| Unit (scheduler) | `run_metric_retention_cleanup` skips when kill-switch off; no-op when policy exists; reapplies when missing | Mock `engine`, `get_metric_retention_settings`, `_policy_exists` |
| Unit (main) | `_register_metric_retention_job` adds job with required knobs; returns False on kill-switch | Mock `backup_scheduler`; mirrors `tests/test_event_prune_scheduler.py:22-58` |
| Integration | Real TimescaleDB instance: insert row 100d old + row 1d old, apply 30d policy, assert out-of-window row is excluded by `SELECT * FROM metric_values WHERE time > now() - INTERVAL '200 days'` | New `tests/integration/test_metric_retention_integration.py`; gated by env `RUN_TIMESCALE_INTEGRATION=1`; runs against docker-compose stack |

### Specific Test File Layout

- **`backend/tests/test_retention_service.py`** (NEW) — settings, apply_metric_retention, run_metric_retention_cleanup, _policy_exists (with mock engine).
- **`backend/tests/test_metric_retention_scheduler.py`** (NEW) — _register_metric_retention_job kill-switch + registration; mirrors `tests/test_event_prune_scheduler.py`.
- **`backend/tests/test_metric_retention_repo.py`** (NEW) — `create_hypertable` calls `apply_metric_retention` on success; does not raise on apply failure; does NOT call when hypertable creation fails.
- **`backend/tests/conftest.py`** (MODIFY) — add `mock_timescale_engine` fixture returning a `MagicMock` engine whose `begin()` is a context manager yielding a mock connection.

### Acceptance Test Mapping (Issue #457 strict-TDD)

1. **Idempotency** — `test_apply_metric_retention_twice_emits_one_policy`: call `apply_metric_retention(engine=m, 90)` twice; assert `m.begin().__enter__.execute` called twice with the same SQL; assert no exception on second call (mock raises `IntegrityError` once, is caught).
2. **30-day override** — `test_metric_retention_settings_from_env_30_days`: `monkeypatch.setenv("METRIC_RETENTION_DAYS", "30")`; assert `settings.retention_days == 30`; assert `apply_metric_retention` SQL contains `'30 days'`.
3. **Kill-switch off** — `test_register_metric_retention_job_disabled_skips`: patch `_METRIC_RETENTION_ENABLED=False`; assert `backup_scheduler.add_job` not called.
4. **Invalid env** — `test_metric_retention_settings_invalid_days_falls_back`: `monkeypatch.setenv("METRIC_RETENTION_DAYS", "invalid")`; assert `settings.retention_days == 90`; assert WARNING log line via `caplog`.
5. **Out-of-window exclusion** — integration test; not in the unit suite.

## Threat Matrix

N/A — this design does **not** alter routing, shell command execution, subprocess management, VCS/PR automation, executable-file classification, or process-integration boundaries. It adds a single DDL helper guarded by Pydantic settings and a CronTrigger entrypoint, both operating exclusively through the existing `postgres_db.engine` SQLAlchemy surface. No new network, FS, or shell surfaces are introduced.

## Migration / Rollout

No data migration required. The TimescaleDB retention policy is **forward-looking only** (REQ-MVR-006); existing rows are not retroactively deleted. Operators upgrading from a deployment with accumulated metrics will continue to see existing rows in `metric_values` until each chunk's age crosses the configured threshold and the scheduler drops it on roll-over.

**Rollout sequence:**

1. Deploy branch; `MetricRetentionSettings.from_env()` reads `METRIC_RETENTION_DAYS` (default 90).
2. On first boot after upgrade, `create_hypertable` calls `apply_metric_retention`; idempotent — safe even on a deployment where someone manually created a different interval.
3. Scheduler registers `metric_retention_cleanup`; defensive re-apply if missing.
4. Operators verify policy via `SELECT * FROM timescaledb_information.jobs WHERE application_name LIKE 'Retention Policy%';` and confirm `config` matches `90 days 00:00:00`.

**Operator escape hatch (rollback without code revert):**

```sql
-- Inspect current policy
SELECT job_id, application_name, config
FROM timescaledb_information.jobs
WHERE application_name LIKE 'Retention Policy%';

-- Disable without removing the job (preferred — reverts cleanly on next deploy)
SELECT alter_job(<job_id>, scheduled => false);

-- Full removal (cannot restore already-dropped chunks)
SELECT remove_retention_policy('metric_values');
```

## Work-Unit Commit Plan

Following `work-unit-commits` skill (4 commits, each ≤ 200 LOC including tests, each independently buildable + green):

| # | Commit | Files | LOC est. | Verification |
|---|---|---|---|---|
| W1 | `feat(retention): add metric_values retention settings + service skeleton` | `services/retention_service.py` (NEW), `tests/test_retention_service.py` (NEW) | ~180 | RED→GREEN for: idempotency, 30-day override, invalid-env fallback, kill-switch off, policy-exists short-circuit. No scheduler wiring yet. |
| W2 | `feat(retention): wire boot-time apply + scheduler registration` | `repositories/metric_repo.py`, `main.py`, `tests/test_metric_retention_scheduler.py` (NEW), `tests/test_metric_retention_repo.py` (NEW) | ~200 | GREEN for: `_register_metric_retention_job` knobs, kill-switch path, `create_hypertable` calls apply, scheduler callback named correctly. |
| W3 | `docs(retention): update polling-pipeline-tuning + env.example + cap` | `docs/polling-pipeline-tuning.md`, `.env.example`, `tests/test_retention_service.py` (extend with out-of-window mock) | ~60 | RED→GREEN for: out-of-window exclusion (mocked `timescaledb_information.jobs` + smoke insert). Doc build still passes. |
| W4 | `chore(retention): integration smoke + verify report` | `tests/integration/test_metric_retention_integration.py` (NEW), `verify-report.md` | ~150 | Optional integration test gated by env; verify-report captures green CI run. |

Each commit:

- Keeps tests with code (W1 has RED+GREEN in same commit; W2 has GREEN; W3 has cap; W4 has smoke).
- Tells a clear story: W1 sets up the abstraction; W2 wires the abstraction into boot + scheduler; W3 closes the loop with docs + the smoke edge case; W4 finalizes evidence.
- Is ≤ 200 LOC authored (additions + deletions; tests included), per the 400-line review budget minus headroom for the cap.
- Has an explicit rollback boundary: revert W4+W3+W2+W1 in that order; the SQL escape hatch above handles a partially-deployed state.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| TimescaleDB extension not installed on a deployment | `apply_metric_retention` catches `ProgrammingError` ("extension timescaledb not found") and logs WARNING; boot continues without the policy. REQ-MVR-003 honors the kill-switch. |
| `add_retention_policy` raises on duplicate config across deployments | Catches `IntegrityError` (`sqlalchemy.exc.IntegrityError`, already used in `backend/middleware/rate_limit.py:106`); treated as success with INFO log. |
| Existing deployments have rows older than the window | REQ-MVR-006 documents forward-only semantics; no backfill is added; doc update explicitly states "policy does NOT retroactively prune". |
| Scheduler tick races with boot-time apply | Both paths are idempotent — whichever runs second is a no-op (TimescaleDB returns existing `job_id`). |
| Operator sets `METRIC_RETENTION_DAYS=0` or `>3650` | `from_env()` raises `ValueError` caught by try/except → returns 90 with WARNING. Pydantic `Field(ge=1, le=3650)` enforces the same bound on direct construction. |
| `MetricRetentionSettings.from_env()` called twice in test → divergent state | `get_metric_retention_settings()` is a lazy singleton; tests reset `_settings = None` or patch the returned object directly. |

## Open Questions

None — all design choices are mirrored from existing precedents (`EventPruneSettings`, `run_audit_retention_cleanup`, `_register_event_prune_job`, `_parse_system_status_int`). Implementation can proceed.

## Next Step

Hand off to `sdd-tasks-minim` to generate the per-commit task list with strict-TDD ordering: each task gets a RED-test stub before any GREEN implementation lands.
