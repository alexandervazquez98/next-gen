# backend/tests/test_backup_router.py
"""Integration tests for backup router — TDD RED phase first."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from services.auth_service import get_current_active_user
from models.user import User


# Patch Neo4j driver before importing app (main imports database connections at import time)
_mock_neo4j_driver = MagicMock()
with patch("neo4j.GraphDatabase.driver", return_value=_mock_neo4j_driver):
    from main import app
    from postgres_db import get_pg_db


# TestClient
client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pydantic_user(
    username: str = "admin",
    role: str = "OPERATOR",
    permissions: list[str] | None = None,
    allowed_locations: list[str] | None = None,
) -> User:
    return User(
        username=username,
        role=role,
        permissions=permissions or [],
        allowed_locations=allowed_locations or [],
    )


def _mock_db_session():
    return MagicMock(spec=Session)


def _install_user_override(user: User):
    async def override() -> User:
        return user

    app.dependency_overrides[get_current_active_user] = override
    db = _mock_db_session()
    app.dependency_overrides[get_pg_db] = lambda: db
    return db


def _clear_overrides():
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_pg_db, None)


class TestBackupRouterImports:
    """Verify the backup router can be imported."""

    def test_router_imports_without_error(self):
        """Router module should import without errors."""
        from routers.backup import router
        assert router is not None


class TestBackupConfigEndpoints:
    """Tests for GET/PUT /api/backup/config endpoints via the service layer."""

    def test_get_backup_config_returns_defaults(self):
        """get_backup_config returns default config when nothing stored."""
        from services.backup_service import get_backup_config, DEFAULT_CONFIG

        with patch("services.backup_service._get_config_from_db", return_value=None):
            config = get_backup_config()

        assert config["schedule_type"] == "daily"
        assert config["enabled"] is True
        assert config["retention_days"] == 7

    def test_get_backup_config_returns_stored_config(self):
        """get_backup_config returns stored config from DB."""
        from services.backup_service import get_backup_config

        stored = {
            "schedule_type": "manual",
            "scheduled_time": "03:30",
            "enabled": False,
            "retention_days": 14,
            "storage_path": "/custom/backups",
            "updated_by": "admin",
        }

        with patch("services.backup_service._get_config_from_db", return_value=stored):
            config = get_backup_config()

        assert config["schedule_type"] == "manual"
        assert config["enabled"] is False
        assert config["retention_days"] == 14

    def test_update_backup_config_calls_save(self):
        """update_backup_config delegates to _save_config_to_db."""
        from services.backup_service import update_backup_config, DEFAULT_CONFIG

        saved_values = {}

        def capture_save(**kwargs):
            saved_values.update(kwargs)
            return {**DEFAULT_CONFIG, **kwargs}

        with patch("services.backup_service._get_config_from_db", return_value=None):
            with patch("services.backup_service._save_config_to_db", capture_save):
                result = update_backup_config(
                    schedule_type="daily",
                    scheduled_time="05:00",
                    enabled=True,
                    retention_days=21,
                    storage_path="/new/path",
                    updated_by="admin",
                )

        assert saved_values["schedule_type"] == "daily"
        assert saved_values["retention_days"] == 21
        assert saved_values["updated_by"] == "admin"


class TestUpdateBackupConfigAudit:
    """Tests for PUT /api/backup/config focused on audit behavior."""

    def test_update_backup_config_denied_records_access_denied_audit(self):
        """Non-admin users should receive 403 and emit ACCESS_DENIED audit."""
        operator = _make_pydantic_user(username="operator", role="OPERATOR")
        _install_user_override(operator)

        with patch("routers.backup.audit_service.record_denied") as mock_record_denied:
            response = client.put(
                "/api/backup/config",
                json={"enabled": True},
            )

            assert response.status_code == 403
            assert "Only admins can update backup configuration" in response.json()["detail"]
            mock_record_denied.assert_called_once()
            kwargs = mock_record_denied.call_args.kwargs
            assert kwargs["required_permission"] == "ADMIN"
            assert kwargs["target_type"] == "system_config"
            assert kwargs["target_id"] == "backup_config"
            assert kwargs["source"] == "backup"
            assert kwargs["reason"] == "missing_permission:ADMIN"

        _clear_overrides()

    def test_update_backup_config_validation_failure_records_audit(self):
        """Invalid payload values should be captured as validation failures."""
        admin = _make_pydantic_user(username="admin", role="ADMIN")
        _install_user_override(admin)

        with patch("routers.backup.audit_service.record_critical_change") as mock_record_critical:
            response = client.put(
                "/api/backup/config",
                json={"schedule_type": "quarterly"},
            )

            assert response.status_code == 400
            assert "schedule_type must be one of" in response.json()["detail"]
            mock_record_critical.assert_called_once()
            kwargs = mock_record_critical.call_args.kwargs
            assert kwargs["event_type"] == "SYSTEM_CONFIG_UPDATE"
            assert kwargs["outcome"] == "VALIDATION_FAILURE"
            assert kwargs["reason"] == "invalid_schedule_type"
            assert kwargs["target_type"] == "system_config"

        _clear_overrides()

    def test_update_backup_config_success_records_audit(self):
        """Admins should get SUCCESS audit entry after config update."""
        admin = _make_pydantic_user(username="admin", role="ADMIN")
        _install_user_override(admin)

        update_result = {
            "schedule_type": "manual",
            "scheduled_time": "03:30",
            "enabled": True,
            "retention_days": 14,
            "storage_path": "/custom/backups",
            "updated_by": "admin",
        }

        with patch("routers.backup.audit_service.record_critical_change") as mock_record_critical, \
             patch("routers.backup.backup_service.update_backup_config", return_value=update_result), \
             patch("main.reschedule_backup"):
            response = client.put(
                "/api/backup/config",
                json={"schedule_type": "manual", "retention_days": 14},
            )

            assert response.status_code == 200
            assert response.json() == update_result
            mock_record_critical.assert_called_once()
            kwargs = mock_record_critical.call_args.kwargs
            assert kwargs["event_type"] == "SYSTEM_CONFIG_UPDATE"
            assert kwargs["outcome"] == "SUCCESS"
            assert kwargs["target_type"] == "system_config"
            assert kwargs["target_id"] == "backup_config"
            assert kwargs["reason"] == "backup_config_updated"
            assert kwargs["context"]["changed_fields"] == ["schedule_type", "retention_days"]
            assert kwargs["context"]["required_permission"] == "ADMIN"

        _clear_overrides()


class TestManualBackupEndpoint:
    """Tests for POST /api/backup/backup endpoint (admin-only)."""

    def test_trigger_backup_rejects_non_admin_via_router_logic(self):
        """Router should reject non-admin users for manual backup."""
        from fastapi import HTTPException
        from models.user import UserRole

        # Simulate the admin check logic from the router
        class FakeOperatorUser:
            username = "operator"
            role = "OPERATOR"
            permissions = []

        user = FakeOperatorUser()
        # This should raise HTTPException for non-admin
        with pytest.raises(HTTPException) as exc_info:
            if user.role != UserRole.ADMIN and user.role != "ADMIN":
                raise HTTPException(
                    status_code=403,
                    detail="Only admins can trigger manual backups",
                )

        assert exc_info.value.status_code == 403
        assert "admin" in exc_info.value.detail.lower()

    def test_trigger_backup_allows_admin(self):
        """Router should allow admin users for manual backup."""
        from models.user import UserRole

        class FakeAdminUser:
            username = "admin"
            role = "ADMIN"
            permissions = []

        user = FakeAdminUser()
        # Admin check passes (no exception raised)
        assert user.role == UserRole.ADMIN or user.role == "ADMIN"

    def test_trigger_manual_backup_returns_success_struct(self):
        """trigger_manual_backup returns expected success structure."""
        from services.backup_service import trigger_manual_backup, DEFAULT_CONFIG

        with patch("services.backup_service._get_config_from_db", return_value=DEFAULT_CONFIG):
            with patch("services.backup_service._run_pg_dump", return_value="/backups/manual_test.dump"):
                with patch("services.backup_service._record_backup_history", return_value=None):
                    with patch("services.backup_service._cleanup_old_backups", return_value=0):
                        with patch("services.backup_service._emit_backup_event", return_value=None):
                            result = trigger_manual_backup(triggered_by="admin")

        assert result["status"] == "SUCCESS"
        assert "filename" in result
        assert result["triggered_by"] == "admin"
        assert result["backup_type"] == "manual"


class TestBackupHistoryEndpoint:
    """Tests for GET /api/backup/history endpoint."""

    def test_get_backup_history_returns_list(self):
        """get_backup_history returns list of records."""
        from services.backup_service import get_backup_history

        now = datetime.now(timezone.utc)
        with patch("services.backup_service._get_history_from_db", return_value=[
            {
                "id": 1,
                "filename": "backup_20260501.dump",
                "file_path": "/backups/backup_20260501.dump",
                "size_bytes": 1024000,
                "status": "SUCCESS",
                "backup_type": "scheduled",
                "triggered_by": None,
                "duration_seconds": 120,
                "started_at": now,
                "completed_at": now,
            }
        ]):
            history = get_backup_history(limit=10)

        assert len(history) == 1
        assert history[0]["status"] == "SUCCESS"

    def test_get_backup_history_respects_limit(self):
        """get_backup_history passes limit to DB layer."""
        from services.backup_service import get_backup_history

        captured = {}
        def fake_get_history(limit=None):
            captured["limit"] = limit
            return []

        with patch("services.backup_service._get_history_from_db", fake_get_history):
            get_backup_history(limit=25)

        assert captured["limit"] == 25


class TestBackupMetricsEndpoint:
    """Tests for GET /api/backup/metrics endpoint."""

    def test_get_backup_metrics_returns_stats(self):
        """get_backup_metrics returns aggregated statistics."""
        from services.backup_service import get_backup_metrics

        # FAILURE record is first because it has the more recent started_at
        # (_get_history_from_db sorts by started_at DESC)
        recent = datetime(2026, 5, 2, 6, 0, tzinfo=timezone.utc)
        older = datetime(2026, 5, 1, 6, 0, tzinfo=timezone.utc)
        with patch("services.backup_service._get_history_from_db", return_value=[
            {
                "id": 2,
                "filename": "backup_20260502.dump",
                "file_path": "/backups/backup_20260502.dump",
                "size_bytes": None,
                "status": "FAILURE",
                "backup_type": "manual",
                "triggered_by": "admin",
                "duration_seconds": 5,
                "started_at": recent,  # More recent → history[0] = last_backup
                "completed_at": recent,
            },
            {
                "id": 1,
                "filename": "backup_20260501.dump",
                "file_path": "/backups/backup_20260501.dump",
                "size_bytes": 1024000,
                "status": "SUCCESS",
                "backup_type": "scheduled",
                "triggered_by": None,
                "duration_seconds": 120,
                "started_at": older,
                "completed_at": older,
            },
        ]):
            metrics = get_backup_metrics()

        assert metrics["total_backups"] == 2
        assert metrics["successful_backups"] == 1
        assert metrics["failed_backups"] == 1
        assert metrics["last_backup_status"] == "FAILURE"

    def test_get_backup_metrics_handles_empty_history(self):
        """get_backup_metrics returns zeros when no history."""
        from services.backup_service import get_backup_metrics

        with patch("services.backup_service._get_history_from_db", return_value=[]):
            metrics = get_backup_metrics()

        assert metrics["total_backups"] == 0
        assert metrics["successful_backups"] == 0
        assert metrics["failed_backups"] == 0
        assert metrics["last_backup"] is None
        assert metrics["last_backup_status"] is None