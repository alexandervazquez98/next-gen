"""RED tests for PR1 server-generated ticket identity contracts."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from models.itsm import TicketFolioCreate, TicketFolioResponse
from pydantic import ValidationError
from repositories.ticket_folio_repo import TicketFolioRepository
from services.itsm_service_catalog_service import create_service_catalog, update_service_catalog
from services.ticket_folio_service import create_ticket_folio


class ActiveValueStreamLookup:
    def is_active(self, value: str) -> bool:
        return value == "operate"


def test_create_payload_rejects_client_ticket_id_and_uses_canonical_types():
    with pytest.raises(ValidationError, match="ticket_id"):
        TicketFolioCreate(
            ticket_id=42,
            type="incident",
            title="Router down",
            description="Core router unreachable",
        )

    payload = TicketFolioCreate(
        type="service_request",
        title="Access request",
        description="Grant access",
        service_catalog_id="svc-request",
    )
    assert payload.type == "service_request"

    with pytest.raises(ValidationError, match="service_request"):
        TicketFolioCreate(type="request", title="Legacy type")


def test_ticket_response_contract_exposes_numeric_generated_id():
    response = TicketFolioResponse(
        ticket_id=123,
        type="incident",
        title="Router down",
        description="Core router unreachable",
    )
    assert response.ticket_id == 123
    assert isinstance(response.ticket_id, int)


def test_repository_allocates_id_and_creates_ticket_in_one_write_transaction():
    session = MagicMock()
    session.execute_write.side_effect = lambda callback: callback(session)
    session.run.return_value.single.return_value = {"ticket_id": 17}
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session

    repository = TicketFolioRepository(driver=driver)
    created = repository.create_with_generated_id(
        TicketFolioCreate(type="incident", title="Router down", service_catalog_id="svc-incident")
    )

    assert created["ticket_id"] == 17
    session.execute_write.assert_called_once()
    session.run.assert_called_once()
    assert "TicketSequence" in session.run.call_args.args[0]
    assert "CREATE (tf:TicketFolio" in session.run.call_args.args[0]


def test_repository_rolls_back_ticket_and_sequence_when_relation_sync_fails():
    class TransactionalSession:
        def __init__(self):
            self.state = {"next_value": 0, "tickets": []}
            self.query = ""

        def execute_write(self, callback):
            snapshot = {
                "next_value": self.state["next_value"],
                "tickets": list(self.state["tickets"]),
            }
            try:
                return callback(self)
            except Exception:
                self.state = snapshot
                raise

        def run(self, query, **params):
            self.query = query
            self.state["next_value"] += 1
            self.state["tickets"].append(params)
            raise RuntimeError("service relation synchronization failed")

    session = TransactionalSession()
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session

    repository = TicketFolioRepository(driver=driver)
    with pytest.raises(RuntimeError, match="relation synchronization"):
        repository.create_with_generated_id(
            TicketFolioCreate(type="incident", title="Router down", service_catalog_id="svc-1")
        )

    assert session.state == {"next_value": 0, "tickets": []}
    assert "FOR_SERVICE" in session.query


def test_repository_rejects_missing_catalog_in_write_transaction_without_persisting_ticket():
    session = MagicMock()
    session.execute_write.side_effect = lambda callback: callback(session)
    session.run.return_value.single.return_value = None
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session

    repository = TicketFolioRepository(driver=driver)
    with pytest.raises(RuntimeError, match="ServiceCatalog"):
        repository.create_with_generated_id(
            TicketFolioCreate(
                type="incident", title="Router down", service_catalog_id="svc-deleted"
            )
        )

    query = session.run.call_args.args[0]
    assert "MATCH (sc:ServiceCatalog {service_id: $service_catalog_id})" in query
    assert "sc.service_type = $type" in query
    assert "coalesce(sc.active, true) = true" in query
    assert "OPTIONAL MATCH (sc:ServiceCatalog" not in query


def test_repository_rejects_missing_sequence_without_persisting_ticket():
    session = MagicMock()
    session.execute_write.side_effect = lambda callback: callback(session)
    session.run.return_value.single.return_value = None
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session

    repository = TicketFolioRepository(driver=driver)
    with pytest.raises(RuntimeError, match="TicketSequence"):
        repository.create_with_generated_id(
            TicketFolioCreate(
                type="incident", title="Router down", service_catalog_id="svc-incident"
            )
        )


def test_create_service_rejects_omitted_service_catalog_id_before_persistence():
    repository = MagicMock()

    with pytest.raises(ValidationError, match="service_catalog_id"):
        TicketFolioCreate(type="incident", title="Router down")

    with pytest.raises(HTTPException):
        create_ticket_folio(
            {"type": "incident", "title": "Router down"},
            actor="admin",
            repository=repository,
        )
    repository.create_with_generated_id.assert_not_called()


def test_create_service_rejects_missing_catalog_without_persistence():
    repository = MagicMock()
    catalog_repository = MagicMock()
    catalog_repository.get_by_id.return_value = None

    with pytest.raises(HTTPException, match="service_catalog"):
        create_ticket_folio(
            {
                "type": "incident",
                "title": "Router down",
                "service_catalog_id": "svc-missing",
            },
            repository=repository,
            catalog_repository=catalog_repository,
        )
    repository.create_with_generated_id.assert_not_called()


def test_create_service_accepts_existing_compatible_catalog():
    repository = MagicMock()
    repository.create_with_generated_id.return_value = {
        "ticket_id": 18,
        "type": "incident",
        "title": "Router down",
        "service_catalog_id": "svc-incident",
    }
    catalog_repository = MagicMock()
    catalog_repository.get_by_id.return_value = {
        "service_id": "svc-incident",
        "service_type": "incident",
        "active": True,
    }

    created = create_ticket_folio(
        {
            "type": "incident",
            "title": "Router down",
            "service_catalog_id": "svc-incident",
        },
        actor="admin",
        repository=repository,
        catalog_repository=catalog_repository,
    )

    assert created["ticket_id"] == 18
    repository.create_with_generated_id.assert_called_once()


def test_catalog_api_then_same_type_ticket_uses_persisted_type_and_active_status():
    catalog_repository = MagicMock()
    catalog_repository.upsert.side_effect = lambda payload: {
        **payload.model_dump(),
        "service_id": payload.service_id,
        "service_type": payload.service_type,
        "active": payload.active,
    }
    catalog_repository.get_by_id.side_effect = lambda service_id: (
        catalog_repository.upsert.call_args.args[0].model_dump()
        if catalog_repository.upsert.call_args
        else None
    )
    catalog_repository.find_by_type_and_normalized_name.return_value = None
    ticket_repository = MagicMock()
    ticket_repository.create_with_generated_id.return_value = {
        "ticket_id": 19,
        "type": "incident",
        "service_catalog_id": "svc-incident",
    }

    catalog = create_service_catalog(
        {
            "service_id": "svc-incident",
            "name": "Network Incident",
            "sla_target_minutes": 60,
            "description": "Network incident support",
            "service_type": "incident",
            "value_stream": "operate",
        },
        actor="admin",
        repository=catalog_repository,
        value_stream_lookup=ActiveValueStreamLookup(),
    )
    ticket = create_ticket_folio(
        {
            "type": "incident",
            "title": "Router down",
            "service_catalog_id": catalog["service_id"],
        },
        repository=ticket_repository,
        catalog_repository=catalog_repository,
    )

    assert catalog["service_type"] == "incident"
    assert catalog["active"] is True
    assert ticket["ticket_id"] == 19
    ticket_repository.create_with_generated_id.assert_called_once()


def test_ticket_rejects_incompatible_persisted_catalog_type():
    catalog_repository = MagicMock()
    catalog_repository.get_by_id.return_value = {
        "service_id": "svc-request",
        "service_type": "service_request",
        "active": True,
    }
    ticket_repository = MagicMock()

    with pytest.raises(HTTPException, match="compatible service_type"):
        create_ticket_folio(
            {
                "type": "incident",
                "title": "Router down",
                "service_catalog_id": "svc-request",
            },
            repository=ticket_repository,
            catalog_repository=catalog_repository,
        )

    ticket_repository.create_with_generated_id.assert_not_called()


def test_ticket_rejects_inactive_persisted_catalog():
    catalog_repository = MagicMock()
    catalog_repository.get_by_id.return_value = {
        "service_id": "svc-inactive",
        "service_type": "incident",
        "active": False,
    }
    ticket_repository = MagicMock()

    with pytest.raises(HTTPException, match="inactive"):
        create_ticket_folio(
            {
                "type": "incident",
                "title": "Router down",
                "service_catalog_id": "svc-inactive",
            },
            repository=ticket_repository,
            catalog_repository=catalog_repository,
        )

    ticket_repository.create_with_generated_id.assert_not_called()


def test_catalog_service_type_is_immutable_on_update():
    catalog_repository = MagicMock()
    catalog_repository.get_by_id.return_value = {
        "service_id": "svc-incident",
        "service_type": "incident",
        "active": True,
    }

    with pytest.raises(HTTPException, match="service_type"):
        update_service_catalog(
            "svc-incident",
            {"service_type": "service_request"},
            repository=catalog_repository,
        )

    catalog_repository.update.assert_not_called()
