"""Value-stream lookup seam for Service Management imports.

Backed by the existing ``MetricDictionary`` node model (PR2 seeded ``operate``
and ``deliver`` under ``dictionary_key='value_stream'``). Keeping the lookup
in its own module avoids leaking the dictionary surface into the import path.
"""

from __future__ import annotations

from typing import Any, Iterable

from database import get_db


class MetricDictionaryValueStreamLookup:
    """Read active value streams from ``MetricDictionary`` nodes."""

    DICTIONARY_KEY = "value_stream"

    def __init__(self, driver: Any | None = None) -> None:
        self._driver = driver if driver is not None else get_db()

    def list_active(self) -> list[dict]:
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (v:MetricDictionary {dictionary_key: $key})
                WHERE coalesce(v.active, true) = true
                RETURN v.value AS value, v.label AS label
                ORDER BY v.value
                """,
                key=self.DICTIONARY_KEY,
            )
            return [{"value": r["value"], "label": r.get("label") or r["value"]} for r in result]

    def is_active(self, value: str) -> bool:
        if not value:
            return False
        with self._driver.session() as session:
            record = session.run(
                """
                MATCH (v:MetricDictionary {dictionary_key: $key, value: $value})
                RETURN coalesce(v.active, true) AS active
                """,
                key=self.DICTIONARY_KEY,
                value=value,
            ).single()
        if record is None:
            return False
        return bool(record.get("active"))


__all__ = ["MetricDictionaryValueStreamLookup"]
