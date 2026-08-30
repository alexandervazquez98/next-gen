"""Strict-TDD tests for the stale-event review reminders surface (Issue #154).

PR1 backend test suite. Mirrors the pattern in
``tests/test_legacy_event_discriminator_audit.py`` (frozen dataclass
round-trip, Cypher inspection, allow-list redaction) and adds:

* Detection reason codes (``older_than_threshold`` /
  ``no_refresh_in_window`` / ``link_missing``).
* Schema-version constant + Markdown/JSON parity.
* ``from_mapping`` round-trip + invalid reason_code rejection.
* Bounded scan guards: limit clamps, Cypher contains no write clauses.
* No-mutation guarantee: Cypher contains only MATCH/OPTIONAL MATCH/
  WITH/RETURN/ORDER BY/LIMIT.
* Kill-switch off path returns empty; quick-action kill-switch off
  returns 503 BEFORE audit emission.
* Audit context shape: 3 allow-listed keys, no sensitive keys.
* Snooze handler ignores request-body ``snooze_until``;
  ``snooze_until == now + ttl_hours``.

Run with: ``cd backend && pytest tests/test_stale_event_reminders.py -v``
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures — Neo4j driver stub mirroring test_legacy_event_discriminator_audit
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeTransaction:
    def __init__(self, session):
        self.session = session

    def run(self, query, **parameters):
        return self.session.run(query, **parameters)


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.queries: list[tuple[str, dict]] = []
        self.execute_read_calls = 0
        self.read_transaction_calls = 0
        self.closed = False

    def run(self, query, **parameters):
        self.queries.append((query, parameters))
        return _FakeResult(self.rows)

    def execute_read(self, callback):
        self.execute_read_calls += 1
        return callback(_FakeTransaction(self))

    def read_transaction(self, callback):
        self.read_transaction_calls += 1
        return callback(_FakeTransaction(self))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True


class _FakeDriver:
    def __init__(self, rows):
        self.session_obj = _FakeSession(rows)
        self.session_kwargs: list[dict] = []

    def session(self, **kwargs):
        self.session_kwargs.append(kwargs)
        return self.session_obj


def _row(**overrides):
    base = {
        "event_id": "evt-1",
        "title": "SNMP no-response on core-rtr-01",
        "severity": "CRITICAL",
        "status": "OPEN",
        "ci_id": "ci-core-rtr-01",
        "ci_name": "Core Router 01",
        "metricdef_id": "md-snmp-uptime",
        "metricdef_name": "SNMP Uptime",
        "age_hours": 28.4,
        "last_seen": datetime(2026, 8, 29, 7, 36, tzinfo=UTC),
        "reason_code": "older_than_threshold",
        "refresh_status": "stale_refresh",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Scaffold / constant tests (WU1 RED → GREEN)
# ---------------------------------------------------------------------------


class TestScaffoldConstants:
    def test_recommendation_schema_version_constant(self):
        from services.stale_event_reminders import RECOMMENDATION_SCHEMA_VERSION

        assert RECOMMENDATION_SCHEMA_VERSION == "stale-event-reminder-recommendation.v1"

    def test_reason_code_enum_values_match_public_constants(self):
        from services.stale_event_reminders import (
            REASON_CODES,
            REASON_LINK_MISSING,
            REASON_NO_REFRESH_IN_WINDOW,
            REASON_OLDER_THAN_THRESHOLD,
            ReasonCode,
        )

        assert ReasonCode.OLDER_THAN_THRESHOLD.value == REASON_OLDER_THAN_THRESHOLD
        assert ReasonCode.NO_REFRESH_IN_WINDOW.value == REASON_NO_REFRESH_IN_WINDOW
        assert ReasonCode.LINK_MISSING.value == REASON_LINK_MISSING
        assert set(REASON_CODES) == {
            REASON_LINK_MISSING,
            REASON_NO_REFRESH_IN_WINDOW,
            REASON_OLDER_THAN_THRESHOLD,
        }

    def test_quick_actions_are_three_strings(self):
        from services.stale_event_reminders import QUICK_ACTIONS

        assert set(QUICK_ACTIONS) == {"dismiss", "snooze", "escalate"}


class TestFromMappingRoundTrip:
    def test_from_mapping_accepts_all_three_reason_codes(self):
        from services.stale_event_reminders import StaleEventRecommendation

        for code in ("older_than_threshold", "no_refresh_in_window", "link_missing"):
            row = _row(reason_code=code, refresh_status={
                "older_than_threshold": "stale_refresh",
                "no_refresh_in_window": "stale_refresh",
                "link_missing": "no_link",
            }[code])
            rec = StaleEventRecommendation.from_mapping(row)
            assert rec.reason_code == code

    def test_from_mapping_rejects_unknown_reason_code(self):
        from services.stale_event_reminders import StaleEventRecommendation

        with pytest.raises(ValueError):
            StaleEventRecommendation.from_mapping(_row(reason_code="bogus_reason"))

    def test_to_dict_round_trip_includes_all_contract_fields(self):
        from services.stale_event_reminders import StaleEventRecommendation

        # Use naive datetime to mirror Neo4j DateTime (no tzinfo on the wire
        # surface). The renderer accepts both naive and aware values.
        last_seen = datetime(2026, 8, 29, 7, 36)
        rec = StaleEventRecommendation.from_mapping(
            _row(
                reason_code="link_missing",
                refresh_status="no_link",
                ci_id=None,
                ci_name=None,
                metricdef_id=None,
                metricdef_name=None,
                last_seen=last_seen,
            )
        )
        rendered = rec.to_dict()
        for key in (
            "event_id",
            "title",
            "severity",
            "status",
            "ci_id",
            "ci_name",
            "metricdef_id",
            "metricdef_name",
            "age_hours",
            "last_seen",
            "refresh_status",
            "reason_code",
            "quick_actions",
        ):
            assert key in rendered
        assert rendered["reason_code"] == "link_missing"
        assert rendered["ci_id"] is None
        assert rendered["ci_name"] is None
        assert rendered["last_seen"].startswith("2026-08-29T07:36:00")
        assert rendered["quick_actions"] == ["dismiss", "snooze", "escalate"]

    def test_to_dict_is_json_serializable(self):
        from services.stale_event_reminders import StaleEventRecommendation

        rec = StaleEventRecommendation.from_mapping(_row())
        # JSON-serializable end-to-end (datetime -> ISO string).
        json.dumps(rec.to_dict())


# ---------------------------------------------------------------------------
# Detection Cypher tests (WU2 RED → GREEN)
# ---------------------------------------------------------------------------


class TestDetectionCypher:
    def test_cypher_uses_optional_match_for_missing_links(self):
        from services.stale_event_reminders import READ_ONLY_DETECTION_QUERY

        assert "OPTIONAL MATCH (ci:CI)-[:HAS_EVENT]->(e)" in READ_ONLY_DETECTION_QUERY
        assert "OPTIONAL MATCH (md:MetricDef)-[:TRIGGERED_BY]->(e)" in READ_ONLY_DETECTION_QUERY

    def test_cypher_filter_narrows_to_target_slice(self):
        from services.stale_event_reminders import READ_ONLY_DETECTION_QUERY

        assert "e.status IN $statuses" in READ_ONLY_DETECTION_QUERY
        assert "e.event_type = $event_type" in READ_ONLY_DETECTION_QUERY
        assert "e.failure_family = $failure_family" in READ_ONLY_DETECTION_QUERY

    def test_cypher_has_bounded_limit(self):
        from services.stale_event_reminders import READ_ONLY_DETECTION_QUERY

        assert re.search(r"\bLIMIT\s+\$limit\b", READ_ONLY_DETECTION_QUERY, re.IGNORECASE)

    def test_cypher_contains_no_write_clauses(self):
        """Static guarantee: no MERGE/SET/DELETE/CREATE/REMOVE/DETACH anywhere."""
        from services.stale_event_reminders import READ_ONLY_DETECTION_QUERY

        for forbidden in ("MERGE", "SET", "DELETE", "CREATE", "REMOVE", "DETACH"):
            assert (
                re.search(rf"\b{forbidden}\b", READ_ONLY_DETECTION_QUERY, re.IGNORECASE)
                is None
            ), f"forbidden write clause {forbidden!r} present in Cypher"

    def test_detection_query_uses_read_session(self):
        from services.stale_event_reminders import (
            READ_ONLY_DETECTION_QUERY,
            build_stale_event_recommendations,
        )

        driver = _FakeDriver([_row(reason_code="older_than_threshold",
                                    refresh_status="stale_refresh")])
        build_stale_event_recommendations(driver, age_hours=24, refresh_window_hours=6)

        query, params = driver.session_obj.queries[0]
        assert query.strip() == READ_ONLY_DETECTION_QUERY.strip()
        assert driver.session_obj.execute_read_calls == 1
        assert driver.session_obj.read_transaction_calls == 0

        try:
            from neo4j import READ_ACCESS
        except ImportError:
            expected_kwargs: list[dict] = [{}]
        else:
            expected_kwargs = [{"default_access_mode": READ_ACCESS}]
        assert driver.session_kwargs == expected_kwargs

    def test_limit_clamps_reject_out_of_range(self):
        from services.stale_event_reminders import (
            MAX_LIMIT,
            MIN_LIMIT,
            build_stale_event_recommendations,
        )

        driver = _FakeDriver([])
        with pytest.raises(ValueError):
            build_stale_event_recommendations(driver, age_hours=24, refresh_window_hours=6, limit=0)
        with pytest.raises(ValueError):
            build_stale_event_recommendations(
                driver, age_hours=24, refresh_window_hours=6, limit=MAX_LIMIT + 1
            )
        with pytest.raises(ValueError):
            build_stale_event_recommendations(
                driver, age_hours=24, refresh_window_hours=6, limit=MIN_LIMIT - 1
            )


class TestDetectionRowFiltering:
    def test_drop_rows_with_null_reason_code(self):
        """Rows where the CASE returns NULL are not stale and must be skipped."""
        from services.stale_event_reminders import build_stale_event_recommendations

        driver = _FakeDriver(
            [
                _row(reason_code=None, refresh_status="fresh"),  # not stale
                _row(
                    event_id="evt-stale",
                    reason_code="older_than_threshold",
                    refresh_status="stale_refresh",
                ),
            ]
        )
        response = build_stale_event_recommendations(
            driver, age_hours=24, refresh_window_hours=6
        )
        assert response.total == 1
        assert response.rows[0].event_id == "evt-stale"

    def test_classifier_covers_all_three_reason_codes(self):
        from services.stale_event_reminders import build_stale_event_recommendations

        driver = _FakeDriver(
            [
                _row(event_id="evt-age", reason_code="older_than_threshold",
                     refresh_status="stale_refresh"),
                _row(event_id="evt-stale-refresh", reason_code="no_refresh_in_window",
                     refresh_status="stale_refresh"),
                _row(event_id="evt-link", reason_code="link_missing",
                     refresh_status="no_link", ci_id=None, ci_name=None,
                     metricdef_id=None, metricdef_name=None),
            ]
        )
        response = build_stale_event_recommendations(
            driver, age_hours=24, refresh_window_hours=6
        )
        codes = {row.reason_code for row in response.rows}
        assert codes == {"older_than_threshold", "no_refresh_in_window", "link_missing"}


# ---------------------------------------------------------------------------
# Renderer parity tests
# ---------------------------------------------------------------------------


class TestRendererParity:
    def test_markdown_contains_each_row_and_count(self):
        from services.stale_event_reminders import (
            RECOMMENDATION_SCHEMA_VERSION,
            StaleEventRecommendation,
            StaleEventRecommendationsResponse,
            recommendation_to_markdown,
        )

        rec = StaleEventRecommendation.from_mapping(
            _row(event_id="evt-42", reason_code="link_missing",
                 refresh_status="no_link")
        )
        response = StaleEventRecommendationsResponse(
            schema_version=RECOMMENDATION_SCHEMA_VERSION,
            generated_at="2026-08-30T12:00:00",
            settings_snapshot={
                "age_hours": 24,
                "refresh_window_hours": 6,
                "limit": 100,
            },
            rows=[rec],
            total=1,
        )
        markdown = recommendation_to_markdown(response)
        assert "evt-42" in markdown
        assert "link_missing" in markdown
        assert "Total rows: 1" in markdown
        assert "Advisory only" in markdown
        assert "does not close events" in markdown.lower()
        for mutation_clause in ("MERGE", "DELETE", "SET", "CREATE"):
            assert mutation_clause not in markdown

    def test_empty_response_renders_no_stale_message(self):
        from services.stale_event_reminders import (
            RECOMMENDATION_SCHEMA_VERSION,
            StaleEventRecommendationsResponse,
            recommendation_to_markdown,
        )

        response = StaleEventRecommendationsResponse(
            schema_version=RECOMMENDATION_SCHEMA_VERSION,
            generated_at="2026-08-30T12:00:00",
            settings_snapshot={"age_hours": 24, "refresh_window_hours": 6, "limit": 100},
            rows=[],
            total=0,
        )
        markdown = recommendation_to_markdown(response)
        assert "No stale events detected." in markdown

    def test_json_and_markdown_agree_on_row_count(self):
        from services.stale_event_reminders import (
            RECOMMENDATION_SCHEMA_VERSION,
            StaleEventRecommendation,
            StaleEventRecommendationsResponse,
            recommendation_to_json_dict,
            recommendation_to_markdown,
        )

        rows = [
            StaleEventRecommendation.from_mapping(_row(event_id=f"evt-{i}"))
            for i in range(3)
        ]
        response = StaleEventRecommendationsResponse(
            schema_version=RECOMMENDATION_SCHEMA_VERSION,
            generated_at="2026-08-30T12:00:00",
            settings_snapshot={"age_hours": 24, "refresh_window_hours": 6, "limit": 100},
            rows=rows,
            total=3,
        )
        payload = recommendation_to_json_dict(response)
        markdown = recommendation_to_markdown(response)
        assert payload["total"] == 3
        assert "Total rows: 3" in markdown


# ---------------------------------------------------------------------------
# Settings tests (WU3 RED → GREEN)
# ---------------------------------------------------------------------------


class TestStaleEventReminderSettings:
    def test_defaults_match_spec(self):
        from config import StaleEventReminderSettings

        settings = StaleEventReminderSettings()
        assert settings.enabled is True
        assert settings.age_hours == 24
        assert settings.refresh_window_hours == 6
        assert settings.snooze_ttl_hours == 24

    def test_from_env_returns_defaults_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            from config import StaleEventReminderSettings

            settings = StaleEventReminderSettings.from_env()
        assert settings.enabled is True
        assert settings.age_hours == 24
        assert settings.refresh_window_hours == 6
        assert settings.snooze_ttl_hours == 24

    def test_from_env_reads_overrides(self):
        env = {
            "STALE_EVENT_REMINDER_ENABLED": "false",
            "STALE_EVENT_REMINDER_AGE_HOURS": "12",
            "STALE_EVENT_REMINDER_REFRESH_WINDOW_HOURS": "4",
            "STALE_EVENT_REMINDER_SNOOZE_TTL_HOURS": "8",
        }
        with patch.dict("os.environ", env, clear=True):
            from config import StaleEventReminderSettings

            settings = StaleEventReminderSettings.from_env()
        assert settings.enabled is False
        assert settings.age_hours == 12
        assert settings.refresh_window_hours == 4
        assert settings.snooze_ttl_hours == 8

    def test_invalid_values_fall_back_to_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "STALE_EVENT_REMINDER_ENABLED": "banana",
                "STALE_EVENT_REMINDER_AGE_HOURS": "not-a-number",
                "STALE_EVENT_REMINDER_REFRESH_WINDOW_HOURS": "negative",
                "STALE_EVENT_REMINDER_SNOOZE_TTL_HOURS": "0",
            },
            clear=True,
        ):
            from config import StaleEventReminderSettings

            settings = StaleEventReminderSettings.from_env()
        # enabled falls back to safe default (True).
        assert settings.enabled is True
        assert settings.age_hours == 24
        assert settings.refresh_window_hours == 6
        # snooze_ttl_hours=0 is below the ge=1 floor → default.
        assert settings.snooze_ttl_hours == 24


# ---------------------------------------------------------------------------
# Router + audit emission tests (WU4 / WU5 RED → GREEN)
# ---------------------------------------------------------------------------


@pytest.fixture
def _disable_neo4j_driver():
    """Replace database.driver with a MagicMock so importing the router doesn't
    require a live Neo4j connection."""
    mock = MagicMock()
    with patch("routers.event_recommendations._neo4j_driver", mock):
        yield mock


class TestKillSwitchOff:
    def test_get_recommendations_returns_empty_when_disabled(self, _disable_neo4j_driver):
        from config import StaleEventReminderSettings

        settings = StaleEventReminderSettings(enabled=False)
        with patch(
            "routers.event_recommendations.get_stale_event_reminder_settings",
            return_value=settings,
        ):
            from fastapi.testclient import TestClient

            app_user = SimpleNamespace(
                username="viewer",
                role="OPERATOR",
                permissions=["EVENT_VIEW"],
                allowed_locations=[],
                allowed_ci_types=None,
                disabled=False,
            )

            from main import app
            from services.auth_service import get_current_active_user

            async def _override_user():
                return app_user

            app.dependency_overrides[get_current_active_user] = _override_user
            try:
                client = TestClient(app)
                response = client.get("/api/events/recommendations")
                assert response.status_code == 200
                body = response.json()
                assert body["rows"] == []
                assert body["total"] == 0
                assert body["settings"]["enabled"] is False
            finally:
                app.dependency_overrides.pop(get_current_active_user, None)

    def test_quick_action_returns_503_when_disabled_without_writing_audit(
        self, _disable_neo4j_driver
    ):
        from config import StaleEventReminderSettings

        settings = StaleEventReminderSettings(enabled=False)
        with patch(
            "routers.event_recommendations.get_stale_event_reminder_settings",
            return_value=settings,
        ):
            from fastapi.testclient import TestClient
            from main import app
            from models.audit_event import AuditEvent
            from models.user import User, UserPermission
            from postgres_db import Base, get_pg_db
            from services.auth_service import get_current_active_user
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from sqlalchemy.pool import StaticPool

            engine = create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            Base.metadata.create_all(bind=engine, tables=[AuditEvent.__table__])
            db = TestingSessionLocal()
            try:
                def _override_pg():
                    yield db

                def _override_user():
                    return User(
                        username="viewer",
                        role="OPERATOR",
                        permissions=[UserPermission.EVENT_VIEW.value],
                        allowed_locations=[],
                        allowed_ci_types=None,
                        disabled=False,
                    )

                app.dependency_overrides[get_pg_db] = _override_pg
                app.dependency_overrides[get_current_active_user] = _override_user
                try:
                    client = TestClient(app)
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
                    # No audit rows should have been written.
                    assert db.query(AuditEvent).count() == 0
                finally:
                    app.dependency_overrides.pop(get_pg_db, None)
                    app.dependency_overrides.pop(get_current_active_user, None)
            finally:
                Base.metadata.drop_all(bind=engine, tables=[AuditEvent.__table__])
                db.close()
                engine.dispose()


class TestEventViewPermission:
    def test_get_returns_403_without_event_view(self, _disable_neo4j_driver):
        from fastapi.testclient import TestClient
        from main import app
        from models.audit_event import AuditEvent
        from models.user import User
        from postgres_db import Base, get_pg_db
        from services.auth_service import get_current_active_user
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine, tables=[AuditEvent.__table__])
        db = TestingSessionLocal()
        try:
            def _override_pg():
                yield db

            def _override_user():
                # No EVENT_VIEW.
                return User(
                    username="noscope",
                    role="VIEWER",
                    permissions=["CI_VIEW"],
                    allowed_locations=[],
                    allowed_ci_types=None,
                    disabled=False,
                )

            app.dependency_overrides[get_pg_db] = _override_pg
            app.dependency_overrides[get_current_active_user] = _override_user
            try:
                client = TestClient(app)
                response = client.get("/api/events/recommendations")
                assert response.status_code == 403
            finally:
                app.dependency_overrides.pop(get_pg_db, None)
                app.dependency_overrides.pop(get_current_active_user, None)
        finally:
            Base.metadata.drop_all(bind=engine, tables=[AuditEvent.__table__])
            db.close()
            engine.dispose()


class TestQuickActionAuditEmission:
    def test_dismiss_writes_audit_row_with_expected_event_type_and_context(
        self, _disable_neo4j_driver
    ):
        from fastapi.testclient import TestClient
        from main import app
        from models.audit_event import AuditEvent
        from models.user import User, UserPermission
        from postgres_db import Base, get_pg_db
        from services.auth_service import get_current_active_user
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine, tables=[AuditEvent.__table__])
        db = TestingSessionLocal()
        try:
            def _override_pg():
                yield db

            def _override_user():
                return User(
                    username="operator",
                    role="OPERATOR",
                    permissions=[UserPermission.EVENT_VIEW.value],
                    allowed_locations=[],
                    allowed_ci_types=None,
                    disabled=False,
                )

            app.dependency_overrides[get_pg_db] = _override_pg
            app.dependency_overrides[get_current_active_user] = _override_user
            try:
                client = TestClient(app)
                response = client.post(
                    "/api/events/recommendations/evt-1/dismiss",
                    json={"reason_code": "no_refresh_in_window"},
                )
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["event_type"] == "STALE_EVENT_REMINDER_DISMISS"
                assert body["context"]["event_id"] == "evt-1"
                assert body["context"]["reason_code"] == "no_refresh_in_window"

                row = db.query(AuditEvent).filter_by(
                    event_type="STALE_EVENT_REMINDER_DISMISS"
                ).one()
                assert row.target_type == "Event"
                assert row.target_id == "evt-1"
                assert row.context == {
                    "event_id": "evt-1",
                    "reason_code": "no_refresh_in_window",
                }
            finally:
                app.dependency_overrides.pop(get_pg_db, None)
                app.dependency_overrides.pop(get_current_active_user, None)
        finally:
            Base.metadata.drop_all(bind=engine, tables=[AuditEvent.__table__])
            db.close()
            engine.dispose()

    def test_snooze_writes_audit_row_with_snooze_until_from_settings(
        self, _disable_neo4j_driver
    ):
        from config import StaleEventReminderSettings
        from fastapi.testclient import TestClient
        from main import app
        from models.audit_event import AuditEvent
        from models.user import User, UserPermission
        from postgres_db import Base, get_pg_db
        from services.auth_service import get_current_active_user
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine, tables=[AuditEvent.__table__])
        db = TestingSessionLocal()
        try:
            def _override_pg():
                yield db

            def _override_user():
                return User(
                    username="operator",
                    role="OPERATOR",
                    permissions=[UserPermission.EVENT_VIEW.value],
                    allowed_locations=[],
                    allowed_ci_types=None,
                    disabled=False,
                )

            app.dependency_overrides[get_pg_db] = _override_pg
            app.dependency_overrides[get_current_active_user] = _override_user
            with patch(
                "routers.event_recommendations.get_stale_event_reminder_settings",
                return_value=StaleEventReminderSettings(
                    enabled=True, snooze_ttl_hours=24
                ),
            ):
                try:
                    client = TestClient(app)
                    # Even when the body tries to inject snooze_until, the
                    # server uses settings.snooze_ttl_hours (threat: snooze-TTL bypass).
                    response = client.post(
                        "/api/events/recommendations/evt-1/snooze",
                        json={
                            "reason_code": "older_than_threshold",
                            "snooze_until": "2099-01-01T00:00:00Z",
                        },
                    )
                    assert response.status_code == 200, response.text
                    body = response.json()
                    assert body["event_type"] == "STALE_EVENT_REMINDER_SNOOZE"
                    snooze_until = body["context"]["snooze_until"]
                    # Roughly 24h from now (allow slack for slow tests).
                    parsed = datetime.fromisoformat(snooze_until.rstrip("Z"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    now = datetime.now(UTC)
                    delta_h = (parsed - now).total_seconds() / 3600.0
                    assert 23.0 < delta_h < 25.0, delta_h

                    row = db.query(AuditEvent).filter_by(
                        event_type="STALE_EVENT_REMINDER_SNOOZE"
                    ).one()
                    assert row.context["event_id"] == "evt-1"
                    assert row.context["reason_code"] == "older_than_threshold"
                    assert "snooze_until" in row.context
                    # The request-body snooze_until is NOT echoed back.
                    assert "2099-01-01" not in (row.context.get("snooze_until") or "")
                finally:
                    app.dependency_overrides.pop(get_pg_db, None)
                    app.dependency_overrides.pop(get_current_active_user, None)
        finally:
            Base.metadata.drop_all(bind=engine, tables=[AuditEvent.__table__])
            db.close()
            engine.dispose()

    def test_escalate_writes_audit_row(self, _disable_neo4j_driver):
        from fastapi.testclient import TestClient
        from main import app
        from models.audit_event import AuditEvent
        from models.user import User, UserPermission
        from postgres_db import Base, get_pg_db
        from services.auth_service import get_current_active_user
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine, tables=[AuditEvent.__table__])
        db = TestingSessionLocal()
        try:
            def _override_pg():
                yield db

            def _override_user():
                return User(
                    username="operator",
                    role="OPERATOR",
                    permissions=[UserPermission.EVENT_VIEW.value],
                    allowed_locations=[],
                    allowed_ci_types=None,
                    disabled=False,
                )

            app.dependency_overrides[get_pg_db] = _override_pg
            app.dependency_overrides[get_current_active_user] = _override_user
            try:
                client = TestClient(app)
                response = client.post(
                    "/api/events/recommendations/evt-1/escalate",
                    json={"reason_code": "link_missing"},
                )
                assert response.status_code == 200
                body = response.json()
                assert body["event_type"] == "STALE_EVENT_REMINDER_ESCALATE"
                row = db.query(AuditEvent).filter_by(
                    event_type="STALE_EVENT_REMINDER_ESCALATE"
                ).one()
                assert row.context == {
                    "event_id": "evt-1",
                    "reason_code": "link_missing",
                }
            finally:
                app.dependency_overrides.pop(get_pg_db, None)
                app.dependency_overrides.pop(get_current_active_user, None)
        finally:
            Base.metadata.drop_all(bind=engine, tables=[AuditEvent.__table__])
            db.close()
            engine.dispose()


class TestAuditContextAllowListRedaction:
    """Even if a caller tries to inject sensitive keys via context, the audit
    service ``sanitize_context`` should drop them (defense in depth)."""

    def test_sanitize_context_drops_unauthorized_keys(self):
        from services.audit_service import sanitize_context

        safe = sanitize_context(
            {
                "event_id": "evt-1",
                "reason_code": "older_than_threshold",
                "snooze_until": "2026-08-31T12:00:00Z",
                "authorization": "Bearer leaked-token",
                "cookie": "session=leaked",
                "token": "leaked",
                "body": "raw request body",
                # An unauthorized key that should never reach the audit row.
                "raw_payload": "leaked",
            }
        )
        assert safe == {
            "event_id": "evt-1",
            "reason_code": "older_than_threshold",
            "snooze_until": "2026-08-31T12:00:00Z",
        }

    def test_sanitize_context_returns_none_for_empty(self):
        from services.audit_service import sanitize_context

        assert sanitize_context(None) is None
        assert sanitize_context({}) is None


# ---------------------------------------------------------------------------
# Helper unit tests — pure-function coverage
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_compute_snooze_until_adds_ttl_hours(self):
        from routers.event_recommendations import _compute_snooze_until

        start = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
        snooze_until = _compute_snooze_until(start, ttl_hours=24)
        assert snooze_until - start == timedelta(hours=24)

    def test_build_quick_action_context_omits_none_keys(self):
        from routers.event_recommendations import _build_quick_action_context

        ctx = _build_quick_action_context(
            event_id="evt-1", reason_code=None, snooze_until=None
        )
        assert ctx == {"event_id": "evt-1"}

    def test_build_quick_action_context_for_snooze(self):
        from routers.event_recommendations import _build_quick_action_context

        snooze_until = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
        ctx = _build_quick_action_context(
            event_id="evt-1", reason_code="older_than_threshold", snooze_until=snooze_until
        )
        assert ctx == {
            "event_id": "evt-1",
            "reason_code": "older_than_threshold",
            "snooze_until": "2026-08-31T12:00:00Z",
        }

    def test_record_quick_action_rejects_unknown_event_type(self):
        from routers.event_recommendations import _record_quick_action

        with pytest.raises(ValueError):
            _record_quick_action(
                db=MagicMock(),
                request=None,
                actor=MagicMock(),
                event_type="NOT_ALLOWED",
                event_id="evt-1",
                reason_code=None,
                snooze_until=None,
            )
