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


# PR1 #287 — auth session lifecycle context keys must be allow-listed so
# `session.activity_recorded` and `session.idle_expired` audit events persist
# the safe session/user/policy context they need. Sensitive keys must still
# be stripped.

PR1_SESSION_LIFECYCLE_KEYS = {
    "session_id",
    "user_id",
    "policy_profile",
    "throttle_seconds",
    "activity_anchor",
}


def test_pr1_session_lifecycle_keys_are_allow_listed():
    """PR1 session lifecycle keys must be in AUDIT_CONTEXT_ALLOWED_KEYS."""
    missing = PR1_SESSION_LIFECYCLE_KEYS - AUDIT_CONTEXT_ALLOWED_KEYS
    assert not missing, (
        f"AUDIT_CONTEXT_ALLOWED_KEYS missing PR1 session lifecycle keys: {missing}"
    )


def test_record_auth_event_persists_pr1_session_lifecycle_context(audit_db):
    """Safe session lifecycle context must survive sanitization."""
    record_auth_event(
        audit_db,
        request=_Request(),
        event_type="session.activity_recorded",
        outcome="SUCCESS",
        actor_username="alice",
        reason="activity_recorded",
        context={
            "session_id": "sess-abc-123",
            "user_id": 42,
            "policy_profile": "standard",
            "throttle_seconds": 60,
            "activity_anchor": "last_activity_at",
        },
    )

    stored = audit_db.query(AuditEvent).one()
    assert stored.context["session_id"] == "sess-abc-123"
    assert stored.context["user_id"] == 42
    assert stored.context["policy_profile"] == "standard"
    assert stored.context["throttle_seconds"] == 60
    assert stored.context["activity_anchor"] == "last_activity_at"
    assert set(stored.context).issubset(AUDIT_CONTEXT_ALLOWED_KEYS)


def test_record_auth_event_strips_sensitive_keys_with_pr1_context(audit_db):
    """Sensitive keys must be stripped even when PR1 lifecycle keys are present."""
    record_auth_event(
        audit_db,
        request=_Request(),
        event_type="session.idle_expired",
        outcome="DENIED",
        actor_username="alice",
        reason="idle_timeout",
        context={
            "session_id": "sess-xyz-789",
            "user_id": 42,
            "policy_profile": "standard",
            "throttle_seconds": 60,
            "activity_anchor": "last_activity_at",
            # Sensitive noise that must still be filtered out:
            "token": "Bearer secret",
            "cookies": "session=deadbeef",
            "authorization": "Bearer secret",
            "raw_body": {"refresh_token": "must-not-persist"},
            "refresh_token": "raw-refresh",
        },
    )

    stored = audit_db.query(AuditEvent).one()
    # PR1 safe context preserved
    assert stored.context["session_id"] == "sess-xyz-789"
    assert stored.context["user_id"] == 42
    # Sensitive keys stripped
    for forbidden in (
        "token",
        "cookies",
        "authorization",
        "raw_body",
        "refresh_token",
    ):
        assert forbidden not in stored.context
    serialized = str(stored.context).lower()
    assert "secret" not in serialized
    assert "deadbeef" not in serialized
    assert "must-not-persist" not in serialized


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


# Issue #386 — MQTT mapping lifecycle context keys must be allow-listed so
# `MQTT_MAPPING_*` audit events persist mapping identifiers and lifecycle state.
# Sensitive payload/credential material must still be stripped.

MQTT_MAPPING_CONTEXT_KEYS = {
    "mapping_id",
    "source_device_id",
    "source_metric_id",
    "target_ci_id",
    "target_metric_def_id",
    "previous_state",
    "next_state",
    "version",
    "changed_fields",
}


def _mapping_actor():
    return type("User", (), {"username": "operator", "role": "OPERATOR"})()


def test_mqtt_mapping_context_keys_are_allow_listed():
    """Mapping lifecycle context keys must be in AUDIT_CONTEXT_ALLOWED_KEYS."""
    missing = MQTT_MAPPING_CONTEXT_KEYS - AUDIT_CONTEXT_ALLOWED_KEYS
    assert not missing, f"AUDIT_CONTEXT_ALLOWED_KEYS missing mapping lifecycle keys: {missing}"


