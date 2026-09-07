"""TimescaleDB retention helpers for the ``metric_values`` hypertable.

Issue #457. Mirrors ``audit_service.run_audit_retention_cleanup`` semantics;
see ``openspec/changes/fix-457-metric-values-retention/proposal.md``.

Public surface
--------------
* :class:`MetricRetentionSettings` — Pydantic BaseModel mirroring
  ``backend.config.EventPruneSettings``. Default window 90 days, bounded
  1..3650; kill-switch honors ``METRIC_RETENTION_ENABLED``.
* :func:`apply_metric_retention` — idempotent SQL wrapper around
  ``add_retention_policy('metric_values', INTERVAL '<N> days')``.
* :func:`get_metric_retention_settings` — lazy singleton accessor.

Defensive contract
------------------
``apply_metric_retention`` MUST NOT raise:

* ``IntegrityError`` — duplicate policy; treated as success with INFO log.
* ``ProgrammingError`` — extension missing or perms denied; WARNING log.
* Any other exception — ERROR log, swallowed to keep boot alive
  (REQ-MVR-003 kill-switch semantics).
"""

from __future__ import annotations

import logging
import os
from typing import Final

from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, ProgrammingError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — defaults and bounds (REQ-MVR-002)
# ---------------------------------------------------------------------------

METRIC_RETENTION_DEFAULT_DAYS: Final[int] = 90
METRIC_RETENTION_MIN_DAYS: Final[int] = 1
METRIC_RETENTION_MAX_DAYS: Final[int] = 3650
METRIC_HYPERTABLE_NAME: Final[str] = "metric_values"

_TRUTHY_ENV: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})
_BOOL_INPUTS: Final[frozenset[str]] = frozenset(_TRUTHY_ENV | _FALSY_ENV)


# ---------------------------------------------------------------------------
# Settings — Pydantic BaseModel mirroring EventPruneSettings
# ---------------------------------------------------------------------------


class MetricRetentionSettings(BaseModel):
    """Runtime settings for the ``metric_values`` retention scheduler.

    Mirrors ``backend.config.EventPruneSettings`` (fix-423 PR #2):
    env-driven, invalid values fall back to defaults, kill-switch honored.

    Attributes
    ----------
    enabled:
        ``METRIC_RETENTION_ENABLED`` kill-switch (default True).
    retention_days:
        ``METRIC_RETENTION_DAYS`` window (default 90, bounded 1..3650).
    """

    enabled: bool = True
    retention_days: int = Field(
        default=METRIC_RETENTION_DEFAULT_DAYS,
        ge=METRIC_RETENTION_MIN_DAYS,
        le=METRIC_RETENTION_MAX_DAYS,
    )

    @classmethod
    def from_env(cls) -> MetricRetentionSettings:
        """Load metric retention settings from environment with safe defaults.

        Invalid ``METRIC_RETENTION_DAYS`` returns ``retention_days=90`` and
        logs a WARNING. Mirrors ``_parse_system_status_int`` in
        ``main.py:63-81``. Invalid bool falls back to True (safe default).
        """

        def _int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None:
                return default
            try:
                value = int(raw.strip())
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Invalid METRIC_RETENTION_DAYS=%r, using default %s: %s",
                    raw,
                    default,
                    exc,
                )
                return default
            if not (METRIC_RETENTION_MIN_DAYS <= value <= METRIC_RETENTION_MAX_DAYS):
                logger.warning(
                    "METRIC_RETENTION_DAYS=%r out of range [%d..%d], using default %s",
                    raw,
                    METRIC_RETENTION_MIN_DAYS,
                    METRIC_RETENTION_MAX_DAYS,
                    default,
                )
                return default
            return value

        enabled_raw = os.getenv("METRIC_RETENTION_ENABLED", "true").strip().lower()
        # Invalid bool falls back to True — safe default, mirrors
        # EventPruneSettings.from_env() in config.py.
        enabled = enabled_raw in _TRUTHY_ENV
        if enabled_raw not in _BOOL_INPUTS:
            logger.warning(
                "Invalid METRIC_RETENTION_ENABLED=%r, using default true",
                enabled_raw,
            )
            enabled = True

        return cls(
            enabled=enabled,
            retention_days=_int("METRIC_RETENTION_DAYS", METRIC_RETENTION_DEFAULT_DAYS),
        )


# Lazy singleton; tests reset ``_settings`` directly when they need to
# override the cached instance.
_settings: MetricRetentionSettings | None = None


def get_metric_retention_settings() -> MetricRetentionSettings:
    """Return cached ``MetricRetentionSettings`` (lazy singleton)."""
    global _settings
    if _settings is None:
        _settings = MetricRetentionSettings.from_env()
    return _settings


# ---------------------------------------------------------------------------
# SQL surface
# ---------------------------------------------------------------------------

_RETENTION_POLICY_SQL: Final[str] = (
    "SELECT add_retention_policy(" "'metric_values', INTERVAL :interval, if_not_exists => TRUE);"
)
"""SQL for the ``metric_values`` retention policy.

TimescaleDB 2.x surfaces ``if_not_exists`` as a no-op when an identical
policy already exists, so the call is naturally idempotent on the happy
path. ``apply_metric_retention`` also catches ``IntegrityError`` defensively
to absorb races where two scheduler ticks collide on the same hypertable.
"""


# ---------------------------------------------------------------------------
# apply_metric_retention — idempotent SQL wrapper
# ---------------------------------------------------------------------------


def apply_metric_retention(
    *,
    engine: Engine,
    retention_days: int,
) -> None:
    """Idempotently apply the TimescaleDB retention policy on ``metric_values``.

    Catches:

    * ``IntegrityError`` — duplicate policy (treated as success).
    * ``ProgrammingError`` — extension missing or perms denied (logged WARNING).
    * Any other ``Exception`` — logged ERROR, never raises (REQ-MVR-003).

    Parameters
    ----------
    engine:
        Sync SQLAlchemy engine (typically ``postgres_db.engine`` or
        ``db.get_bind()``). The function takes the engine rather than a
        session to keep the SQL surface identical to ``_policy_exists``.
    retention_days:
        Forward-looking window in days (must be 1..3650 per
        ``MetricRetentionSettings`` bounds).
    """
    interval = f"{retention_days} days"
    try:
        with engine.begin() as conn:
            conn.execute(_RETENTION_POLICY_SQL, {"interval": interval})
    except IntegrityError as exc:
        # Duplicate policy: TimescaleDB returns the existing job_id, but a
        # rare race across scheduler ticks can surface this as an
        # IntegrityError. Treat as success — the policy is in place.
        logger.info("Retention policy already exists on metric_values: %s", exc)
        return
    except ProgrammingError as exc:
        # Extension missing, hypertable not created, or perms denied.
        logger.warning("Cannot apply metric retention policy: %s", exc)
        return
    except Exception as exc:  # noqa: BLE001 — defensive per REQ-MVR-003
        logger.error("Unexpected error applying metric retention policy: %s", exc)
        return

    logger.info("Applied metric_values retention policy: %s", interval)
