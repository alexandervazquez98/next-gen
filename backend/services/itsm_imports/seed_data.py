"""Idempotent seeders for managed MetricDictionary keys.

The Service Catalog form (feature #480) consumes tier and criticality
options from the ``MetricDictionary`` node model — same surface as
``value_stream``. The seeders here make a clean-slate deployment usable
for the ITIL-aligned create/edit form without depending on the cypher
migration timing.

Design notes:
- Each seeder is idempotent (Cypher MERGE on (dictionary_key, value)).
- The seed data is exposed as Python constants so tests and runbooks can
  rely on a single source of truth.
- The driver defaults to ``database.get_db()`` but accepts an injected
  driver for unit tests.
"""

from __future__ import annotations

from typing import Any

from database import get_db

TIER_VALUES: tuple[str, ...] = ("bronze", "silver", "gold", "platinum")
CRITICALITY_VALUES: tuple[str, ...] = ("low", "medium", "high", "critical")

_SEED_TIER_QUERY = """
UNWIND $values AS row
MERGE (v:MetricDictionary {dictionary_key: 'tier', value: row.value})
ON CREATE SET v.label = row.label, v.active = true
ON MATCH SET v.label = coalesce(v.label, row.label)
"""

_SEED_CRITICALITY_QUERY = """
UNWIND $values AS row
MERGE (v:MetricDictionary {dictionary_key: 'criticality', value: row.value})
ON CREATE SET v.label = row.label, v.active = true
ON MATCH SET v.label = coalesce(v.label, row.label)
"""


def _payload(values: tuple[str, ...]) -> list[dict[str, str]]:
    return [{"value": v, "label": v.capitalize()} for v in values]


def seed_tier_criticality_dictionaries(driver: Any | None = None) -> dict[str, int]:
    """Insert (or refresh labels for) tier + criticality MetricDictionary rows.

    Returns the count of rows upserted per key for test instrumentation.
    """

    db = driver if driver is not None else get_db()
    with db.session() as session:
        session.run(_SEED_TIER_QUERY, values=_payload(TIER_VALUES))
        session.run(_SEED_CRITICALITY_QUERY, values=_payload(CRITICALITY_VALUES))
    return {
        "tier_count": len(TIER_VALUES),
        "criticality_count": len(CRITICALITY_VALUES),
    }


__all__ = [
    "TIER_VALUES",
    "CRITICALITY_VALUES",
    "seed_tier_criticality_dictionaries",
]
