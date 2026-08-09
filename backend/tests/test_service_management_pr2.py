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
