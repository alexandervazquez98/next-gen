# backend/tests/test_backup_service.py
"""Unit tests for backup_service — TDD RED phase first."""

from __future__ import annotations

import importlib
import sys
import types
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from services.backup_service import DEFAULT_CONFIG


def _load_backup_service_module():
    """Load backup_service fresh, stubbing heavy dependencies."""
    # Remove any cached version
    sys.modules.pop("services.backup_service", None)

    # Stub APScheduler
    apscheduler_stub = types.ModuleType("apscheduler")
    apscheduler_stub.scheduler = MagicMock()
    sys.modules["apscheduler"] = apscheduler_stub
    sys.modules["apscheduler.scheduler"] = apscheduler_stub.scheduler

    # Stub subprocess for pg_dump calls
    subprocess_stub = types.ModuleType("backup_subprocess")
    sys.modules["backup_subprocess"] = subprocess_stub

    return importlib.import_module("services.backup_service")


class TestBackupServiceImports:
    """Verify module structure and public API."""

    def test_module_imports_without_error(self):
        """The module should import without errors."""
        backup_service = _load_backup_service_module()
        assert backup_service is not None

    def test_exposes_public_functions(self):
        """Service should expose the expected public API."""
        backup_service = _load_backup_service_module()
        expected = {
            "get_backup_config",
            "update_backup_config",
            "trigger_manual_backup",
            "get_backup_history",
            "get_backup_metrics",
            "_run_pg_dump",
            "_cleanup_old_backups",
        }
        for name in expected:
            assert hasattr(backup_service, name), f"Missing: {name}"


class TestBackupConfigOperations:
    """Tests for backup configuration CRUD via the service layer."""

    def test_get_backup_config_returns_default_when_empty(self, mock_neo4j_session):
        """get_backup_config returns sensible defaults when no config exists."""
        backup_service = _load_backup_service_module()

        # Patch the DB layer to return empty (no config row)
        with patch.object(backup_service, "_get_config_from_db", return_value=None):
            config = backup_service.get_backup_config()

        assert config["schedule_type"] == "daily"
        assert config["scheduled_time"] == "06:00"
        assert config["enabled"] is True
        assert config["retention_days"] == 7
        assert config["storage_path"] == "/backups"

    def test_get_backup_config_returns_stored_values(self, mock_neo4j_session):
        """get_backup_config returns stored config from DB."""
        backup_service = _load_backup_service_module()
        stored = {
            "schedule_type": "daily",
            "scheduled_time": "03:30",
            "enabled": False,
            "retention_days": 14,
            "storage_path": "/backups/custom",
            "updated_by": "admin",
        }

        with patch.object(backup_service, "_get_config_from_db", return_value=stored):
            config = backup_service.get_backup_config()

        assert config["schedule_type"] == "daily"
        assert config["scheduled_time"] == "03:30"
        assert config["enabled"] is False
        assert config["retention_days"] == 14
        assert config["storage_path"] == "/backups/custom"

    def test_get_backup_config_normalizes_unmounted_stored_path(self, mock_neo4j_session):
        """Stored paths outside /backups fall back to persisted storage."""
        backup_service = _load_backup_service_module()
        stored = {
            "schedule_type": "daily",
            "scheduled_time": "03:30",
            "enabled": False,
            "retention_days": 14,
            "storage_path": "/custom/backups",
            "updated_by": "admin",
        }

        with patch.object(backup_service, "_get_config_from_db", return_value=stored):
            config = backup_service.get_backup_config()

        assert config["storage_path"] == "/backups"

    def test_get_backup_config_allows_subpath_under_backups(self, mock_neo4j_session):
        """Subpaths under /backups remain inside the persisted mount."""
        backup_service = _load_backup_service_module()
        stored = {
            "schedule_type": "daily",
            "scheduled_time": "03:30",
            "enabled": False,
            "retention_days": 14,
            "storage_path": "/backups/team-a",
            "updated_by": "admin",
        }

        with patch.object(backup_service, "_get_config_from_db", return_value=stored):
            config = backup_service.get_backup_config()

        assert config["storage_path"] == "/backups/team-a"

    def test_update_backup_config_saves_to_db(self, mock_neo4j_session):
        """update_backup_config persists the new configuration."""
        backup_service = _load_backup_service_module()

        saved_config = {}
        # Patch both the read (to avoid DB) and write (to capture)
        with patch.object(backup_service, "_get_config_from_db", return_value=None):  # noqa: SIM117
            with patch.object(backup_service, "_save_config_to_db", saved_config.update):
                backup_service.update_backup_config(
                    schedule_type="manual",
                    scheduled_time="04:00",
                    enabled=True,
                    retention_days=30,
                    storage_path="/mnt/backups",
                    updated_by="admin",
                )

        assert saved_config["schedule_type"] == "manual"
        assert saved_config["scheduled_time"] == "04:00"
        assert saved_config["retention_days"] == 30
        assert saved_config["storage_path"] == "/backups"
        assert saved_config["updated_by"] == "admin"

    def test_update_backup_config_returns_updated_config(self, mock_neo4j_session):
        """update_backup_config returns the updated config."""
        backup_service = _load_backup_service_module()

        expected_result = {
            "schedule_type": "daily",
            "scheduled_time": "02:00",
            "enabled": True,
            "retention_days": 5,
            "storage_path": "/backups/fast",
            "updated_by": "admin",
        }

        with patch.object(backup_service, "_get_config_from_db", return_value=None):  # noqa: SIM117
            with patch.object(backup_service, "_save_config_to_db", return_value=expected_result):
                result = backup_service.update_backup_config(
                    schedule_type="daily",
                    scheduled_time="02:00",
                    enabled=True,
                    retention_days=5,
                    storage_path="/backups/fast",
                    updated_by="admin",
                )

        assert result["schedule_type"] == "daily"
        assert result["scheduled_time"] == "02:00"
        assert result["enabled"] is True
        assert result["retention_days"] == 5


