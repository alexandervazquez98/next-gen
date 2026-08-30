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


# ---------------------------------------------------------------------------
# Stale event reminder quick-action audit rows (Issue #154, audit-logging
# delta spec). The dedicated router lives in
# ``backend/routers/event_recommendations.py`` and emits rows via
# ``record_critical_change`` — these tests focus on the audit-logging
# contract: 3 event_type strings, allow-listed context keys, kill-switch
# 503 with no audit emission.
# ---------------------------------------------------------------------------


def _stale_reminder_user():
    return User(
        username="reminder-operator",
        role="OPERATOR",
        permissions=[UserPermission.EVENT_VIEW.value],
        allowed_locations=[],
        allowed_ci_types=None,
        disabled=False,
    )


def _mock_event_recommendations_driver():
    """Return a MagicMock stand-in for ``database.driver`` so importing the
    router module does not require a live Neo4j connection."""
    return MagicMock()


def test_stale_reminder_dismiss_audit_row_has_event_id_and_reason_code(audit_db):
    """Dismiss emits audit row with allow-listed keys (no sensitive keys)."""
    from routers import event_recommendations

    with patch(
        "routers.event_recommendations._neo4j_driver",
        _mock_event_recommendations_driver(),
    ):
        _set_current_user(_stale_reminder_user())

        response = client.post(
            "/api/events/recommendations/evt-1/dismiss",
            json={"reason_code": "older_than_threshold"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["event_type"] == "STALE_EVENT_REMINDER_DISMISS"
        # Context contains event_id + reason_code; no tokens / cookies / body.
        assert body["context"]["event_id"] == "evt-1"
        assert body["context"]["reason_code"] == "older_than_threshold"
        for forbidden in ("authorization", "cookie", "token", "body"):
            assert forbidden not in body["context"]

        # Audit row landed in Postgres with the right shape.
        row = (
            audit_db.query(AuditEvent)
            .filter_by(event_type="STALE_EVENT_REMINDER_DISMISS")
            .one()
        )
        assert row.target_type == "Event"
        assert row.target_id == "evt-1"
        assert row.context == {
            "event_id": "evt-1",
            "reason_code": "older_than_threshold",
        }


def test_stale_reminder_snooze_audit_row_records_snooze_until_only_from_settings(
    audit_db,
):
    """Snooze audit row records snooze_until computed from settings (not body)."""
    from config import StaleEventReminderSettings
    from routers import event_recommendations

    with patch(
        "routers.event_recommendations._neo4j_driver",
        _mock_event_recommendations_driver(),
    ), patch(
        "routers.event_recommendations.get_stale_event_reminder_settings",
        return_value=StaleEventReminderSettings(enabled=True, snooze_ttl_hours=24),
    ):
        _set_current_user(_stale_reminder_user())

        # Body tries to inject snooze_until — server must use settings.
        response = client.post(
            "/api/events/recommendations/evt-1/snooze",
            json={
                "reason_code": "no_refresh_in_window",
                "snooze_until": "2099-01-01T00:00:00Z",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["event_type"] == "STALE_EVENT_REMINDER_SNOOZE"
        # Snooze value is ~now + 24h, NOT the request-body 2099 timestamp.
        snooze_until = body["context"]["snooze_until"]
        assert "2099" not in snooze_until
        parsed = datetime.fromisoformat(snooze_until.rstrip("Z"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta_h = (parsed - datetime.now(timezone.utc)).total_seconds() / 3600.0
        assert 23.0 < delta_h < 25.0, delta_h

        row = (
            audit_db.query(AuditEvent)
            .filter_by(event_type="STALE_EVENT_REMINDER_SNOOZE")
            .one()
        )
        assert row.context["event_id"] == "evt-1"
        assert row.context["reason_code"] == "no_refresh_in_window"
        assert "snooze_until" in row.context


def test_stale_reminder_escalate_audit_row_has_event_id_and_reason_code(audit_db):
    """Escalate emits audit row with allow-listed keys (no sensitive keys)."""
    from routers import event_recommendations

    with patch(
        "routers.event_recommendations._neo4j_driver",
        _mock_event_recommendations_driver(),
    ):
        _set_current_user(_stale_reminder_user())

        response = client.post(
            "/api/events/recommendations/evt-1/escalate",
            json={"reason_code": "link_missing"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["event_type"] == "STALE_EVENT_REMINDER_ESCALATE"
        assert body["context"] == {
            "event_id": "evt-1",
            "reason_code": "link_missing",
        }
        for forbidden in ("authorization", "cookie", "token", "body"):
            assert forbidden not in body["context"]


def test_stale_reminder_quick_action_returns_503_when_kill_switch_off(audit_db):
    """Kill-switch off → 503 and no audit row written."""
    from config import StaleEventReminderSettings
    from routers import event_recommendations

    with patch(
        "routers.event_recommendations._neo4j_driver",
        _mock_event_recommendations_driver(),
    ), patch(
        "routers.event_recommendations.get_stale_event_reminder_settings",
        return_value=StaleEventReminderSettings(enabled=False),
    ):
        _set_current_user(_stale_reminder_user())

        # All three quick actions short-circuit BEFORE audit emission.
        for action in ("dismiss", "snooze", "escalate"):
            response = client.post(
                f"/api/events/recommendations/evt-1/{action}",
                json={"reason_code": "older_than_threshold"},
            )
            assert response.status_code == 503, action
            assert (
                "STALE_EVENT_REMINDER_ENABLED=false"
                in response.json().get("detail", "")
            )

        # No audit row should have been written.
        count = (
            audit_db.query(AuditEvent)
            .filter(
                AuditEvent.event_type.in_(
                    [
                        "STALE_EVENT_REMINDER_DISMISS",
                        "STALE_EVENT_REMINDER_SNOOZE",
                        "STALE_EVENT_REMINDER_ESCALATE",
                    ]
                )
            )
            .count()
        )
        assert count == 0


def test_stale_reminder_audit_allow_list_redacts_injected_sensitive_keys(audit_db):
    """Defense in depth: even if a caller slips sensitive keys into context,
    ``sanitize_context`` drops them before persistence."""
    from routers import event_recommendations
    from services.audit_service import sanitize_context

    raw = {
        "event_id": "evt-1",
        "reason_code": "older_than_threshold",
        "snooze_until": "2026-08-31T12:00:00Z",
        "authorization": "Bearer leaked",
        "cookie": "session=leaked",
        "token": "leaked",
        "body": "raw request body",
        "raw_payload": "leaked",
    }
    safe = sanitize_context(raw)
    assert safe == {
        "event_id": "evt-1",
        "reason_code": "older_than_threshold",
        "snooze_until": "2026-08-31T12:00:00Z",
    }
