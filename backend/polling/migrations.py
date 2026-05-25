"""Explicit PostgreSQL migrations for the polling pipeline.

PR 2 intentionally adds a small migration runner instead of putting polling DDL
inside `backend/main.py` startup or introducing a full Alembic project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import text


@dataclass(frozen=True)
class PostgresMigration:
    version: str
    description: str
    sql: str


SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

POLLING_QUEUE_MIGRATION = PostgresMigration(
    version="20260525_001_polling_queue",
    description="create scalable polling queue tables",
    sql="""
CREATE TABLE IF NOT EXISTS poll_cycles (
    cycle_id UUID PRIMARY KEY,
    scheduled_for TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    config_version TEXT,
    target_task_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_poll_cycles_scheduled_for ON poll_cycles (scheduled_for DESC);
CREATE INDEX IF NOT EXISTS idx_poll_cycles_status_scheduled ON poll_cycles (status, scheduled_for);

CREATE TABLE IF NOT EXISTS poll_task_queue (
    task_id UUID PRIMARY KEY,
    cycle_id UUID NOT NULL REFERENCES poll_cycles(cycle_id) ON DELETE CASCADE,
    ci_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    protocol TEXT NOT NULL,
    priority SMALLINT NOT NULL DEFAULT 50,
    due_at TIMESTAMPTZ NOT NULL,
    next_eligible_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    partition_key INTEGER NOT NULL DEFAULT 0,
    site_id TEXT,
    subnet TEXT,
    ip_address TEXT,
    credential_ref TEXT,
    endpoint TEXT,
    source TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_version TEXT,
    status TEXT NOT NULL DEFAULT 'available',
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    lease_attempts INTEGER NOT NULL DEFAULT 0,
    execute_attempts INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    last_error_message TEXT,
    dead_letter_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_poll_task_claim ON poll_task_queue
    (priority, next_eligible_at, partition_key, task_id)
    WHERE status IN ('available', 'retry_wait', 'deferred')
       OR (status = 'leased' AND lease_expires_at IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_poll_task_lease_expired ON poll_task_queue (lease_expires_at)
    WHERE status = 'leased';
CREATE INDEX IF NOT EXISTS idx_poll_task_cycle_status ON poll_task_queue
    (cycle_id, status, protocol, priority);
CREATE INDEX IF NOT EXISTS idx_poll_task_target_safety ON poll_task_queue
    (protocol, ci_id, ip_address, site_id, subnet, credential_ref, endpoint, source, status);

CREATE TABLE IF NOT EXISTS poll_result_queue (
    result_id UUID PRIMARY KEY,
    task_id UUID NOT NULL,
    cycle_id UUID NOT NULL REFERENCES poll_cycles(cycle_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    protocol TEXT NOT NULL,
    ci_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'ready',
    priority SMALLINT NOT NULL DEFAULT 50,
    partition_key INTEGER NOT NULL DEFAULT 0,
    envelope JSONB NOT NULL,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    write_attempts INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    last_error_message TEXT,
    dead_letter_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_poll_result_idempotency_key
    ON poll_result_queue (idempotency_key);
CREATE INDEX IF NOT EXISTS idx_poll_result_claim ON poll_result_queue
    (priority, received_at, partition_key, result_id)
    WHERE status IN ('ready', 'retry_wait')
       OR (status = 'leased' AND lease_expires_at IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_poll_result_cycle_status ON poll_result_queue
    (cycle_id, status, protocol);
CREATE INDEX IF NOT EXISTS idx_poll_result_lease_expired ON poll_result_queue (lease_expires_at)
    WHERE status = 'leased';
CREATE INDEX IF NOT EXISTS idx_poll_result_ci_metric_observed ON poll_result_queue
    (ci_id, metric_id, observed_at DESC);
""",
)

POLLING_MIGRATIONS = (POLLING_QUEUE_MIGRATION,)


def _statements(sql: str) -> Iterable[str]:
    for statement in sql.split(";"):
        stripped = statement.strip()
        if stripped:
            yield stripped


def _applied_versions(conn) -> set[str]:
    result = conn.execute(text("SELECT version FROM schema_migrations"))
    return {row.version for row in result}


def run_pending_migrations(engine, migrations: Iterable[PostgresMigration] = POLLING_MIGRATIONS) -> list[str]:
    """Apply unapplied PostgreSQL migrations and return applied versions."""
    applied_now: list[str] = []
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_MIGRATIONS_SQL))
        applied = _applied_versions(conn)
        for migration in migrations:
            if migration.version in applied:
                continue
            for statement in _statements(migration.sql):
                conn.execute(text(statement))
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, description) "
                    "VALUES (:version, :description) "
                    "ON CONFLICT (version) DO NOTHING"
                ),
                {"version": migration.version, "description": migration.description},
            )
            applied_now.append(migration.version)
    return applied_now
