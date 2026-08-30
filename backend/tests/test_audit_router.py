from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from postgres_db import Base, get_pg_db
from models.audit_event import AuditEvent
from models.user import User, UserPermission
from services.auth_service import get_current_active_user

_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app

client = TestClient(app)


@pytest.fixture()
def audit_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[AuditEvent.__table__])
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine, tables=[AuditEvent.__table__])


@pytest.fixture(autouse=True)
def override_pg_db(audit_db):
    def _override_get_pg_db():
        yield audit_db

    app.dependency_overrides[get_pg_db] = _override_get_pg_db
    yield
    app.dependency_overrides.pop(get_pg_db, None)
    app.dependency_overrides.pop(get_current_active_user, None)


def _user(username="auditor", permissions=None, role="OPERATOR"):
    return User(
        username=username,
        role=role,
        permissions=[permission.value for permission in (permissions or [])],
        allowed_locations=[],
        allowed_ci_types=None,
        disabled=False,
    )


def _set_current_user(user: User):
    async def _override():
        return user

    app.dependency_overrides[get_current_active_user] = _override


def _add_event(db, **kwargs):
    event = AuditEvent(**kwargs)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def test_audit_events_requires_audit_view_permission(audit_db):
    _add_event(
        audit_db,
        event_type="LOGIN_FAILURE",
        outcome="FAILURE",
        actor_username="alice",
        created_at=datetime.now(timezone.utc),
    )
    _set_current_user(_user(permissions=[UserPermission.EVENT_VIEW]))

    response = client.get("/api/audit/events")

    assert response.status_code == 403
    assert "items" not in response.text


def test_audit_events_filters_and_sorts_for_audit_view_user(audit_db):
    now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
    expected = _add_event(
        audit_db,
        event_type="LOGIN_FAILURE",
        outcome="FAILURE",
        actor_username="alice",
        target_type="auth",
        target_id="alice",
        target_label="alice",
        source="auth",
        ip_address="203.0.113.10",
        user_agent="pytest-agent",
        reason="incorrect_credentials",
        context={"route": "/api/auth/token"},
        created_at=now - timedelta(minutes=5),
    )
    _add_event(
        audit_db,
        event_type="LOGIN_SUCCESS",
        outcome="SUCCESS",
        actor_username="bob",
        target_type="auth",
        created_at=now - timedelta(minutes=4),
    )
    _add_event(
        audit_db,
        event_type="ROLE_UPDATE",
        outcome="SUCCESS",
        actor_username="alice",
        target_type="role",
        created_at=now - timedelta(days=3),
    )
    _set_current_user(_user(permissions=[UserPermission.AUDIT_VIEW]))

    response = client.get(
        "/api/audit/events",
        params={
            "start_time": (now - timedelta(hours=1)).isoformat(),
            "end_time": now.isoformat(),
            "actor": "alice",
            "event_type": "LOGIN_FAILURE",
            "outcome": "FAILURE",
            "target_type": "auth",
            "page": 1,
            "page_size": 10,
            "sort": "created_at_desc",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert [item["id"] for item in body["items"]] == [expected.id]
    item = body["items"][0]
    assert item["schema_version"] == 1
    assert item["actor_username"] == "alice"
    assert item["ip_address"] == "203.0.113.10"
    assert item["context"] == {"route": "/api/auth/token"}


def test_audit_events_paginates_and_supports_ascending_sort(audit_db):
    base = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
    first = _add_event(audit_db, event_type="A", outcome="SUCCESS", created_at=base)
    second = _add_event(audit_db, event_type="B", outcome="SUCCESS", created_at=base + timedelta(minutes=1))
    third = _add_event(audit_db, event_type="C", outcome="SUCCESS", created_at=base + timedelta(minutes=2))
    _set_current_user(_user(permissions=[UserPermission.AUDIT_VIEW]))

    response = client.get(
        "/api/audit/events",
        params={"page": 2, "page_size": 1, "sort": "created_at_asc"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["id"] for item in body["items"]] == [second.id]


def test_audit_events_rejects_invalid_time_range(audit_db):
    _set_current_user(_user(permissions=[UserPermission.AUDIT_VIEW]))

    response = client.get(
        "/api/audit/events",
        params={
            "start_time": "2026-06-08T00:00:00Z",
            "end_time": "2026-06-07T00:00:00Z",
        },
    )

    assert response.status_code == 422


def test_audit_events_filter_by_target_id_returns_only_that_mapping(audit_db):
    """Issue #386 — a mapping's audit history must be retrievable by target_id."""
    # `created_at` is stored as naive UTC by audit_service, so build it that way here.
    now = datetime(2026, 6, 7, 12, 0)
    _add_event(
        audit_db,
        event_type="MQTT_MAPPING_CREATE",
        outcome="SUCCESS",
        actor_username="operator",
        target_type="mqtt_mapping",
        target_id="map-1",
        created_at=now - timedelta(minutes=2),
    )
    _add_event(
        audit_db,
        event_type="MQTT_MAPPING_APPROVE",
        outcome="SUCCESS",
        actor_username="operator",
        target_type="mqtt_mapping",
        target_id="map-1",
        created_at=now - timedelta(minutes=1),
    )
    _add_event(
        audit_db,
        event_type="MQTT_MAPPING_CREATE",
        outcome="SUCCESS",
        actor_username="operator",
        target_type="mqtt_mapping",
        target_id="map-2",
        created_at=now,
    )
    _set_current_user(_user(permissions=[UserPermission.AUDIT_VIEW]))

    response = client.get(
        "/api/audit/events",
        params={
            "target_type": "mqtt_mapping",
            "target_id": "map-1",
            "sort": "created_at_asc",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["event_type"] for item in payload["items"]] == [
        "MQTT_MAPPING_CREATE",
        "MQTT_MAPPING_APPROVE",
    ]
    assert {item["target_id"] for item in payload["items"]} == {"map-1"}
