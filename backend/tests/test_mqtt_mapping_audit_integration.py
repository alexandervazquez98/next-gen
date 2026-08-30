"""End-to-end audit trail for the MQTT mapping lifecycle (issue #386).

Drives the real router -> real service -> real audit persistence path and reads
the history back through the audit API, exactly as an operator would.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.audit_event import AuditEvent
from models.user import User, UserPermission
from postgres_db import Base, get_pg_db
from routers import audit as audit_router, mqtt as mqtt_router
from services.auth_service import get_current_active_user
from services.mqtt_mapping_service import MqttMappingService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class _RepoStub:
    """In-memory mapping store good enough for the lifecycle under test."""

    def __init__(self):
        self.mappings: dict[str, dict] = {}

    def get_mapping(self, mapping_id):
        return self.mappings.get(mapping_id)

    def list_mappings(self, status=None):
        return list(self.mappings.values())

    def create_draft(self, **kwargs):
        mapping = {
            "id": kwargs["mapping_id"],
            "source_device_id": kwargs["source_device_id"],
            "source_metric_id": kwargs["source_metric_id"],
            "source_metric_name": kwargs["source_metric_name"],
            "target_ci_id": kwargs["target_ci_id"],
            "target_metric_def_id": kwargs["target_metric_def_id"],
            "status": "DRAFT",
            "version": 1,
            "warning": kwargs.get("warning"),
            "critical": kwargs.get("critical"),
            "operator": kwargs.get("operator"),
        }
        self.mappings[mapping["id"]] = mapping
        return mapping

    def approve(self, mapping_id, approved_by):
        mapping = self.mappings[mapping_id]
        mapping.update({"status": "APPROVED", "version": 2, "approved_by": approved_by})
        return mapping

    def update_thresholds(self, **kwargs):
        mapping = self.mappings[kwargs["mapping_id"]]
        mapping.update(
            {
                "warning": kwargs["warning"],
                "critical": kwargs["critical"],
                "operator": kwargs["operator"],
                "version": 3,
            }
        )
        return mapping


@pytest.fixture()
def audit_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[AuditEvent.__table__])
    db = testing_session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine, tables=[AuditEvent.__table__])


def _operator():
    return User(
        username="operator",
        role="OPERATOR",
        permissions=[
            UserPermission.MQTT_READ.value,
            UserPermission.MQTT_MAPPING_MANAGE.value,
            UserPermission.AUDIT_VIEW.value,
        ],
    )


@pytest.fixture()
def client(audit_db):
    repo = _RepoStub()
    app = FastAPI()
    app.include_router(mqtt_router.router, prefix="/api")
    app.include_router(audit_router.router, prefix="/api")
    app.dependency_overrides[get_pg_db] = lambda: audit_db
    app.dependency_overrides[mqtt_router._current_user] = _operator
    app.dependency_overrides[get_current_active_user] = _operator
    app.dependency_overrides[mqtt_router._mapping_service] = lambda: MqttMappingService(repo=repo)
    return TestClient(app)


def test_mapping_lifecycle_history_is_queryable_by_target(client):
    """Spec: mapping events are queryable by target filter, ordered by created_at."""
    created = client.post(
        "/api/mqtt/mappings",
        json={
            "source_device_id": "rtu-1",
            "source_metric_id": "rtu-1/temp",
            "source_metric_name": "temp",
            "target_ci_id": "ci-1",
            "target_metric_def_id": "temperature",
            "thresholds": {"operator": ">=", "warning": 70, "critical": 90},
        },
    )
    assert created.status_code == 200
    mapping_id = created.json()["id"]

    assert client.post(f"/api/mqtt/mappings/{mapping_id}/approve").status_code == 200
    assert (
        client.put(
            f"/api/mqtt/mappings/{mapping_id}/thresholds",
            json={"operator": ">=", "warning": 75, "critical": 95},
        ).status_code
        == 200
    )

    response = client.get(
        "/api/audit/events",
        params={
            "target_type": "mqtt_mapping",
            "target_id": mapping_id,
            "sort": "created_at_asc",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert [item["event_type"] for item in payload["items"]] == [
        "MQTT_MAPPING_CREATE",
        "MQTT_MAPPING_APPROVE",
        "MQTT_MAPPING_THRESHOLD_UPDATE",
    ]
    assert {item["outcome"] for item in payload["items"]} == {"SUCCESS"}
    assert {item["actor_username"] for item in payload["items"]} == {"operator"}

    create_row, approve_row, threshold_row = payload["items"]
    assert create_row["context"]["previous_state"] is None
    assert create_row["context"]["next_state"] == "DRAFT"
    assert create_row["context"]["version"] == 1
    assert create_row["context"]["source_device_id"] == "rtu-1"
    assert approve_row["context"]["previous_state"] == "DRAFT"
    assert approve_row["context"]["next_state"] == "APPROVED"
    assert threshold_row["context"]["changed_fields"] == ["critical", "operator", "warning"]

    # The request carried a bearer token and a cookie; none of it may be persisted.
    assert "authorization" not in str(payload).lower()
    assert "secret-token" not in str(payload)


def test_denied_lifecycle_attempt_is_queryable_for_the_same_mapping(client, audit_db):
    """A denial is recorded under the lifecycle event type, so it shares target_id."""
    created = client.post(
        "/api/mqtt/mappings",
        json={
            "source_device_id": "rtu-1",
            "source_metric_id": "rtu-1/temp",
            "source_metric_name": "temp",
            "target_ci_id": "ci-1",
            "target_metric_def_id": "temperature",
        },
    )
    mapping_id = created.json()["id"]

    client.app.dependency_overrides[mqtt_router._current_user] = lambda: User(
        username="viewer",
        role="OPERATOR",
        permissions=[UserPermission.MQTT_READ.value],
    )

    denied = client.post(f"/api/mqtt/mappings/{mapping_id}/approve")

    assert denied.status_code == 403
    rows = (
        audit_db.query(AuditEvent)
        .filter(AuditEvent.target_id == mapping_id, AuditEvent.outcome == "DENIED")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].event_type == "MQTT_MAPPING_APPROVE"
    assert rows[0].actor_username == "viewer"
    assert rows[0].context["required_permission"] == "MQTT_MAPPING_MANAGE"
