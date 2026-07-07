"""Shared MQTT runtime status repository (slice 1).

Persists subscriber status + bridge counters in PostgreSQL so API and runtime can
share heartbeat visibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from postgres_db import SessionLocal


_DEFAULT_SERVICE_NAME = "mqtt-subscriber"

_CREATE_STATUS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mqtt_runtime_status (
    service_name VARCHAR(128) PRIMARY KEY,
    configured BOOLEAN NOT NULL DEFAULT false,
    running BOOLEAN NOT NULL DEFAULT false,
    connected BOOLEAN NOT NULL DEFAULT false,
    subscribed_patterns TEXT NOT NULL DEFAULT '[]',
    last_message_at TIMESTAMPTZ NULL,
    last_error TEXT NULL,
    reason_code VARCHAR(64) NULL,
    mapped_writes_total INTEGER NOT NULL DEFAULT 0,
    unmapped_skips_total INTEGER NOT NULL DEFAULT 0,
    failed_writes_total INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_SELECT_STATUS_SQL = """
SELECT service_name,
       configured,
       running,
       connected,
       subscribed_patterns,
       last_message_at,
       last_error,
       reason_code,
       mapped_writes_total,
       unmapped_skips_total,
       failed_writes_total
FROM mqtt_runtime_status
WHERE service_name = :service_name
"""

_INSERT_STATUS_SQL = """
INSERT INTO mqtt_runtime_status (
    service_name,
    configured,
    running,
    connected,
    subscribed_patterns,
    last_message_at,
    last_error,
    reason_code,
    mapped_writes_total,
    unmapped_skips_total,
    failed_writes_total,
    updated_at
) VALUES (
    :service_name,
    :configured,
    :running,
    :connected,
    :subscribed_patterns,
    :last_message_at,
    :last_error,
    :reason_code,
    :mapped_writes_total,
    :unmapped_skips_total,
    :failed_writes_total,
    :updated_at
)
ON CONFLICT (service_name) DO NOTHING
"""

_UPDATE_STATUS_SQL = """
UPDATE mqtt_runtime_status
SET configured = COALESCE(:configured, configured),
    running = COALESCE(:running, running),
    connected = COALESCE(:connected, connected),
    subscribed_patterns = COALESCE(:subscribed_patterns, subscribed_patterns),
    last_message_at = COALESCE(:last_message_at, last_message_at),
    last_error = CASE
        WHEN :clear_last_error THEN NULL
        ELSE COALESCE(:last_error, last_error)
    END,
    reason_code = CASE
        WHEN :clear_reason_code THEN NULL
        ELSE COALESCE(:reason_code, reason_code)
    END,
    mapped_writes_total = mapped_writes_total + COALESCE(:mapped_writes_delta, 0),
    unmapped_skips_total = unmapped_skips_total + COALESCE(:unmapped_skips_total_delta, 0),
    failed_writes_total = failed_writes_total + COALESCE(:failed_writes_total_delta, 0),
    updated_at = :updated_at
