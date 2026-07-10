"""Work Unit 1 domain contracts for ITSM Service Catalog and Ticket/Folio."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from models.itsm import (
    TICKET_STATUS_ORDER,
    ServiceCatalogCreate,
    TicketFolioCreate,
    TicketFolioType,
    TicketFolioUpdate,
    TicketFolioUpdateArchive,
    TicketStatus,
    validate_ticket_transition,
)
from pydantic import ValidationError
from services.itsm_bootstrap import run_service_catalog_preflight


class TestServiceCatalogDomainContract:
    """Contract expectations for ServiceCatalog alias compatibility and SLA validation."""

    def test_service_catalog_accepts_canonical_service_id_and_builds_aliases(self):
        payload = ServiceCatalogCreate(
            service_id="svc-net-01",
            name="WAN Platform",
            category="NETWORK",
            tier="Gold",
            sla_target_minutes=45,
            owner_team="NetOps",
            criticality="High",
            service_type="incident",
        )

        assert payload.service_id == "svc-net-01"
        assert payload.id == "svc-net-01"
        assert payload.service_tier == "Gold"
        assert payload.sla_minutes == 45
        assert payload.sla_target_minutes == 45
        assert payload.sla_target_minutes >= 0

    def test_service_catalog_accepts_legacy_alias_fields(self):
        payload = ServiceCatalogCreate(
            id="svc-legacy-01",
            name="Legacy Service",
            category="CORE",
            service_tier="Silver",
            sla_minutes=60,
            service_type="service_request",
        )

        assert payload.service_id == "svc-legacy-01"
        assert payload.id == "svc-legacy-01"
        assert payload.tier == "Silver"
        assert payload.sla_target_minutes == 60

    def test_service_catalog_alias_mismatch_is_rejected(self):
        with pytest.raises(ValidationError):
            ServiceCatalogCreate(
                service_id="svc-01",
                id="svc-02",
                name="Mismatch",
                sla_target_minutes=30,
            )

    def test_service_catalog_rejects_negative_sla_target_minutes(self):
        with pytest.raises(ValidationError):
            ServiceCatalogCreate(
                service_id="svc-neg-01",
                name="Bad SLA",
                sla_target_minutes=-1,
            )

    def test_service_catalog_rejects_negative_legacy_sla_minutes(self):
        with pytest.raises(ValidationError):
            ServiceCatalogCreate(
                id="svc-legacy-neg-01",
                name="Bad Legacy SLA",
                sla_minutes=-10,
                category="NETWORK",
            )


class TestTicketFolioTypeAndLifecycle:
    """Contract expectations for Ticket/Folio type and linear lifecycle order."""

    def test_ticket_folio_type_is_limited_to_incident_and_service_request(self):
        for ticket_type in (TicketFolioType.SERVICE_REQUEST, TicketFolioType.INCIDENT):
            payload = TicketFolioCreate(
                type=ticket_type,
                title="Reset password",
                description="Request access reset",
                    service_catalog_id="svc-request",
            )
            assert payload.type == ticket_type

        with pytest.raises(ValidationError):
            TicketFolioCreate(type="request", title="Legacy request")

        with pytest.raises(ValidationError):
            TicketFolioCreate(type="change", title="Change request")

        with pytest.raises(ValidationError, match="ticket_id"):
            TicketFolioCreate(type="incident", title="Client supplied ID", ticket_id=2)

    def test_ticket_transition_only_allows_linear_progression(self):
        assert validate_ticket_transition(TicketStatus.OPEN, TicketStatus.IN_PROGRESS)
        assert validate_ticket_transition(TicketStatus.IN_PROGRESS, TicketStatus.IN_VALIDATION)
        assert validate_ticket_transition(TicketStatus.IN_VALIDATION, TicketStatus.RESOLVED)
        assert validate_ticket_transition(TicketStatus.RESOLVED, TicketStatus.CLOSED)

    def test_ticket_transition_rejects_regressions_and_skips(self):
        with pytest.raises(ValueError):
            validate_ticket_transition(TicketStatus.OPEN, TicketStatus.RESOLVED)

        with pytest.raises(ValueError):
            validate_ticket_transition(TicketStatus.CLOSED, TicketStatus.OPEN)

        with pytest.raises(ValueError):
            validate_ticket_transition(TicketStatus.OPEN, TicketStatus.OPEN)

    def test_ticket_lifecycle_order_is_strict_linear_contract(self):
        assert list(TICKET_STATUS_ORDER) == [
            "open",
            "in_progress",
            "in_validation",
            "resolved",
            "closed",
        ]


class TestTicketHardDeleteContract:
    """Ticket/Folio updates should remain logical (archived/closed), not hard-delete."""

    def test_ticket_update_model_models_logical_lifecycle_only(self):
        fields = TicketFolioUpdate.model_fields
        assert "archived" in fields
        assert "closed_reason" in fields
        assert "status" in fields
        assert "delete" not in fields

    def test_ticket_archive_request_uses_update_contract(self):
        payload = TicketFolioUpdateArchive(
            archived=True,
            closed_reason="Legacy cleanup",
        )
        assert payload.archived is True
        assert payload.closed_reason == "Legacy cleanup"


class TestItsmBootstrapPreflightContract:
    """Startup preflight should fail only when blockers are present."""

    def test_preflight_passes_on_clean_identity_input(self):
        session = MagicMock()
        session.run.side_effect = [
            [],
            [],
        ]

        driver = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__enter__.return_value = session
        session_ctx.__exit__.return_value = False
        driver.session.return_value = session_ctx

        run_service_catalog_preflight(driver=driver)

    def test_preflight_blocks_duplicate_or_conflicting_catalog_identity(self):
        session = MagicMock()
        session.run.side_effect = [
            [
                {"canonical_id": "svc-dup", "total": 2},
                {"canonical_id": "svc-other", "total": 3},
            ],
            [
                {
                    "canonical_id": "svc-bad",
                    "service_id": "svc-bad",
                    "legacy_id": "svc-legacy-bad",
                }
            ],
        ]

        driver = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__enter__.return_value = session
        session_ctx.__exit__.return_value = False
        driver.session.return_value = session_ctx

        with pytest.raises(RuntimeError) as exc:
            run_service_catalog_preflight(driver=driver)

        assert "itsm catalog preflight failed" in str(exc.value).lower()
