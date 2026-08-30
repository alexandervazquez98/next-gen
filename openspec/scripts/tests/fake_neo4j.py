"""Duck-typed fake Neo4j session/result for unit tests.

The classes below mirror the structural subset of ``neo4j.Session`` that
``cmdb_backfill_orphans`` actually uses:

- ``session.run(query, **params)`` → ``FakeResult``
- ``result`` is iterable of ``FakeRecord`` (mapping-like with ``[]`` and ``get``)
- ``session.queries`` is a list of every ``(query, params)`` invocation

They are intentionally minimal — no live driver, no Bolt socket.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeRecord:
    """Duck-typed stand-in for ``neo4j.Record`` (mapping-like access)."""

    data: dict

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass
class FakeResult:
    """Iterable ``neo4j.Result`` stand-in exposing the ``FakeRecord`` list."""

    records: list[FakeRecord]

    def __iter__(self) -> Iterable[FakeRecord]:
        return iter(self.records)


@dataclass
class FakeSession:
    """In-memory session that records every ``run`` call.

    Pass either a list of dicts (returned as records) or an exception
    instance to raise. The optional ``schema_drift`` flag (or a matching
    ``label X not found`` message) is used by ``discover_orphans`` to
    assert fail-fast behaviour on schema drift.
    """

    responses: Any
    queries: list[tuple[str, dict]] = field(default_factory=list)
    schema_drift: str | None = None

    def run(self, query: str, **params):
        self.queries.append((query, params))
        if isinstance(self.responses, Exception):
            raise self.responses
        return FakeResult([FakeRecord(dict(row)) for row in self.responses])
