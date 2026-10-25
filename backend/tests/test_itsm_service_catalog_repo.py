"""Repository-level tests for the ServiceCatalog create-only persistence path.

Feature #480 S1: ``POST /api/itsm/service-catalog`` must not turn a duplicate
``service_id`` into an update. The repository therefore exposes a dedicated
``create`` primitive that never merges onto an existing row.
"""

from __future__ import annotations

from typing import Any

import pytest
from models.itsm import ServiceCatalogCreate
from repositories.itsm_service_catalog_repo import (
    ServiceCatalogConflictError,
    ServiceCatalogRepository,
)


class _FakeResult:
    """Minimal stand-in for a Neo4j result (only ``single()`` is used)."""

    def __init__(self, row: Any = None) -> None:
        self._row = row

    def single(self) -> Any:
        return self._row


class _FakeSession:
    """Records every Cypher statement issued by the repository."""

    def __init__(self, *, created: Any = None, error: Exception | None = None):
        self.created = created
        self.error = error
        self.queries: list[str] = []
        self.params: list[dict[str, Any]] = []

    def run(self, query: str, **params: Any) -> _FakeResult:
        self.queries.append(query)
        self.params.append(params)
        if self.error is not None:
            raise self.error
        return _FakeResult(self.created)

    def execute_write(self, work):
        return work(self)


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self):
        session = self._session

        class _Ctx:
            def __enter__(self):
                return session

            def __exit__(self, *exc_info):
                return False

        return _Ctx()


class _FakeConstraintError(Exception):
    """Mimics ``neo4j.exceptions.ConstraintError`` (code + class name)."""

    code = "Neo.ClientError.Schema.ConstraintValidationFailed"


def _payload(**overrides: Any) -> ServiceCatalogCreate:
    data = {
        "service_id": "svc-001",
        "name": "Operations Platform",
        "sla_target_minutes": 60,
        "description": "Operational platform support",
        "service_type": "incident",
        "value_stream": "operate",
    }
    data.update(overrides)
    return ServiceCatalogCreate(**data)


def _created_row() -> dict[str, Any]:
    return {
        "id": "svc-001",
        "service_id": "svc-001",
        "name": "Operations Platform",
        "owner_team": None,
        "category": None,
        "tier": None,
        "service_tier": None,
        "criticality": None,
        "sla_target_minutes": 60,
        "sla_minutes": 60,
        "description": "Operational platform support",
        "service_type": "incident",
        "value_stream": "operate",
        "active": True,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "updated_by": "admin",
    }


def test_create_uses_create_semantics_and_never_merges():
    """The create path must issue CREATE — a MERGE would overwrite on match."""
    session = _FakeSession(created=_created_row())
    repository = ServiceCatalogRepository(driver=_FakeDriver(session))

    record = repository.create(_payload())

    assert record["service_id"] == "svc-001"
    merge_statements = [q for q in session.queries if "MERGE" in q]
    assert merge_statements == [], f"create must not MERGE; got {merge_statements}"
    assert any("CREATE (sc:ServiceCatalog" in q for q in session.queries)
    # The existence guard keeps the CREATE from running on a duplicate id.
    assert any("OPTIONAL MATCH (existing:ServiceCatalog" in q for q in session.queries)


def test_create_rejects_existing_service_id_without_writing():
    """An existing row with the same service_id aborts the create.

    The existence guard filters the statement out, so the driver returns no
    row — the repository turns that into a conflict instead of an update.
    """
    session = _FakeSession(created=None)
    repository = ServiceCatalogRepository(driver=_FakeDriver(session))

    with pytest.raises(ServiceCatalogConflictError):
        repository.create(_payload())

    assert all("MERGE" not in q for q in session.queries)


def test_create_translates_neo4j_constraint_violation_into_conflict():
    """A unique-constraint violation (concurrent insert) surfaces as a conflict."""
    session = _FakeSession(error=_FakeConstraintError("Constraint failed"))
    repository = ServiceCatalogRepository(driver=_FakeDriver(session))

    with pytest.raises(ServiceCatalogConflictError):
        repository.create(_payload())


def test_upsert_keeps_the_historical_merge_semantics():
    """``upsert`` stays MERGE/update-on-match for existing callers."""
    session = _FakeSession(created=_created_row())
    repository = ServiceCatalogRepository(driver=_FakeDriver(session))

    record = repository.upsert(_payload())

    assert record["service_id"] == "svc-001"
    assert any("MERGE (sc:ServiceCatalog" in q for q in session.queries)
    assert any("ON MATCH SET" in q for q in session.queries)
