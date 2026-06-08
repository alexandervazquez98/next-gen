from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from postgres_db import Base
from models.audit_event import AuditEvent
from services.audit_service import (
    AUDIT_CONTEXT_ALLOWED_KEYS,
    cleanup_old_events,
    record_auth_event,
    record_critical_change,
)


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


class _Request:
    def __init__(self):
        self.client = type("Client", (), {"host": "203.0.113.10"})()
        self.headers = {
            "user-agent": "pytest-agent",
            "authorization": "Bearer must-not-persist",
            "cookie": "refresh_token=must-not-persist",
            "x-request-id": "req-123",
        }
        self.url = type("URL", (), {"path": "/api/auth/token"})()
        self.method = "POST"


def test_record_auth_event_persists_versioned_schema_and_safe_request_metadata(audit_db):
    event = record_auth_event(
        audit_db,
        request=_Request(),
        event_type="LOGIN_FAILURE",
        outcome="FAILURE",
        actor_username="alice",
        reason="incorrect_credentials",
        context={
            "route": "/api/auth/token",
            "password": "super-secret",
            "token": "secret-token",
            "raw_body": {"password": "super-secret"},
            "changed_fields": ["role"],
        },
    )

    stored = audit_db.query(AuditEvent).one()
    assert event.id == stored.id
    assert stored.schema_version == 1
    assert stored.event_type == "LOGIN_FAILURE"
    assert stored.outcome == "FAILURE"
    assert stored.actor_username == "alice"
    assert stored.target_type == "auth"
    assert stored.ip_address == "203.0.113.10"
    assert stored.user_agent == "pytest-agent"
    assert stored.reason == "incorrect_credentials"
    assert stored.context["route"] == "/api/auth/token"
    assert stored.context["changed_fields"] == ["role"]
    assert "request_id" in stored.context

    serialized = str(stored.context).lower()
    assert "super-secret" not in serialized
    assert "secret-token" not in serialized
    assert "raw_body" not in stored.context
    assert "password" not in stored.context
    assert set(stored.context).issubset(AUDIT_CONTEXT_ALLOWED_KEYS)


def test_record_critical_change_truncates_free_text_and_rejects_sensitive_context(audit_db):
    long_reason = "x" * 300

    record_critical_change(
        audit_db,
        request=None,
        actor=type("User", (), {"username": "operator", "role": "OPERATOR"})(),
        event_type="USER_UPDATE",
        outcome="SUCCESS",
        target_type="user",
        target_id="bob",
        target_label="Bob Example" * 100,
        reason=long_reason,
        source="users",
        context={"changed_fields": ["email"], "authorization": "Bearer secret"},
    )

    stored = audit_db.query(AuditEvent).one()
    assert stored.actor_username == "operator"
    assert stored.actor_role == "OPERATOR"
    assert stored.target_type == "user"
    assert stored.target_id == "bob"
    assert len(stored.reason) <= 128
    assert len(stored.target_label) <= 256
    assert stored.context == {"changed_fields": ["email"]}


def test_cleanup_old_events_deletes_strictly_older_than_90_days(audit_db):
    now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
    old_event = AuditEvent(
        event_type="LOGIN_FAILURE",
        outcome="FAILURE",
        created_at=now - timedelta(days=90, seconds=1),
    )
    boundary_event = AuditEvent(
        event_type="LOGIN_SUCCESS",
        outcome="SUCCESS",
        created_at=now - timedelta(days=90),
    )
    recent_event = AuditEvent(
        event_type="LOGOUT",
        outcome="SUCCESS",
        created_at=now - timedelta(days=1),
    )
    audit_db.add_all([old_event, boundary_event, recent_event])
    audit_db.commit()

    deleted = cleanup_old_events(audit_db, retention_days=90, now=now)

    remaining_types = {event.event_type for event in audit_db.query(AuditEvent).all()}
    assert deleted == 1
    assert remaining_types == {"LOGIN_SUCCESS", "LOGOUT"}
