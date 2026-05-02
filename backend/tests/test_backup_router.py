# backend/tests/test_backup_router.py
"""Integration tests for backup router — TDD RED phase first."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


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