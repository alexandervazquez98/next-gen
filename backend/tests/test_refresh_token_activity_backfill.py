"""Tests for the refresh-token activity backfill script (PR0 of #287).

The script (`backend/scripts/backfill_refresh_token_activity.py`) is the
deployment-time repair step for legacy `refresh_tokens.last_activity_at IS NULL`
rows. PR0 keeps this slice DB-only and avoids any auth behavior changes.

These tests are intentionally strict-TDD RED scaffolds: they import the
production helper that lands in Task 0.2, so they fail with ``ImportError``
until that helper is implemented.
"""

from __future__ import annotations

import contextlib
import io
from unittest.mock import MagicMock

import pytest


def _make_execute_mock(rowcounts):
    """Build a mock SQLAlchemy ``Session`` whose ``execute`` returns rowcounts.

    The helper records every (statement, params) call so tests can assert the
    bounded-batch UPDATE shape used by the backfill loop. ``rowcounts`` is the
    sequence of rowcounts returned in order; once exhausted the mock returns
    ``0`` so the loop can exit.
    """
    calls = []
    remaining = list(rowcounts)

    def fake_execute(stmt, *args, **kwargs):
        calls.append({"stmt": stmt, "params": args, "kwargs": kwargs})
        rowcount = remaining.pop(0) if remaining else 0
        result = MagicMock()
        result.rowcount = rowcount
        return result

    db = MagicMock()
    db.execute.side_effect = fake_execute
    db.commit = MagicMock()
    return db, calls


class TestBackfillRefreshTokenActivity:
    """RED scaffolds for the batched backfill helper."""

    def test_sets_last_activity_at_non_null_for_legacy_row(self, monkeypatch):
        # Import the helper from its final location so the test references
        # production code that does not exist yet (RED).
        from scripts import backfill_refresh_token_activity as script

        # Avoid real sleeps during the unit test run.
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        db, calls = _make_execute_mock([1, 0])

        updated = script.backfill_refresh_token_activity(
            db, batch_size=1000, sleep_seconds=0
        )

        assert updated == 1
        # First batch updated one row; loop probed again with rowcount=0 and
        # exited cleanly.
        assert len(calls) == 2

    def test_empty_batch_returns_zero_without_raising(self, monkeypatch):
        from scripts import backfill_refresh_token_activity as script

        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        db, calls = _make_execute_mock([0])

        updated = script.backfill_refresh_token_activity(
            db, batch_size=1000, sleep_seconds=0
        )

        assert updated == 0
        assert len(calls) == 1

    def test_update_uses_database_now_not_python_clock(self, monkeypatch):
        # Regression: the UPDATE must use the database NOW() so backfill time
        # comes from a single authoritative clock. Using `datetime.utcnow()`
        # from the application host introduces clock-skew risk between the
        # app server and the Postgres host.
        from scripts import backfill_refresh_token_activity as script

        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        db, calls = _make_execute_mock([0])

        script.backfill_refresh_token_activity(
            db, batch_size=1000, sleep_seconds=0
        )

        assert calls, "expected the backfill to call db.execute at least once"
        rendered_sql = str(calls[0]["stmt"]).upper()
        assert "NOW()" in rendered_sql, (
            "Backfill UPDATE must use DB NOW() (no clock skew). "
            f"Got SQL: {rendered_sql!r}"
        )
        assert "LIMIT" in rendered_sql, (
            "Backfill UPDATE must be bounded by batch_size LIMIT. "
            f"Got SQL: {rendered_sql!r}"
        )
        assert "LAST_ACTIVITY_AT" in rendered_sql, (
            "Backfill UPDATE must target last_activity_at. "
            f"Got SQL: {rendered_sql!r}"
        )


class TestBackfillScriptHelp:
    """The CLI help must advertise the live-evidence SQL operators run before/after."""

    EVIDENCE_SQL = (
        "SELECT count(*) FROM refresh_tokens WHERE last_activity_at IS NULL"
    )
    EVIDENCE_ROW_SQL = (
        "SELECT id, user_id, last_activity_at FROM refresh_tokens "
        "WHERE last_activity_at IS NULL"
    )

    def _capture_help(self, script):
        # argparse writes help to stdout and calls ``parser.exit(0)`` which
        # raises SystemExit; capture both so the test sees the help text.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with pytest.raises(SystemExit) as exc_info:
                script.main(["--help"])
        assert exc_info.value.code == 0
        return buf.getvalue()

    def test_help_documents_live_evidence_query(self, monkeypatch):
        from scripts import backfill_refresh_token_activity as script

        # The script must not actually try to open a database when --help is
        # requested; if it does we want the test to fail loudly.
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        help_text = self._capture_help(script)

        assert self.EVIDENCE_SQL in help_text, (
            "Backfill CLI --help must include the live-evidence SQL so "
            "operators can copy/paste it for before/after validation."
        )

    def test_help_documents_row_identification_query(self, monkeypatch):
        from scripts import backfill_refresh_token_activity as script

        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        help_text = self._capture_help(script)

        assert self.EVIDENCE_ROW_SQL in help_text, (
            "Backfill CLI --help must include a row-identification SQL so "
            "operators can capture at least one exercised row id for the PR body."
        )

    def test_help_works_without_postgres_db_import(self):
        # Regression: `python backend/scripts/backfill_refresh_token_activity.py --help`
        # must succeed even if `postgres_db` / `psycopg2` is not importable
        # on the host. The verify agent for PR0 caught this: the eager
        # `from models.refresh_token import RefreshToken` inside the script
        # pulled `models/__init__.py` which in turn loaded `postgres_db`,
        # which then tried to create a SQLAlchemy engine with the postgresql
        # dialect and crashed with `ModuleNotFoundError: psycopg2`.
        #
        # We exercise the failure in a clean subprocess so Python's import
        # cache cannot mask the bug the way in-process monkeypatch can.
        import os
        import subprocess
        import sys

        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        script_path = os.path.join(
            repo_root, "backend", "scripts", "backfill_refresh_token_activity.py"
        )

        result = subprocess.run(
            [sys.executable, script_path, "--help"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=15,
        )

        assert result.returncode == 0, (
            f"Script --help failed with code {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )
        assert self.EVIDENCE_SQL in result.stdout, (
            "--help output must include the live-evidence SQL for operators."
        )

    def test_invalid_batch_size_rejected(self):
        from scripts import backfill_refresh_token_activity as script

        with pytest.raises(ValueError, match="batch_size must be positive"):
            script.backfill_refresh_token_activity(
                MagicMock(), batch_size=0, sleep_seconds=0
            )

    def test_invalid_sleep_seconds_rejected(self):
        from scripts import backfill_refresh_token_activity as script

        with pytest.raises(ValueError, match="sleep_seconds must be non-negative"):
            script.backfill_refresh_token_activity(
                MagicMock(), batch_size=1000, sleep_seconds=-0.1
            )