"""Service-layer tests for ITSM ticket/folio lifecycle and transitions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import services.ticket_folio_service as ticket_service


class _CatalogRepoStub:
    def __init__(self):
        self.get_by_id = MagicMock()


class _TicketRepoStub:
    def __init__(self):
        self.get = MagicMock()
        self.list = MagicMock()
        self.upsert = MagicMock()
        self.update = MagicMock()
        self.sync_service_relationship = MagicMock()


def _sample_ticket_record(status: str = "open") -> dict:
    return {
        "ticket_id": "TK-001",
        "type": "request",
        "title": "Request access",
        "description": "Please grant access",
        "service_catalog_id": "svc-001",
        "status": status,
        "archived": False,
        "closed_reason": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "updated_by": "admin",
    }


class TestTicketFolioService:
    """Validate ticket lifecycle policy and no hard-delete semantics in service logic."""

    def test_create_ticket_defaults_to_open_and_resolves_catalog_id(self):
        catalog_repo = _CatalogRepoStub()
        catalog_repo.get_by_id.return_value = {"service_id": "svc-001"}
        ticket_repo = _TicketRepoStub()
        ticket_repo.upsert.return_value = _sample_ticket_record()

        created = ticket_service.create_ticket_folio(
            {
                "ticket_id": "TK-001",
                "type": "request",
                "title": "Request access",
                "description": "Please grant access",
                "service_catalog_id": "svc-001",
            },
            actor="admin",
            repository=ticket_repo,
            catalog_repository=catalog_repo,
        )

        assert created["ticket_id"] == "TK-001"
        assert created["status"] == "open"
        assert created["service_catalog_id"] == "svc-001"
        assert ticket_repo.sync_service_relationship.call_count == 1

    def test_create_ticket_rejects_blank_title(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()

        with pytest.raises(HTTPException) as exc:
            ticket_service.create_ticket_folio(
                {
                    "ticket_id": "TK-blank",
                    "type": "request",
                    "title": "   ",
                },
                repository=ticket_repo,
                catalog_repository=catalog_repo,
            )

        assert exc.value.status_code == 400
        assert "title" in exc.value.detail.lower()
        ticket_repo.upsert.assert_not_called()

    def test_create_ticket_rejects_invalid_type(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()

        with pytest.raises(HTTPException) as exc:
            ticket_service.create_ticket_folio(
                {
                    "ticket_id": "TK-002",
                    "type": "change",
                    "title": "Change request",
                },
                repository=ticket_repo,
                catalog_repository=catalog_repo,
            )

        assert exc.value.status_code == 400
        ticket_repo.upsert.assert_not_called()
        ticket_repo.sync_service_relationship.assert_not_called()

    def test_create_ticket_requires_existing_catalog_when_catalog_id_provided(self):
        catalog_repo = _CatalogRepoStub()
        catalog_repo.get_by_id.return_value = None
        ticket_repo = _TicketRepoStub()

        with pytest.raises(HTTPException) as exc:
            ticket_service.create_ticket_folio(
                {
                    "ticket_id": "TK-003",
                    "type": "incident",
                    "title": "Production alarm",
                    "service_catalog_id": "svc-missing",
                },
                repository=ticket_repo,
                catalog_repository=catalog_repo,
            )

        assert exc.value.status_code == 404
        assert "service_catalog" in exc.value.detail.lower()
        ticket_repo.upsert.assert_not_called()

    def test_transition_rejects_skip_and_regression(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()
        ticket_repo.get.return_value = _sample_ticket_record("open")

        with pytest.raises(HTTPException) as exc:
            ticket_service.transition_ticket_folio(
                "TK-001",
                next_status="resolved",
                catalog_repository=catalog_repo,
                repository=ticket_repo,
                actor="admin",
            )

        assert exc.value.status_code == 409
        assert "transition" in exc.value.detail.lower()
        ticket_repo.update.assert_not_called()

    def test_transition_to_closed_requires_closed_reason(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()
        ticket_repo.get.return_value = _sample_ticket_record("resolved")

        with pytest.raises(HTTPException) as exc:
            ticket_service.transition_ticket_folio(
                "TK-001",
                next_status="closed",
                actor="admin",
                repository=ticket_repo,
                catalog_repository=catalog_repo,
            )

        assert exc.value.status_code == 400
        assert "closed_reason" in exc.value.detail.lower()
        ticket_repo.update.assert_not_called()

    def test_transition_to_closed_archives_and_persists_reason(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()
        ticket_repo.get.return_value = _sample_ticket_record("resolved")
        ticket_repo.update.return_value = {
            **_sample_ticket_record("resolved"),
            "status": "closed",
            "archived": True,
            "closed_reason": "Incident resolved and verified",
            "updated_by": "admin",
        }

        updated = ticket_service.transition_ticket_folio(
            "TK-001",
            next_status="closed",
            closed_reason="Incident resolved and verified",
            actor="admin",
            repository=ticket_repo,
            catalog_repository=catalog_repo,
        )

        assert updated["status"] == "closed"
        assert updated["archived"] is True
        assert updated["closed_reason"] == "Incident resolved and verified"
        assert ticket_repo.update.called

    def test_update_ticket_allows_clearing_optional_fields_and_syncs_relation(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()
        ticket_repo.get.return_value = _sample_ticket_record("open")
        ticket_repo.update.return_value = {
            **_sample_ticket_record("open"),
            "description": None,
            "service_catalog_id": None,
        }

        ticket_service.update_ticket_folio(
            "TK-001",
            {"description": None, "service_catalog_id": None},
            repository=ticket_repo,
            catalog_repository=catalog_repo,
        )

        update_payload = ticket_repo.update.call_args.args[1]
        assert "description" in update_payload.model_fields_set
        assert "service_catalog_id" in update_payload.model_fields_set
        ticket_repo.sync_service_relationship.assert_called_once_with("TK-001", None)

    def test_closed_ticket_rejects_direct_updates(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()
        ticket_repo.get.return_value = _sample_ticket_record("closed")

        with pytest.raises(HTTPException) as exc:
            ticket_service.update_ticket_folio(
                "TK-001",
                {"title": "Should not change"},
                repository=ticket_repo,
                catalog_repository=catalog_repo,
            )

        assert exc.value.status_code == 409
        assert "read-only" in exc.value.detail.lower()
        ticket_repo.update.assert_not_called()

    def test_archived_cannot_be_changed_without_closing_transition(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()
        ticket_repo.get.return_value = _sample_ticket_record("open")

        with pytest.raises(HTTPException) as exc:
            ticket_service.update_ticket_folio(
                "TK-001",
                {"archived": True},
                repository=ticket_repo,
                catalog_repository=catalog_repo,
            )

        assert exc.value.status_code == 409
        assert "archived" in exc.value.detail.lower()
        ticket_repo.update.assert_not_called()

    def test_update_ticket_rejects_rollback_transition(self):
        catalog_repo = _CatalogRepoStub()
        ticket_repo = _TicketRepoStub()
        ticket_repo.get.return_value = _sample_ticket_record("in_validation")

        with pytest.raises(HTTPException) as exc:
            ticket_service.update_ticket_folio(
                "TK-001",
                {
                    "status": "open",
                },
                repository=ticket_repo,
                catalog_repository=catalog_repo,
            )

        assert exc.value.status_code == 409
        assert "transition" in exc.value.detail.lower()
        ticket_repo.update.assert_not_called()
