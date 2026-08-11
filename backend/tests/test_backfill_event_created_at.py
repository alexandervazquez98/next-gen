"""Strict-TDD tests for ``backend/scripts/backfill_event_created_at.py``.

PR #1 of fix-423: one-shot idempotent backfill for ``Event`` rows whose
``created_at`` is NULL. 70%+ of production rows have NULL ``created_at`` (pre-#279
legacy); the streaming pruner's cursor pagination cannot survive them. The
backfill fills them in bounded batches before the auto-prune scheduler ships in
PR #2.

Tests are intentionally split into two halves:

* ``TestBackfillEventCreatedAt`` — drives the helper function with a fake Neo4j
  session and asserts: dry-run reports candidates only, live-run mutates
  candidates, re-run is idempotent, the batch loop exits on a 0-row probe, and
  the COALESCE fallback includes ``datetime()`` for rows with no other
  timestamp.
* ``TestBackfillScriptHelp`` — verifies the CLI surface (argparse help must be
  importable without a real Neo4j, must advertise the live-evidence Cypher, and
  must reject invalid arguments).
"""
from __future__ import annotations

import contextlib
import io
from unittest.mock import MagicMock

import pytest


class _FakeRecord(dict):
    """A Neo4j record that supports both ``record["k"]`` and ``record.get("k")``."""


class _FakeNeo4jResult:
    """Minimal Neo4j Result mock supporting ``single()`` and ``__iter__``."""

    def __init__(self, records):
        self._records = [_FakeRecord(r) if isinstance(r, dict) else r for r in records]

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None


class _FakeNeo4jSession:
    """Captures every ``run(query, **params)`` and dispatches canned responses."""

    def __init__(self):
        self.queries: list[dict] = []
        # canned payloads keyed by substring of query (case-insensitive)
        self._responses: dict[str, list] = {}
        self._sequence: list[list] = []  # successive UPDATE batches

    def set_response(self, query_contains: str, records: list):
        self._responses[query_contains.lower()] = list(records)

    def set_sequence(self, batches: list[list]):
        self._sequence = [list(b) for b in batches]

    def run(self, query, **params):
        self.queries.append({"query": query, "params": params})
        query_lower = query.lower()
        if self._sequence:
            batch = self._sequence.pop(0) if self._sequence else []
            return _FakeNeo4jResult(batch)
        for needle, records in self._responses.items():
            if needle in query_lower:
                return _FakeNeo4jResult(records)
        return _FakeNeo4jResult([])


def _load_script():
    """Import the script module (red until implemented)."""
    from scripts import backfill_event_created_at as script

    return script