WHERE service_name = :service_name
"""


class MqttRuntimeStatusRepo:
    """PostgreSQL-backed runtime status row for a named MQTT process."""

    def __init__(
        self,
        service_name: str = _DEFAULT_SERVICE_NAME,
        session_factory: Callable[[], Session] | None = None,
    ):
        self.service_name = service_name
        self._session_factory = session_factory or SessionLocal

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _to_iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()

    @staticmethod
    def _normalize_timestamp(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        return value

    @staticmethod
    def _to_patterns(value: list[str] | tuple[str, ...] | None) -> str:
        if value is None:
            return "[]"
        return json.dumps(list(value))

    @staticmethod
    def _from_patterns(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return list(value)
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return [value] if value else []
        return []

    @staticmethod
    def _extract_row(result: Any) -> Any:
        if result is None:
            return None
        if hasattr(result, "mappings"):
            try:
                mapped = result.mappings()
                # SQLAlchemy 2.x-style mapping result.
                return mapped.first()
            except Exception:
                pass
        for accessor in ("fetchone", "first", "one_or_none", "scalar_one_or_none"):
            fn = getattr(result, accessor, None)
            if callable(fn):
                try:
                    return fn()
                except Exception:
                    pass
        if isinstance(result, (list, tuple)) and result:
            return result[0]
        return None

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        if row is None:
            return {
                "service_name": _DEFAULT_SERVICE_NAME,
                "configured": False,
                "running": False,
                "connected": False,
                "subscribed_patterns": [],
                "last_message_at": None,
                "last_error": None,
                "reason_code": None,
                "mapped_writes_total": 0,
                "unmapped_skips_total": 0,
                "failed_writes_total": 0,
            }

        return {
            "service_name": row["service_name"],
            "configured": bool(row["configured"]),
            "running": bool(row["running"]),
            "connected": bool(row["connected"]),
            "subscribed_patterns": MqttRuntimeStatusRepo._from_patterns(row["subscribed_patterns"]),
            "last_message_at": MqttRuntimeStatusRepo._normalize_timestamp(row["last_message_at"]),
            "last_error": row.get("last_error"),
            "reason_code": row.get("reason_code"),
            "mapped_writes_total": int(row["mapped_writes_total"] or 0),
            "unmapped_skips_total": int(row["unmapped_skips_total"] or 0),
            "failed_writes_total": int(row["failed_writes_total"] or 0),
        }

    @staticmethod
    def _is_stale(last_message_at: Any, stale_after_seconds: int, now: datetime | None = None) -> bool:
        if last_message_at is None:
            return True
        if now is None:
            now = MqttRuntimeStatusRepo._now()
        last_message_at = MqttRuntimeStatusRepo._normalize_timestamp(last_message_at)
        if last_message_at is None:
            return True
        if last_message_at.tzinfo is None:
            last_message_at = last_message_at.replace(tzinfo=UTC)
        return (now - last_message_at).total_seconds() > stale_after_seconds

    def _get_db(self) -> Session:
        return self._session_factory()

    def ensure_schema(self, db: Session) -> None:
        db.execute(text(_CREATE_STATUS_TABLE_SQL.strip()))

    def _read_row(self, db: Session) -> dict[str, Any] | None:
        row = self._extract_row(db.execute(text(_SELECT_STATUS_SQL.strip()), {"service_name": self.service_name}))
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_status(self, stale_after_seconds: int = 90, now: datetime | None = None) -> dict[str, Any]:
        now = now or self._now()
        db = self._get_db()
        try:
            self.ensure_schema(db)
            row = self._read_row(db)
            if row is None:
                self._initialize_default_row(db)
                row = self._read_row(db)

            if row is None:
                raise RuntimeError("Could not initialize runtime status row")

            is_stale = self._is_stale(row["last_message_at"], stale_after_seconds, now=now)
            status = dict(row)
            status["is_stale"] = is_stale

            if is_stale:
                status["running"] = False
                status["connected"] = False
                status["reason_code"] = status["reason_code"] or "STALE_HEARTBEAT"

            return status
        finally:
            db.close()

    def _initialize_default_row(self, db: Session) -> None:
        base = self._row_to_dict(None)
        base["service_name"] = self.service_name
        db.execute(
            text(_INSERT_STATUS_SQL.strip()),
            {
                "service_name": base["service_name"],
                "configured": base["configured"],
                "running": base["running"],
                "connected": base["connected"],
                "subscribed_patterns": self._to_patterns(base["subscribed_patterns"]),
                "last_message_at": base["last_message_at"],
                "last_error": base["last_error"],
                "reason_code": base["reason_code"],
                "mapped_writes_total": base["mapped_writes_total"],
                "unmapped_skips_total": base["unmapped_skips_total"],
                "failed_writes_total": base["failed_writes_total"],
                "updated_at": self._now(),
            },
        )
        db.commit()

    def update_status(
        self,
        *,
        configured: bool | None = None,
        running: bool | None = None,
        connected: bool | None = None,
        subscribed_patterns: list[str] | None = None,
        last_message_at: datetime | None = None,
        last_error: str | None = None,
        reason_code: str | None = None,
        clear_last_error: bool = False,
        clear_reason_code: bool = False,
        mapped_writes_delta: int = 0,
        unmapped_skips_total_delta: int = 0,
        failed_writes_total_delta: int = 0,
    ) -> dict[str, Any]:
        db = self._get_db()
        try:
            self.ensure_schema(db)
            now = self._now()

            existing = self._read_row(db)
            if existing is None:
                base = self._row_to_dict(None)
                base.update(
                    {
                        "service_name": self.service_name,
                        "configured": configured if configured is not None else base["configured"],
                        "running": running if running is not None else base["running"],
                        "connected": connected if connected is not None else base["connected"],
                        "subscribed_patterns": subscribed_patterns or base["subscribed_patterns"],
                        "last_message_at": self._to_iso(last_message_at) or base["last_message_at"],
                        "last_error": None if clear_last_error else (last_error if last_error is not None else base["last_error"]),
                        "reason_code": None if clear_reason_code else (reason_code if reason_code is not None else base["reason_code"]),
                        "mapped_writes_total": int(base["mapped_writes_total"]) + int(mapped_writes_delta or 0),
                        "unmapped_skips_total": int(base["unmapped_skips_total"]) + int(unmapped_skips_total_delta or 0),
                        "failed_writes_total": int(base["failed_writes_total"]) + int(failed_writes_total_delta or 0),
                    }
                )
                db.execute(
                    text(_INSERT_STATUS_SQL.strip()),
                    {
                        "service_name": base["service_name"],
                        "configured": base["configured"],
                        "running": base["running"],
                        "connected": base["connected"],
                        "subscribed_patterns": self._to_patterns(base["subscribed_patterns"]),
                        "last_message_at": base["last_message_at"],
                        "last_error": base["last_error"],
                        "reason_code": base["reason_code"],
                        "mapped_writes_total": base["mapped_writes_total"],
                        "unmapped_skips_total": base["unmapped_skips_total"],
                        "failed_writes_total": base["failed_writes_total"],
                        "updated_at": now,
                    },
                )
            else:
                db.execute(
                    text(_UPDATE_STATUS_SQL.strip()),
                    {
                        "service_name": self.service_name,
                        "configured": configured,
                        "running": running,
                        "connected": connected,
                        "subscribed_patterns": self._to_patterns(subscribed_patterns)
                        if subscribed_patterns is not None
                        else None,
                        "last_message_at": self._to_iso(last_message_at),
                        "last_error": last_error,
                        "clear_last_error": clear_last_error,
                        "reason_code": reason_code,
                        "clear_reason_code": clear_reason_code,
                        "mapped_writes_delta": int(mapped_writes_delta or 0),
                        "unmapped_skips_total_delta": int(unmapped_skips_total_delta or 0),
                        "failed_writes_total_delta": int(failed_writes_total_delta or 0),
                        "updated_at": now,
                    },
                )

            db.commit()
            # Return freshly initialized object with an intentionally long freshness window;
            # staleness is decided by caller on read.
            return self.get_status(stale_after_seconds=2 ** 31 - 1)
        finally:
            db.close()

    def increment_counter(self, counter: str, delta: int = 1) -> dict[str, Any]:
        valid = {
            "mapped_writes_total": "mapped_writes_delta",
            "unmapped_skips_total": "unmapped_skips_total_delta",
            "failed_writes_total": "failed_writes_total_delta",
        }
        if counter not in valid:
            raise ValueError(f"Unknown counter: {counter}")
        if delta < 0:
            raise ValueError("Counter delta must be non-negative")

        params = {
            "configured": None,
            "running": None,
            "connected": None,
            "subscribed_patterns": None,
            "last_message_at": None,
            "last_error": None,
            "reason_code": None,
            "mapped_writes_delta": 0,
            "unmapped_skips_total_delta": 0,
            "failed_writes_total_delta": 0,
        }
        params[valid[counter]] = delta
        return self.update_status(
            configured=params["configured"],
            running=params["running"],
            connected=params["connected"],
            subscribed_patterns=params["subscribed_patterns"],
            last_message_at=params["last_message_at"],
            last_error=params["last_error"],
            reason_code=params["reason_code"],
            mapped_writes_delta=params["mapped_writes_delta"],
            unmapped_skips_total_delta=params["unmapped_skips_total_delta"],
            failed_writes_total_delta=params["failed_writes_total_delta"],
        )


_status_repo: MqttRuntimeStatusRepo | None = None


def get_mqtt_runtime_status_repo(
    service_name: str = _DEFAULT_SERVICE_NAME,
    session_factory: Callable[[], Session] | None = None,
) -> MqttRuntimeStatusRepo:
    global _status_repo
    if _status_repo is None:
        _status_repo = MqttRuntimeStatusRepo(service_name=service_name, session_factory=session_factory)
    return _status_repo
