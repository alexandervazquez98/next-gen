"""Service-layer tests for ITSM service catalog behavior.

Focus on create/list/update/deactivate flow and validation failures.

Feature #480 S1: ``service_id`` is optional on create. The service mints
``sc-{value_stream_slug|name_slug}-{nanoid}`` when the caller omits it, keeps
explicit ids working, and never turns a duplicate id into an update.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
import services.itsm_service_catalog_service as service_catalog_service
from fastapi import HTTPException
from models.itsm import ServiceCatalogCreate, ServiceCatalogUpdate
from repositories.itsm_service_catalog_repo import ServiceCatalogConflictError

# ``sc-`` + up to 8 slug chars + ``-`` + 8 random chars = 20 chars (budget 21).
MINTED_SERVICE_ID_PATTERN = re.compile(r"^sc-[a-z0-9-]{1,8}-[A-Za-z0-9_-]{8}$")


class _CatalogRepositoryStub:
    """Repository double mirroring the real create-only persistence path.

    ``create`` is a real method (not an instance mock) so the service's
    capability probe finds it. ``upsert`` fails loudly: the create path must
    never use the historical update-on-match write.
    """

    def __init__(self):
        self.list = MagicMock()
        self.get_by_id = MagicMock()
        self.update = MagicMock()
        self.deactivate = MagicMock()
        self.find_by_type_and_normalized_name = MagicMock(return_value=None)
        self.created_payloads = []
        self.create_result = MagicMock(side_effect=lambda payload: payload.model_dump())

    def create(self, payload):
        self.created_payloads.append(payload)
        return self.create_result(payload)

    def upsert(self, payload):  # pragma: no cover - guarded by the tests below
        raise AssertionError("the create path must not use the legacy upsert write")


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
        "description": "Operational platform support",
        "value_stream": "operate",  # noqa: F601
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

        lookup = MagicMock()
        lookup.is_active.return_value = True

        created = service_catalog_service.create_service_catalog(
            {
                "id": "svc-legacy",
                "name": "Platform Core",
                "service_tier": "Silver",
                "sla_minutes": 45,
                "description": "Platform incident support",
                "value_stream": "operate",  # noqa: F601
                "service_type": "incident",
                "sla_target_minutes": 45,
                "description": "Network incident support",  # noqa: F601
                "value_stream": "operate",  # noqa: F601
            },
            actor="admin",
            repository=repository,
            value_stream_lookup=lookup,
        )

        assert created["service_id"] == "svc-legacy"
        assert created["id"] == "svc-legacy"
        assert created["tier"] == "Silver"
        assert created["sla_target_minutes"] == 45
        assert created["sla_minutes"] == 45
        assert created["active"] is True
        assert len(repository.created_payloads) == 1
        persisted_payload = repository.created_payloads[0]
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
        assert repository.created_payloads == []

    def test_create_catalog_auto_mints_service_id_when_missing(self):
        """S1: server mints sc-{value_stream_slug}-{nanoid} when service_id absent."""
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = None

        lookup = MagicMock()
        lookup.is_active.return_value = True

        created = service_catalog_service.create_service_catalog(
            {
                "name": "Auth Platform",
                "owner_team": "SRE",
                "sla_target_minutes": 30,
                "description": "Auth support",
                "value_stream": "operate",
                "service_type": "incident",
            },
            actor="admin",
            repository=repository,
            value_stream_lookup=lookup,
        )

        assert MINTED_SERVICE_ID_PATTERN.match(created["service_id"])
        assert created["service_id"].startswith("sc-operate-")
        assert len(created["service_id"]) <= 21
        assert len(repository.created_payloads) == 1
        persisted_payload = repository.created_payloads[0]
        assert isinstance(persisted_payload, ServiceCatalogCreate)
        assert persisted_payload.service_id == created["service_id"]
        assert persisted_payload.id == created["service_id"]

    def test_minted_service_id_slug_falls_back_to_name_when_value_stream_absent(self):
        """S1 ODD decision #3: ``sc-{value_stream_slug|name_slug}-{nanoid}``."""
        from services.itsm_service_catalog_service import _slugify_segment

        assert _slugify_segment("operate") == "operate"
        assert _slugify_segment("Operate") == "operate"
        assert _slugify_segment("deliver") == "deliver"
        assert _slugify_segment("") == "nil"
        assert _slugify_segment(None) == "nil"
        assert _slugify_segment("Network Operations!") == "network-"  # 8-char cap
        assert _slugify_segment("@#$%") == "nil"  # all garbage → nil
        assert _slugify_segment("Auth Platform") == "auth-pla"  # name fallback slug

    def test_create_catalog_auto_mint_is_unique_even_when_same_inputs(self):
        """S1: two consecutive creates with identical inputs get distinct IDs (nanoid suffix)."""
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = None
        lookup = MagicMock()
        lookup.is_active.return_value = True

        base = {
            "name": "Notification Service",
            "sla_target_minutes": 10,
            "description": "Notifications",
            "value_stream": "operate",
            "service_type": "incident",
        }
        first = service_catalog_service.create_service_catalog(
            dict(base),
            actor="admin",
            repository=repository,
            value_stream_lookup=lookup,
        )
        second = service_catalog_service.create_service_catalog(
            dict(base),
            actor="admin",
            repository=repository,
            value_stream_lookup=lookup,
        )

        assert first["service_id"] != second["service_id"]
        assert first["service_id"].startswith("sc-operate-")
        assert second["service_id"].startswith("sc-operate-")

    def test_create_catalog_keeps_explicit_service_id(self):
        """S1: an explicit service_id stays untouched (backwards compatible)."""
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = None
        lookup = MagicMock()
        lookup.is_active.return_value = True

        created = service_catalog_service.create_service_catalog(
            {
                "service_id": "svc-explicit",
                "name": "Legacy Platform",
                "sla_target_minutes": 30,
                "description": "Legacy support",
                "value_stream": "operate",
                "service_type": "incident",
            },
            actor="admin",
            repository=repository,
            value_stream_lookup=lookup,
        )

        assert created["service_id"] == "svc-explicit"
        assert created["id"] == "svc-explicit"

    def test_create_catalog_rejects_duplicate_explicit_service_id_without_writing(self):
        """S1: a duplicate explicit id must not overwrite the existing row.

        Historical contract: an explicitly supplied duplicate id stays HTTP 400.
        """
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = {"service_id": "svc-duplicate"}

        lookup = MagicMock()
        lookup.is_active.return_value = True

        with pytest.raises(HTTPException) as exc:
            service_catalog_service.create_service_catalog(
                {
                    "service_id": "svc-duplicate",
                    "name": "Another Platform",
                    "sla_target_minutes": 30,
                    "description": "Another support",
                    "value_stream": "operate",
                    "service_type": "incident",
                },
                actor="admin",
                repository=repository,
                value_stream_lookup=lookup,
            )

        assert exc.value.status_code == 400
        assert "service_id" in exc.value.detail
        assert repository.created_payloads == []

    def test_create_catalog_surfaces_atomic_conflict_on_explicit_id_as_400(self):
        """S1: a race on an explicit id stays a 400 bad request, never an update."""
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = None
        repository.create_result.side_effect = ServiceCatalogConflictError("svc-duplicate")

        lookup = MagicMock()
        lookup.is_active.return_value = True

        with pytest.raises(HTTPException) as exc:
            service_catalog_service.create_service_catalog(
                {
                    "service_id": "svc-duplicate",
                    "name": "Racing Platform",
                    "sla_target_minutes": 30,
                    "description": "Race support",
                    "value_stream": "operate",
                    "service_type": "incident",
                },
                actor="admin",
                repository=repository,
                value_stream_lookup=lookup,
            )

        assert exc.value.status_code == 400
        assert "service_id" in exc.value.detail
        assert len(repository.created_payloads) == 1
        repository.update.assert_not_called()

    def test_create_catalog_retries_minted_id_after_a_collision(self):
        """S1: a collision on a minted id retries with a fresh id."""
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = None
        repository.find_by_type_and_normalized_name.return_value = None
        calls: list[str] = []

        def _create(payload):
            calls.append(payload.service_id)
            if len(calls) == 1:
                raise ServiceCatalogConflictError(payload.service_id)
            return payload.model_dump()

        repository.create_result.side_effect = _create
        lookup = MagicMock()
        lookup.is_active.return_value = True

        created = service_catalog_service.create_service_catalog(
            {
                "name": "Retried Platform",
                "sla_target_minutes": 30,
                "description": "Retry support",
                "value_stream": "operate",
                "service_type": "incident",
            },
            actor="admin",
            repository=repository,
            value_stream_lookup=lookup,
        )

        assert len(calls) == 2
        assert calls[0] != calls[1]
        assert created["service_id"] == calls[1]

    def test_create_catalog_returns_409_when_minted_id_retries_are_exhausted(self):
        """S1: a minted id that keeps colliding ends as a 409 conflict."""
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = None
        repository.create_result.side_effect = ServiceCatalogConflictError("sc-operate-collide")

        lookup = MagicMock()
        lookup.is_active.return_value = True

        with pytest.raises(HTTPException) as exc:
            service_catalog_service.create_service_catalog(
                {
                    "name": "Always Colliding",
                    "sla_target_minutes": 30,
                    "description": "Collision support",
                    "value_stream": "operate",
                    "service_type": "incident",
                },
                actor="admin",
                repository=repository,
                value_stream_lookup=lookup,
            )

        assert exc.value.status_code == 409
        assert "service_id" in exc.value.detail
        assert len(repository.created_payloads) == service_catalog_service.SERVICE_ID_MINT_ATTEMPTS
        repository.update.assert_not_called()

    def test_create_catalog_falls_back_to_upsert_for_legacy_repositories(self):
        """Repositories that predate the create-only primitive keep working."""

        class _LegacyRepository:
            def __init__(self):
                self.get_by_id = MagicMock(return_value=None)
                self.find_by_type_and_normalized_name = MagicMock(return_value=None)
                self.upserted = []

            def upsert(self, payload):
                self.upserted.append(payload)
                return payload.model_dump()

        repository = _LegacyRepository()
        lookup = MagicMock()
        lookup.is_active.return_value = True

        created = service_catalog_service.create_service_catalog(
            {
                "service_id": "svc-legacy-call",
                "name": "Legacy Caller",
                "sla_target_minutes": 30,
                "description": "Legacy caller support",
                "value_stream": "operate",
                "service_type": "incident",
            },
            actor="admin",
            repository=repository,
            value_stream_lookup=lookup,
        )

        assert created["service_id"] == "svc-legacy-call"
        assert len(repository.upserted) == 1

    def test_create_catalog_persists_through_the_create_only_primitive(self):
        """S1: create persistence must be create-only (no merge-on-match update)."""
        repository = _CatalogRepositoryStub()
        repository.get_by_id.return_value = None
        lookup = MagicMock()
        lookup.is_active.return_value = True

        service_catalog_service.create_service_catalog(
            {
                "name": "Create Only",
                "sla_target_minutes": 30,
                "description": "Create only support",
                "value_stream": "operate",
                "service_type": "incident",
            },
            actor="admin",
            repository=repository,
            value_stream_lookup=lookup,
        )

        assert len(repository.created_payloads) == 1
        repository.update.assert_not_called()

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