class TestBackfillEventCreatedAt:
    """RED -> GREEN -> TRIANGULATE: helper function contract."""

    def test_dry_run_reports_candidates_without_mutating(self, monkeypatch):
        script = _load_script()
        # Avoid real sleeps even when dry_run is False later in the suite.
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        session = _FakeNeo4jSession()
        # The dry-run COUNT query returns 1000 NULL-bearing candidates.
        session.set_response("count(e)", [{"candidate_count": 1000}])

        report = script.backfill_event_created_at(
            session, batch_size=500, sleep_seconds=0, dry_run=True
        )

        assert report["dry_run"] is True
        assert report["candidates"] == 1000
        assert report["updated"] == 0
        # Dry-run MUST NOT issue a SET clause.
        mutating_queries = [
            q for q in session.queries if "SET" in q["query"].upper() and "MATCH" in q["query"].upper()
        ]
        assert mutating_queries == [], (
            f"Dry-run must not mutate; got SET-bearing queries: "
            f"{[q['query'] for q in mutating_queries]!r}"
        )

    def test_live_run_mutates_candidates_and_returns_count(self, monkeypatch):
        script = _load_script()
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        session = _FakeNeo4jSession()
        # 1st UPDATE returns 500 IDs, 2nd UPDATE returns 0 (terminates loop).
        session.set_sequence(
            [
                [{"updated_id": f"evt-{i}"} for i in range(500)],
                [],
            ]
        )

        report = script.backfill_event_created_at(
            session, batch_size=500, sleep_seconds=0, dry_run=False
        )

        assert report["dry_run"] is False
        assert report["updated"] == 500
        assert report["candidates"] == 500  # last batch hit 0; loop ran twice
        update_queries = [
            q for q in session.queries if "SET" in q["query"].upper() and "LIMIT" in q["query"].upper()
        ]
        assert len(update_queries) == 2, (
            f"Expected two bounded UPDATEs (500 + 0); got {len(update_queries)}"
        )

    def test_re_run_after_completion_is_idempotent(self, monkeypatch):
        script = _load_script()
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        session = _FakeNeo4jSession()
        # First invocation: one batch of 50, then 0.
        session.set_sequence(
            [
                [{"updated_id": f"evt-{i}"} for i in range(50)],
                [],
            ]
        )

        first = script.backfill_event_created_at(
            session, batch_size=100, sleep_seconds=0, dry_run=False
        )
        assert first["updated"] == 50

        # Second invocation: now all NULL rows have been backfilled, so the
        # loop should probe once, get 0 rows, and exit cleanly.
        second_session = _FakeNeo4jSession()
        second_session.set_sequence([[]])

        second = script.backfill_event_created_at(
            second_session, batch_size=100, sleep_seconds=0, dry_run=False
        )
        assert second["updated"] == 0
        assert second["candidates"] == 0

    def test_batch_boundary_returns_zero_when_no_candidates(self, monkeypatch):
        script = _load_script()
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        session = _FakeNeo4jSession()
        # No candidates at all: a single UPDATE returns [].
        session.set_sequence([[]])

        report = script.backfill_event_created_at(
            session, batch_size=500, sleep_seconds=0, dry_run=False
        )

        assert report["updated"] == 0
        assert report["candidates"] == 0
        # Exactly one UPDATE was issued (the 0-row probe that terminates the loop).
        update_queries = [
            q for q in session.queries if "SET" in q["query"].upper() and "LIMIT" in q["query"].upper()
        ]
        assert len(update_queries) == 1

    def test_update_uses_coalesce_fallback_to_datetime(self, monkeypatch):
        script = _load_script()
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)

        session = _FakeNeo4jSession()
        session.set_sequence([[]])

        script.backfill_event_created_at(
            session, batch_size=100, sleep_seconds=0, dry_run=False
        )

        update_queries = [
            q for q in session.queries if "SET" in q["query"].upper() and "LIMIT" in q["query"].upper()
        ]
        assert update_queries, "expected at least one bounded UPDATE"
        rendered = update_queries[0]["query"].upper()
        # Every backfill row must derive its timestamp from one of the existing
        # fields, falling back to ``datetime()`` when none are set.
        assert "COALESCE(" in rendered, (
            "Backfill SET must use COALESCE so re-runs preserve enrichment. "
            f"Got SQL: {rendered!r}"
        )
        for fallback in ("RECOVERED_AT", "LAST_SEEN", "CLOSED_AT", "DATETIME()"):
            assert fallback in rendered, (
                f"COALESCE fallback chain missing {fallback!r}. "
                f"Got SQL: {rendered!r}"
            )

    def test_invalid_batch_size_rejected(self):
        script = _load_script()
        with pytest.raises(ValueError, match="batch_size must be positive"):
            script.backfill_event_created_at(
                MagicMock(), batch_size=0, sleep_seconds=0
            )

    def test_invalid_sleep_seconds_rejected(self):
        script = _load_script()
        with pytest.raises(ValueError, match="sleep_seconds must be non-negative"):
            script.backfill_event_created_at(
                MagicMock(), batch_size=100, sleep_seconds=-0.1
            )


class TestBackfillScriptHelp:
    """The CLI surface must be usable without a live Neo4j connection."""

    EVIDENCE_CYPHER = (
        "MATCH (e:Event) WHERE e.created_at IS NULL RETURN count(e) AS candidate_count"
    )

    def _capture_help(self, script):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), pytest.raises(SystemExit) as exc_info:
            script.main(["--help"])
        assert exc_info.value.code == 0
        return buf.getvalue()

    def test_help_advertises_live_evidence_cypher(self, monkeypatch):
        script = _load_script()
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)
        help_text = self._capture_help(script)
        assert self.EVIDENCE_CYPHER in help_text, (
            "Backfill --help must include the live-evidence Cypher so operators "
            "can copy/paste it for before/after validation."
        )

    def test_help_advertises_batch_and_sleep_flags(self, monkeypatch):
        script = _load_script()
        monkeypatch.setattr(script.time, "sleep", lambda *_a, **_k: None)
        help_text = self._capture_help(script)
        for flag in ("--batch-size", "--sleep-seconds", "--dry-run"):
            assert flag in help_text, f"--help missing required flag {flag!r}"