class TestManualBackup:
    """Tests for manually-triggered backups."""

    def test_trigger_manual_backup_returns_success_result(self, mock_neo4j_session):
        """trigger_manual_backup returns a success dict on success."""
        backup_service = _load_backup_service_module()

        with (
            patch.object(backup_service, "_get_config_from_db", return_value=DEFAULT_CONFIG),
            patch.object(
                backup_service, "_run_pg_dump", return_value="/backups/manual_20260502_120000.dump"
            ),
            patch.object(backup_service, "_record_backup_history", return_value=None),
            patch.object(backup_service, "_cleanup_old_backups", return_value=0),
            patch.object(backup_service, "_emit_backup_event", return_value=None),
        ):
            result = backup_service.trigger_manual_backup(triggered_by="admin")

        assert result["status"] == "SUCCESS"
        assert "filename" in result
        assert result["triggered_by"] == "admin"
        assert result["backup_type"] == "manual"

    def test_trigger_manual_backup_records_failure(self, mock_neo4j_session):
        """trigger_manual_backup returns FAILURE status when pg_dump fails."""
        backup_service = _load_backup_service_module()

        with (
            patch.object(backup_service, "_get_config_from_db", return_value=DEFAULT_CONFIG),
            patch.object(
                backup_service,
                "_run_pg_dump",
                side_effect=RuntimeError("pg_dump failed: connection refused"),
            ),
            patch.object(backup_service, "_record_backup_history", return_value=None),
            patch.object(backup_service, "_emit_backup_event", return_value=None) as mock_event,
        ):
            result = backup_service.trigger_manual_backup(triggered_by="admin")

        assert result["status"] == "FAILURE"
        assert "pg_dump failed" in result["error_message"]
        # Should emit BACKUP_FAILURE event
        assert mock_event.called


class TestBackupHistory:
    """Tests for backup history retrieval."""

    def test_get_backup_history_returns_list(self, mock_neo4j_session):
        """get_backup_history returns a list of history records."""
        backup_service = _load_backup_service_module()
        now = datetime.now(UTC)

        stored_records = [
            {
                "id": 1,
                "filename": "backup_20260501_060000.dump",
                "file_path": "/backups/backup_20260501_060000.dump",
                "size_bytes": 1024000,
                "status": "SUCCESS",
                "backup_type": "scheduled",
                "triggered_by": None,
                "duration_seconds": 120,
                "started_at": now,
                "completed_at": now,
            },
            {
                "id": 2,
                "filename": "backup_20260502_060000.dump",
                "file_path": "/backups/backup_20260502_060000.dump",
                "size_bytes": 1050000,
                "status": "SUCCESS",
                "backup_type": "manual",
                "triggered_by": "admin",
                "duration_seconds": 130,
                "started_at": now,
                "completed_at": now,
            },
        ]

        with patch.object(backup_service, "_get_history_from_db", return_value=stored_records):
            history = backup_service.get_backup_history()

        assert len(history) == 2
        assert history[0]["status"] == "SUCCESS"
        assert history[1]["backup_type"] == "manual"
        assert history[1]["triggered_by"] == "admin"

    def test_get_backup_history_respects_limit(self, mock_neo4j_session):
        """get_backup_history accepts a limit parameter."""
        backup_service = _load_backup_service_module()

        captured_limit = {}

        def fake_get_history(limit=None):
            captured_limit["value"] = limit
            return []

        with patch.object(backup_service, "_get_history_from_db", fake_get_history):
            backup_service.get_backup_history(limit=5)

        assert captured_limit["value"] == 5


class TestBackupMetrics:
    """Tests for backup metrics aggregation."""

    def test_get_backup_metrics_returns_stats(self, mock_neo4j_session):
        """get_backup_metrics aggregates statistics from history."""
        backup_service = _load_backup_service_module()
        now = datetime.now(UTC)

        stored_records = [
            {
                "id": 1,
                "filename": "backup_success.dump",
                "file_path": "/backups/backup_success.dump",
                "size_bytes": 1000000,
                "status": "SUCCESS",
                "backup_type": "scheduled",
                "triggered_by": None,
                "duration_seconds": 120,
                "started_at": now,
                "completed_at": now,
            },
        ]

        with patch.object(backup_service, "_get_history_from_db", return_value=stored_records):
            metrics = backup_service.get_backup_metrics()

        assert "total_backups" in metrics
        assert "successful_backups" in metrics
        assert "failed_backups" in metrics
        assert "last_backup" in metrics
        assert "last_backup_status" in metrics
        assert metrics["successful_backups"] == 1
        assert metrics["last_backup_status"] == "SUCCESS"


