"""Startup ordering and preflight policy tests for ITSM bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from services.itsm_bootstrap import (
    _BACKFILL_COMPATIBILITY_QUERY,
    _PRECHECK_DUPLICATE_CANONICAL_ID_QUERY,
    _PRECHECK_INVALID_IDENTITY_QUERY,
    ITSM_SERVICE_ID_POLICY,
    ItsmBootstrapPreflightError,
    _migration_file_path,
    run_service_catalog_startup_checks,
)


class TestItsmServiceCatalogBootstrapPolicy:
    """Startup policy should be explicit and fail fast before migration."""

    def _mock_driver(self, query_responses: list[list[dict[str, Any]]]) -> MagicMock:
        session = MagicMock()
        session.run.side_effect = query_responses
        driver = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__enter__.return_value = session
        session_ctx.__exit__.return_value = False
        driver.session.return_value = session_ctx
        return driver

    def test_preflight_uses_fail_fast_policy_and_blocks_conflicts(self):
        """When duplicates/legacy conflicts exist, startup must fail fast."""

        driver = self._mock_driver(
            [
                [],
                [{"canonical_id": "svc-alpha", "total": 2}],
                [{"canonical_id": "svc-missing", "service_id": None, "legacy_id": "svc-missing"}],
            ]
        )

        with pytest.raises(ItsmBootstrapPreflightError) as exc:
            run_service_catalog_startup_checks(driver=driver)

        message = str(exc.value).lower()
        assert ITSM_SERVICE_ID_POLICY in str(exc.value)
        assert "itsm catalog preflight failed" in message
        assert "svc-alpha" in message
        assert "svc-missing" in message

    def test_startup_sequence_runs_preflight_before_migration(self, monkeypatch):
        """Startup checks must verify data before executing migration statements."""

        statements = [
            "CREATE CONSTRAINT test_a IF NOT EXISTS FOR (s:ServiceCatalog) REQUIRE s.service_id IS UNIQUE",
            "CREATE INDEX test_b IF NOT EXISTS FOR (s:ServiceCatalog) ON (s.active)",
        ]
        monkeypatch.setattr(
            "services.itsm_bootstrap._load_service_catalog_migration_statements",
            lambda: statements,
        )

        session = MagicMock()
        session.run.side_effect = [
            [],
            [],
            [],
            [],
            [],
        ]
        driver = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__enter__.return_value = session
        session_ctx.__exit__.return_value = False
        driver.session.return_value = session_ctx

        run_service_catalog_startup_checks(driver=driver, apply_migration=True)

        calls = [str(call.args[0]) for call in session.run.call_args_list]
        assert _BACKFILL_COMPATIBILITY_QUERY.strip() in calls[0]
        assert _PRECHECK_DUPLICATE_CANONICAL_ID_QUERY.strip() in calls[1]
        assert _PRECHECK_INVALID_IDENTITY_QUERY.strip() in calls[2]
        assert calls[3] == statements[0]
        assert calls[4] == statements[1]


class TestItsmMainStartupOrdering:
    """Existing startup flow must call bootstrap checks before Postgres migrations."""

    def test_main_startup_event_calls_itsm_bootstrap_check_before_neo4j_schema_bootstrap(self):
        source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
        bootstrap_call_index = source.index("run_service_catalog_startup_checks")
        neo4j_schema_index = source.index("Base.metadata.create_all")
        assert bootstrap_call_index < neo4j_schema_index

        # Keep the intended fail-fast policy discoverable in code.
        assert "run_service_catalog_startup_checks" in source


def test_migration_file_documents_startup_conflict_policy():
    """Migration docs should keep startup policy consistent with runtime checks."""

    migration_path = _migration_file_path()
    assert migration_path.exists(), f"Migration file not found at {migration_path}."
    migration_text = migration_path.read_text(encoding="utf-8")
    assert "fail-fast" in migration_text.lower()