def test_record_critical_change_preserves_mapping_context_verbatim(audit_db):
    """Spec: mapping context keys survive sanitization."""
    record_critical_change(
        audit_db,
        request=None,
        actor=_mapping_actor(),
        event_type="MQTT_MAPPING_APPROVE",
        outcome="SUCCESS",
        target_type="mqtt_mapping",
        target_id="map-1",
        target_label="map-1",
        reason="mapping_approved",
        source="mqtt_mapping",
        context={
            "mapping_id": "map-1",
            "source_device_id": "rtu-1",
            "source_metric_id": "rtu-1/temp",
            "target_ci_id": "ci-1",
            "target_metric_def_id": "temperature",
            "previous_state": "DRAFT",
            "next_state": "APPROVED",
            "version": 2,
            "changed_fields": ["status"],
        },
    )

    stored = audit_db.query(AuditEvent).one()
    assert stored.target_type == "mqtt_mapping"
    assert stored.target_id == "map-1"
    assert stored.context["mapping_id"] == "map-1"
    assert stored.context["source_device_id"] == "rtu-1"
    assert stored.context["source_metric_id"] == "rtu-1/temp"
    assert stored.context["target_ci_id"] == "ci-1"
    assert stored.context["target_metric_def_id"] == "temperature"
    assert stored.context["previous_state"] == "DRAFT"
    assert stored.context["next_state"] == "APPROVED"
    assert stored.context["version"] == 2
    assert stored.context["changed_fields"] == ["status"]


def test_mapping_context_strips_every_sensitive_key(audit_db):
    """Threat matrix row 1 — no credential or payload material may persist."""
    record_critical_change(
        audit_db,
        request=None,
        actor=_mapping_actor(),
        event_type="MQTT_MAPPING_CREATE",
        outcome="SUCCESS",
        target_type="mqtt_mapping",
        target_id="map-2",
        reason="mapping_created",
        source="mqtt_mapping",
        context={
            "mapping_id": "map-2",
            "next_state": "DRAFT",
            "body": "raw mqtt payload leak-me",
            "raw_body": {"password": "leak-me"},
            "request_body": "leak-me",
            "token": "Bearer leak-me",
            "session_token": "leak-me",
            "refresh_token": "leak-me",
            "cookie": "session=leak-me",
            "cookies": "session=leak-me",
            "authorization": "Bearer leak-me",
            "password": "leak-me",
        },
    )

    stored = audit_db.query(AuditEvent).one()
    assert stored.context["mapping_id"] == "map-2"
    assert stored.context["next_state"] == "DRAFT"
    for forbidden in (
        "body",
        "raw_body",
        "request_body",
        "token",
        "session_token",
        "refresh_token",
        "cookie",
        "cookies",
        "authorization",
        "password",
    ):
        assert forbidden not in stored.context
    assert "leak-me" not in str(stored.context).lower()
    assert set(stored.context).issubset(AUDIT_CONTEXT_ALLOWED_KEYS)


def test_mapping_context_drops_unknown_keys_and_caps_value_length(audit_db):
    """Spec: unknown keys are stripped; threat matrix row 3 — no source_topic, bounded values."""
    record_critical_change(
        audit_db,
        request=None,
        actor=_mapping_actor(),
        event_type="MQTT_MAPPING_UPDATE",
        outcome="SUCCESS",
        target_type="mqtt_mapping",
        target_id="map-3",
        reason="mapping_updated",
        source="mqtt_mapping",
        context={
            "mapping_id": "map-3",
            "source_topic": "plant/floor-1/rtu-1/telemetry",
            "mqtt_username": "broker-user",
            "source_metric_id": "y" * 1000,
        },
    )

    stored = audit_db.query(AuditEvent).one()
    assert stored.context["mapping_id"] == "map-3"
    assert "source_topic" not in stored.context
    assert "mqtt_username" not in stored.context
    assert len(stored.context["source_metric_id"]) == 256


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