class TestPgDump:
    """Tests for the pg_dump subprocess call."""

    def test_run_pg_dump_returns_file_path_on_success(self):
        """_run_pg_dump returns a path string when pg_dump succeeds."""
        backup_service = _load_backup_service_module()

        with patch("os.makedirs") as mock_makedirs, patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("os.path.getsize", return_value=2048000):
                result = backup_service._run_pg_dump(
                    output_path="/backups",
                    db_name="nexgen_auth",
                )

        mock_makedirs.assert_called_once_with("/backups", exist_ok=True)

        # Normalize path for cross-platform comparison
        result_normalized = result.replace("\\", "/")
        assert "/backups/backup_" in result_normalized
        assert result.endswith(".dump")
        # Verify pg_dump preserves custom format and output file behavior.
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "pg_dump"
        assert "-Fc" in call_args
        assert "-f" in call_args
        assert any(str(arg).replace("\\", "/").startswith("/backups/backup_") for arg in call_args)
        assert call_args[-2:] == ["-d", "nexgen_auth"]

    def test_run_pg_dump_uses_postgres_env_vars(self):
        """_run_pg_dump passes Compose-compatible env vars as pg_dump args."""
        backup_service = _load_backup_service_module()

        with (
            patch.dict(
                "os.environ",
                {
                    "POSTGRES_USER": "custom_user",
                    "POSTGRES_PASSWORD": "custom_password",
                    "POSTGRES_HOST": "custom_postgres",
                    "POSTGRES_PORT": "15432",
                    "POSTGRES_DB": "custom_db",
                },
            ),
            patch("os.makedirs"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            backup_service._run_pg_dump(output_path="/backups")

        call_args = mock_run.call_args[0][0]
        assert "postgresql://" not in " ".join(str(a) for a in call_args)
        assert call_args[4:6] == ["-h", "custom_postgres"]
        assert call_args[6:8] == ["-p", "15432"]
        assert call_args[8:10] == ["-U", "custom_user"]
        assert call_args[10:12] == ["-d", "custom_db"]

    def test_run_pg_dump_keeps_special_character_password_out_of_args(self):
        """_run_pg_dump sends passwords through PGPASSWORD, not argv."""
        backup_service = _load_backup_service_module()
        password = "p@ss:word/with?special&chars='\"$"

        with (
            patch.dict(
                "os.environ",
                {
                    "POSTGRES_USER": "custom_user",
                    "POSTGRES_PASSWORD": password,
                    "POSTGRES_HOST": "custom_postgres",
                    "POSTGRES_PORT": "15432",
                    "POSTGRES_DB": "custom_db",
                },
            ),
            patch("os.makedirs"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            backup_service._run_pg_dump(output_path="/backups")

        call_args = mock_run.call_args[0][0]
        call_kwargs = mock_run.call_args.kwargs
        assert password not in " ".join(str(a) for a in call_args)
        assert call_kwargs["env"]["PGPASSWORD"] == password

    def test_run_pg_dump_raises_on_failure(self):
        """_run_pg_dump raises RuntimeError when pg_dump fails."""
        backup_service = _load_backup_service_module()

        with patch("os.makedirs"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr=b"connection refused")
            with pytest.raises(RuntimeError, match="pg_dump failed"):
                backup_service._run_pg_dump(output_path="/backups", db_name="nexgen_auth")


class TestCleanupOldBackups:
    """Tests for old backup file cleanup."""

    def test_cleanup_old_backups_deletes_files_older_than_retention(self):
        """_cleanup_old_backups removes files past retention_days threshold."""
        backup_service = _load_backup_service_module()

        deleted_files = []

        def fake_remove(path):
            deleted_files.append(path)

        with patch("os.path.exists", return_value=True):  # noqa: SIM117
            with patch("os.listdir") as mock_listdir:
                with patch("os.path.getmtime") as mock_getmtime:
                    with patch("os.remove", fake_remove):
                        # Simulate two files: one old (deleted), one recent (kept)
                        import time

                        now = time.time()
                        mock_listdir.return_value = ["old.dump", "recent.dump"]
                        mock_getmtime.side_effect = lambda p: (
                            now - (8 * 86400) if "old" in p else now - (1 * 86400)
                        )

                        removed_count = backup_service._cleanup_old_backups(
                            backup_dir="/backups",
                            retention_days=7,
                        )

        assert removed_count == 1
        assert any("old.dump" in f for f in deleted_files)
        assert not any("recent.dump" in f for f in deleted_files)

    def test_cleanup_old_backups_handles_missing_dir(self):
        """_cleanup_old_backups returns 0 when backup dir doesn't exist."""
        backup_service = _load_backup_service_module()

        with patch("os.path.exists", return_value=False):
            count = backup_service._cleanup_old_backups("/nonexistent", retention_days=7)

        assert count == 0
