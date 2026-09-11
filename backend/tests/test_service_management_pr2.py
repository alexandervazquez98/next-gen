"""RED tests for PR2 catalog governance and active value streams."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from models.itsm import ServiceCatalogCreate, ServiceCatalogUpdate
from pydantic import ValidationError
from repositories.itsm_service_catalog_repo import ServiceCatalogRepository, ValueStreamLookup
from services.itsm_bootstrap import _load_service_catalog_migration_statements
from services.itsm_service_catalog_service import create_service_catalog, update_service_catalog


class ActiveValueStreamLookup:
    def __init__(self, active_values):
        self.active_values = set(active_values)

    def is_active(self, value: str) -> bool:
        return value in self.active_values


def catalog_payload(**overrides):
    payload = {
        "service_id": "svc-001",
        "name": "Operations Platform",
        "sla_target_minutes": 60,
        "description": "Operational platform support",
        "service_type": "incident",
        "value_stream": "operate",
    }
    payload.update(overrides)
    return payload


def test_catalog_create_requires_description_and_value_stream():
    with pytest.raises(ValidationError, match="description"):
        ServiceCatalogCreate(**catalog_payload(description=""))
    with pytest.raises(ValidationError, match="value_stream"):
        ServiceCatalogCreate(**catalog_payload(value_stream=""))


def test_catalog_create_rejects_missing_required_sla():
    with pytest.raises(ValidationError, match="sla_target_minutes"):
        ServiceCatalogCreate(
            **{k: v for k, v in catalog_payload().items() if k != "sla_target_minutes"}
        )


def test_catalog_create_rejects_inactive_value_stream_before_persistence():
    repository = MagicMock()
    lookup = ActiveValueStreamLookup({"operate"})

    with pytest.raises(HTTPException, match="active value stream"):
        create_service_catalog(
            catalog_payload(value_stream="retire"),
            repository=repository,
            value_stream_lookup=lookup,
        )

    repository.upsert.assert_not_called()


def test_catalog_create_rejects_duplicate_service_id_and_same_type_name():
    repository = MagicMock()
    repository.get_by_id.return_value = {"service_id": "svc-existing"}
    repository.find_by_type_and_normalized_name.return_value = {
        "service_id": "svc-other",
        "service_type": "incident",
        "name": "Operations Platform",
    }
    lookup = ActiveValueStreamLookup({"operate"})

    with pytest.raises(HTTPException, match="service_id"):
        create_service_catalog(
            catalog_payload(service_id="svc-existing", name="Another"),
            repository=repository,
            value_stream_lookup=lookup,
        )
    repository.upsert.assert_not_called()

    repository.get_by_id.return_value = None
    with pytest.raises(HTTPException, match="service_type.*name|name.*service_type"):
        create_service_catalog(
            catalog_payload(service_id="svc-new"),
            repository=repository,
            value_stream_lookup=lookup,
        )
    repository.upsert.assert_not_called()


def test_catalog_update_validates_new_value_stream_and_preserves_immutable_type():
    repository = MagicMock()
    repository.get_by_id.return_value = {
        "service_id": "svc-001",
        "service_type": "incident",
        "name": "Operations Platform",
        "value_stream": "operate",
    }
    lookup = ActiveValueStreamLookup({"operate"})

    with pytest.raises(HTTPException, match="active value stream"):
        update_service_catalog(
            "svc-001",
            ServiceCatalogUpdate(value_stream="retire"),
            repository=repository,
            value_stream_lookup=lookup,
        )
    repository.update.assert_not_called()


def test_repository_persists_description_value_stream_and_uses_governed_name_query():
    session = MagicMock()
    session.run.return_value.single.return_value = {
        "id": "svc-001",
        "service_id": "svc-001",
        "name": "Operations Platform",
        "description": "Operational platform support",
        "sla_target_minutes": 60,
        "service_type": "incident",
        "value_stream": "operate",
        "active": True,
    }
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session

    repository = ServiceCatalogRepository(driver=driver)
    repository.upsert(ServiceCatalogCreate(**catalog_payload()))

    query = session.run.call_args.args[0]
    assert "description" in query
    assert "value_stream" in query
    assert "service_type" in query


def test_value_stream_update_model_accepts_governed_mutable_fields():
    update = ServiceCatalogUpdate(description="New description", value_stream="operate")
    assert update.description == "New description"
    assert update.value_stream == "operate"


def test_catalog_update_rejects_blank_description_without_repository_write():
    repository = MagicMock()
    repository.get_by_id.return_value = {
        "service_id": "svc-001",
        "service_type": "incident",
        "description": "Existing support",
        "sla_target_minutes": 60,
    }

    with pytest.raises(HTTPException) as exc:
        update_service_catalog(
            "svc-001",
            {"description": "   "},
            repository=repository,
            value_stream_lookup=ActiveValueStreamLookup({"operate"}),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail.startswith("1 validation error for ServiceCatalogUpdate")
    repository.update.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"sla_target_minutes": None},
        {"sla_target_minutes": -1},
    ],
)
def test_catalog_update_rejects_invalid_sla_without_repository_write(payload):
    repository = MagicMock()
    repository.get_by_id.return_value = {
        "service_id": "svc-001",
        "service_type": "incident",
        "description": "Existing support",
        "sla_target_minutes": 60,
    }

    with pytest.raises(HTTPException) as exc:
        update_service_catalog(
            "svc-001",
            payload,
            repository=repository,
            value_stream_lookup=ActiveValueStreamLookup({"operate"}),
        )

    assert exc.value.status_code == 400
    assert "sla_target_minutes" in exc.value.detail
    repository.update.assert_not_called()


def test_clean_bootstrap_seeds_active_value_streams_for_real_lookup_and_create():
    statements = _load_service_catalog_migration_statements()
    seed_statements = [statement for statement in statements if "value_stream" in statement]
    assert any(
        "MetricDictionary" in statement and "operate" in statement for statement in seed_statements
    )
    assert any(
        "MetricDictionary" in statement and "deliver" in statement for statement in seed_statements
    )

    session = MagicMock()
    session.run.return_value = [{"value": "operate"}]
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    lookup = ValueStreamLookup(driver=driver)

    assert lookup.is_active("operate") is True
    assert lookup.is_active("retire") is False


def test_repository_update_returns_persisted_description_and_value_stream():
    session = MagicMock()
    session.run.return_value.single.return_value = {
        "id": "svc-001",
        "service_id": "svc-001",
        "name": "Operations Platform",
        "description": "Updated support",
        "value_stream": "operate",
        "service_type": "incident",
        "active": True,
    }
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session

    result = ServiceCatalogRepository(driver=driver).update(
        "svc-001",
        ServiceCatalogUpdate(description="Updated support", value_stream="operate"),
    )

    assert result["description"] == "Updated support"
    assert result["value_stream"] == "operate"
    query = session.run.call_args.args[0]
    assert "sc.description AS description" in query
    assert "sc.value_stream AS value_stream" in query


class _FakeNeo4jDateTime:
    """Stand-in for neo4j.time.DateTime exposed by the Neo4j Python driver."""

    def __init__(self, iso: str) -> None:
        self._iso = iso

    def iso_format(self) -> str:
        return self._iso


class _FakeNeo4jDateTimeNoIsoFormat:
    """Stand-in for objects that only expose the stdlib `isoformat` method."""

    def __init__(self, iso: str) -> None:
        self._iso = iso

    def isoformat(self) -> str:
        return self._iso


class _FakeServiceCatalogRow:
    """Mimics a Neo4j Record that only exposes `.get()` (driver behavior)."""

    def __init__(self, values: dict) -> None:
        self._values = values

    def get(self, key: str):
        return self._values[key]


def _full_catalog_row_values(created_at, updated_at):
    return {
        "id": "svc-001",
        "service_id": "svc-001",
        "name": "Demo",
        "owner_team": "team-a",
        "category": "Business",
        "tier": "Gold",
        "service_tier": "Gold",
        "criticality": "High",
        "sla_target_minutes": 60,
        "sla_minutes": 60,
        "description": "Demo service",
        "service_type": "incident",
        "value_stream": "operate",
        "active": True,
        "created_at": created_at,
        "updated_at": updated_at,
        "updated_by": "test-user",
    }


def test_repository_record_coerces_neo4j_datetime_to_iso_string():
    """Regression for #473: _record() must coerce neo4j.time.DateTime to ISO strings."""

    record = ServiceCatalogRepository._record(
        _FakeServiceCatalogRow(
            _full_catalog_row_values(
                _FakeNeo4jDateTime("2026-01-15T10:30:00Z"),
                _FakeNeo4jDateTime("2026-01-15T10:35:00Z"),
            )
        )
    )

    assert record["created_at"] == "2026-01-15T10:30:00Z"
    assert record["updated_at"] == "2026-01-15T10:35:00Z"


def test_repository_record_coerces_stdlib_datetime_to_iso_string():
    """_to_iso() falls back to .isoformat() for stdlib datetime objects."""

    from datetime import datetime

    record = ServiceCatalogRepository._record(
        _FakeServiceCatalogRow(
            _full_catalog_row_values(
                datetime(2026, 1, 15, 10, 30, 0),
                datetime(2026, 1, 15, 10, 35, 0),
            )
        )
    )

    assert record["created_at"] == "2026-01-15T10:30:00"
    assert record["updated_at"] == "2026-01-15T10:35:00"


def test_repository_record_passes_through_none_and_plain_strings():
    """_to_iso() leaves None, strings, and ints untouched (no-op safety net)."""

    record = ServiceCatalogRepository._record(
        _FakeServiceCatalogRow(
            _full_catalog_row_values(None, "2026-01-15T10:35:00Z")
        )
    )

    assert record["created_at"] is None
    assert record["updated_at"] == "2026-01-15T10:35:00Z"
