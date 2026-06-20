"""Tests for the refresh-token activity backfill script (PR0 of #287).

The script (`backend/scripts/backfill_refresh_token_activity.py`) is the
deployment-time repair step for legacy `refresh_tokens.last_activity_at IS NULL`
rows. PR0 keeps this slice DB-only and avoids any auth behavior changes.

These tests are intentionally strict-TDD RED scaffolds: they import the
production helper that lands in Task 0.2, so they fail with ``ImportError``
until that helper is implemented.
"""

from __future__ import annotations

from unittest.mock import MagicMock


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