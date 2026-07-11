"""Service-layer tests for ITSM service catalog behavior.

Focus on create/list/update/deactivate flow and validation failures.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import services.itsm_service_catalog_service as service_catalog_service
from fastapi import HTTPException
from models.itsm import ServiceCatalogCreate, ServiceCatalogUpdate


class _CatalogRepositoryStub:
    def __init__(self):
        self.list = MagicMock()
        self.get_by_id = MagicMock()
        self.upsert = MagicMock()
        self.update = MagicMock()
        self.deactivate = MagicMock()


def _sample_catalog_record() -> dict:
    return {
        "service_id": "svc-001",
        "id": "svc-001",
        "name": "Operations Platform",
        "category": "PLATFORM",
        "owner_team": "SRE",
        "tier": "Gold",
        "service_tier": "Gold",
        "criticality": "High",
        "sla_target_minutes": 60,
        "sla_minutes": 60,
        "active": True,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "updated_by": "admin",
    }


class TestServiceCatalogService:
    """Verify core Service Catalog service behaviors."""

    def test_list_service_catalogs_returns_records(self):
        repository = _CatalogRepositoryStub()
        repository.list.return_value = [_sample_catalog_record()]

        result = service_catalog_service.list_service_catalogs(repository=repository)

        assert result == [_sample_catalog_record()]
        repository.list.assert_called_once_with(limit=100)

    def test_get_service_catalog_returns_404_when_missing(self):
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = None

        with pytest.raises(HTTPException) as exc:
            service_catalog_service.get_service_catalog("missing", repository=repository)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Service catalog not found: missing"
        repository.get_by_id.assert_called_once_with("missing")

    def test_create_catalog_defaults_to_active_and_normalizes_aliases(self):
        repository = _CatalogRepositoryStub()
        repository.upsert.side_effect = lambda payload: payload.model_dump()

        created = service_catalog_service.create_service_catalog(
            {
                "id": "svc-legacy",
                "name": "Platform Core",
                "service_tier": "Silver",
                "sla_minutes": 45,
                "service_type": "incident",
            },
            actor="admin",
            repository=repository,
        )

        assert created["service_id"] == "svc-legacy"
        assert created["id"] == "svc-legacy"
        assert created["tier"] == "Silver"
        assert created["sla_target_minutes"] == 45
        assert created["sla_minutes"] == 45
        assert created["active"] is True
        repository.upsert.assert_called_once()
        persisted_payload = repository.upsert.call_args.args[0]
        assert isinstance(persisted_payload, ServiceCatalogCreate)
        assert persisted_payload.service_id == "svc-legacy"
        assert persisted_payload.id == "svc-legacy"
        assert persisted_payload.updated_by == "admin"

    def test_create_catalog_rejects_empty_name(self):
        repository = _CatalogRepositoryStub()

        with pytest.raises(HTTPException) as exc:
            service_catalog_service.create_service_catalog(
                {
                    "service_id": "svc-empty",
                    "name": "   ",
                    "sla_target_minutes": 30,
                },
                repository=repository,
            )

        assert exc.value.status_code == 400
        assert "name cannot be empty" in exc.value.detail.lower()
        repository.upsert.assert_not_called()

    def test_update_catalog_rejects_negative_sla(self):
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = _sample_catalog_record()

        with pytest.raises(HTTPException) as exc:
            service_catalog_service.update_service_catalog(
                "svc-001",
                {
                    "service_id": "svc-001",
                    "sla_target_minutes": -1,
                },
                actor="admin",
                repository=repository,
            )

        assert exc.value.status_code == 400
        assert "sla_target_minutes" in exc.value.detail
        repository.update.assert_not_called()

    def test_update_allows_clearing_optional_fields(self):
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = _sample_catalog_record()
        repository.update.return_value = {
            **_sample_catalog_record(),
            "owner_team": None,
            "category": None,
        }

        service_catalog_service.update_service_catalog(
            "svc-001",
            {"owner_team": None, "category": None},
            repository=repository,
        )

        update_payload = repository.update.call_args.args[1]
        assert "owner_team" in update_payload.model_fields_set
        assert "category" in update_payload.model_fields_set

    def test_partial_update_with_no_fields_returns_current_record(self):
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = _sample_catalog_record()

        result = service_catalog_service.update_service_catalog(
            "svc-001",
            ServiceCatalogUpdate(),
            repository=repository,
        )

        assert result == _sample_catalog_record()
        repository.get_by_id.assert_called_once_with("svc-001")
        repository.update.assert_not_called()

    def test_deactivate_catalog_marks_catalog_inactive(self):
        repository = _CatalogRepositoryStub()
        repository.deactivate.return_value = {**_sample_catalog_record(), "active": False}

        result = service_catalog_service.deactivate_service_catalog(
            "svc-001",
            actor="admin",
            repository=repository,
        )

        assert result["service_id"] == "svc-001"
        assert result["active"] is False
        repository.deactivate.assert_called_once_with("svc-001", updated_by="admin")

    def test_update_catalog_service_id_mismatch_is_rejected(self):
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = _sample_catalog_record()

        with pytest.raises(HTTPException) as exc:
            service_catalog_service.update_service_catalog(
                "svc-001",
                {"service_id": "svc-other", "name": "Different"},
                repository=repository,
            )

        assert exc.value.status_code == 400
        assert "service_id" in exc.value.detail.lower()
        repository.update.assert_not_called()

    def test_update_catalog_accepts_unchanged_service_type_with_mutable_fields(self):
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = {**_sample_catalog_record(), "service_type": "incident"}
        repository.update.return_value = {**_sample_catalog_record(), "name": "Updated"}

        result = service_catalog_service.update_service_catalog(
            "svc-001",
            {"service_type": "incident", "name": "Updated"},
            repository=repository,
        )

        assert result["name"] == "Updated"
        update_payload = repository.update.call_args.args[1]
        assert update_payload.service_type is None
        assert update_payload.name == "Updated"

    def test_update_catalog_rejects_changed_service_type_with_controlled_error(self):
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = {**_sample_catalog_record(), "service_type": "incident"}

        with pytest.raises(HTTPException) as exc:
            service_catalog_service.update_service_catalog(
                "svc-001",
                {"service_type": "service_request", "name": "Updated"},
                repository=repository,
            )

        assert exc.value.status_code == 400
        assert exc.value.detail == "service_type is immutable after catalog creation"
        repository.update.assert_not_called()
