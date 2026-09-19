"""Strict-TDD tests for ``backend/scripts/backfill_stuck_icmp_events.py``.

PR #2 of chore-events-backfill-stuck-icmp-recovery-486: dry-run inventory
mode for the one-shot backfill script. The dry-run reports the four
residual-bucket counts (proper discriminators, NULL discriminators,
on-down-CI, on-deleted-CI) without mutating any Event row.

Tests assert:

* ``inventory_buckets(session)`` returns four bucket counts via four
  read-only Neo4j queries.
* ``dry_run(session)`` issues no SET clauses.
* ``dry_run(session)`` does not require ``--confirm-target`` (read-only,
  no target allowlist).
* The CI snapshot is captured once at run start (single query), not
  per-CI.

The CI snapshot test uses a single-sequence canned response that matches
both the inventory query and the snapshot query in deterministic order.
"""

from __future__ import annotations

import contextlib
import io

import pytest

# Metric IDs mirror those in ``backend/polling/icmp_measurements.py``.
ICMP_JITTER_METRIC_ID = "icmp_jitter_ms"
ICMP_PACKET_LOSS_METRIC_ID = "packet_loss_pct"


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
    """Captures every ``run(query, **params)`` and dispatches canned responses.

    Mirrors the precedent ``backend/tests/test_backfill_event_created_at.py``.
    """

    def __init__(self):
        self.queries: list[dict] = []
        self._responses: dict[str, list] = {}
        self._sequence: list[list] = []

    def set_response(self, query_contains: str, records: list):
        self._responses[query_contains.lower()] = list(records)

    def set_sequence(self, batches: list[list]):
        self._sequence = [list(b) for b in batches]

    def run(self, query, **params):
        self.queries.append({"query": query, "params": params})
        if self._sequence:
            batch = self._sequence.pop(0) if self._sequence else []
            return _FakeNeo4jResult(batch)
        for needle, records in self._responses.items():
            if needle in query.lower():
                return _FakeNeo4jResult(records)
        return _FakeNeo4jResult([])


def _load_script():
    """Import the script module (red until implemented)."""
    from scripts import backfill_stuck_icmp_events as script

    return script


class TestInventoryBuckets:
    """RED -> GREEN: ``inventory_buckets(session)`` reports four bucket counts."""

    def test_returns_all_four_buckets_with_expected_keys(self):
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence(
            [
                [{"count": 42}],  # proper_discriminators
                [{"count": 153}],  # null_discriminators
                [{"count": 7}],  # down_ci
                [{"count": 3}],  # deleted_ci
            ]
        )

        buckets = script.inventory_buckets(session)

        assert set(buckets.keys()) == {
            "stuck_with_proper_discriminators",
            "stuck_null_discriminators",
            "stuck_on_down_ci",
            "stuck_on_deleted_ci",
        }
        assert buckets["stuck_with_proper_discriminators"] == 42
        assert buckets["stuck_null_discriminators"] == 153
        assert buckets["stuck_on_down_ci"] == 7
        assert buckets["stuck_on_deleted_ci"] == 3

    def test_returns_zero_counts_when_no_residual_events(self):
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence([[{"count": 0}], [{"count": 0}], [{"count": 0}], [{"count": 0}]])

        buckets = script.inventory_buckets(session)

        assert buckets == {
            "stuck_with_proper_discriminators": 0,
            "stuck_null_discriminators": 0,
            "stuck_on_down_ci": 0,
            "stuck_on_deleted_ci": 0,
        }

    def test_issues_exactly_four_queries(self):
        """Inventory must not fan out: one query per bucket, no loops."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence(
            [
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
            ]
        )

        script.inventory_buckets(session)

        assert len(session.queries) == 4

    def test_proper_discriminators_query_filters_event_type_threshold_breach(self):
        """Bucket 1 query must scope to ``event_type='THRESHOLD_BREACH'`` and pass the ICMP metric IDs as a parameter."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence([[{"count": 0}], [{"count": 0}], [{"count": 0}], [{"count": 0}]])

        script.inventory_buckets(session)

        first_query = session.queries[0]["query"]
        first_params = session.queries[0]["params"]
        assert "event_type = 'THRESHOLD_BREACH'" in first_query
        # Parameterized: the ICMP metric IDs live in the params dict, not
        # inlined into the Cypher string (prevents injection, matches repo
        # convention).
        assert "icmp_metric_ids" in first_params
        assert ICMP_JITTER_METRIC_ID in first_params["icmp_metric_ids"]
        assert ICMP_PACKET_LOSS_METRIC_ID in first_params["icmp_metric_ids"]

    def test_null_discriminators_query_filters_is_null(self):
        """Bucket 2 query must scope to ``event_type IS NULL OR metric_id IS NULL``."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence([[{"count": 0}], [{"count": 0}], [{"count": 0}], [{"count": 0}]])

        script.inventory_buckets(session)

        second_query = session.queries[1]["query"]
        assert "event_type IS NULL" in second_query or "event_type is null" in second_query.lower()
        assert "metric_id IS NULL" in second_query or "metric_id is null" in second_query.lower()

    def test_down_ci_query_joins_latest_availability_sample(self):
        """Bucket 3 query must consult :HAS_AVAILABILITY_SAMPLE."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence([[{"count": 0}], [{"count": 0}], [{"count": 0}], [{"count": 0}]])

        script.inventory_buckets(session)

        third_query = session.queries[2]["query"]
        assert "HAS_AVAILABILITY_SAMPLE" in third_query.upper()

    def test_deleted_ci_query_checks_ci_existence(self):
        """Bucket 4 query must use NOT EXISTS to detect deleted CIs."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence([[{"count": 0}], [{"count": 0}], [{"count": 0}], [{"count": 0}]])

        script.inventory_buckets(session)

        fourth_query = session.queries[3]["query"]
        # Cypher keyword check; case-insensitive.
        assert "NOT EXISTS" in fourth_query.upper()


class TestDryRun:
    """RED -> GREEN: ``dry_run(session)`` is read-only and self-contained."""

    def test_dry_run_returns_inventory_plus_metadata(self):
        script = _load_script()
        session = _FakeNeo4jSession()
        # Snapshot first (1 query) + 4 inventory buckets.
        session.set_sequence(
            [
                [{"ci_id": "ci-1", "latest_value": 1.0}],  # capture_ci_snapshot
                [{"count": 10}],  # bucket 1
                [{"count": 5}],  # bucket 2
                [{"count": 2}],  # bucket 3
                [{"count": 1}],  # bucket 4
            ]
        )

        report = script.dry_run(session)

        assert "buckets" in report
        assert "ran_at" in report
        assert "ci_snapshot" in report
        assert report["buckets"]["stuck_with_proper_discriminators"] == 10
        assert report["buckets"]["stuck_null_discriminators"] == 5
        assert report["buckets"]["stuck_on_down_ci"] == 2
        assert report["buckets"]["stuck_on_deleted_ci"] == 1

    def test_dry_run_issues_no_set_clauses(self):
        """Strict invariant: dry-run must never mutate Event rows."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence(
            [
                [{"ci_id": "ci-1", "latest_value": 1.0}],  # snapshot
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
            ]
        )

        script.dry_run(session)

        mutating_queries = [
            q
            for q in session.queries
            if "SET" in q["query"].upper() and "MATCH" in q["query"].upper()
        ]
        assert mutating_queries == [], (
            f"Dry-run must not mutate; got SET-bearing queries: "
            f"{[q['query'] for q in mutating_queries]!r}"
        )

    def test_dry_run_issues_no_delete_clauses(self):
        """Strict invariant: dry-run must never delete Event rows."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence(
            [
                [{"ci_id": "ci-1", "latest_value": 1.0}],  # snapshot
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
            ]
        )

        script.dry_run(session)

        delete_queries = [q for q in session.queries if "DELETE" in q["query"].upper()]
        assert delete_queries == [], (
            f"Dry-run must not delete; got DELETE-bearing queries: "
            f"{[q['query'] for q in delete_queries]!r}"
        )

    def test_dry_run_works_without_confirm_target(self):
        """``--dry-run`` does not require ``--confirm-target`` (read-only)."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence(
            [
                [{"ci_id": "ci-1", "latest_value": 1.0}],  # snapshot
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
            ]
        )

        # No env allowlist, no target confirmation; dry-run must succeed.
        import os

        with contextlib.suppress(KeyError):
            os.environ.pop("BACKFILL_ALLOWED_TARGETS", None)

        report = script.dry_run(session)

        assert "buckets" in report

    def test_dry_run_cli_help_is_importable_without_neo4j(self, capsys):
        """The argparse surface must be testable without a live Neo4j.

        ``--help`` exercises the parser without touching the DB.
        """
        script = _load_script()
        buf = io.StringIO()
        with contextlib.suppress(SystemExit), contextlib.redirect_stdout(buf):
            script.build_parser().print_help()

        help_text = buf.getvalue()
        assert "--dry-run" in help_text
        assert "--output" in help_text

    def test_dry_run_flag_is_parsed_correctly(self):
        """``build_parser()`` must recognize ``--dry-run`` as a flag."""
        script = _load_script()
        args = script.build_parser().parse_args(["--dry-run", "--output", "/tmp/out.json"])
        assert args.dry_run is True
        assert args.output == "/tmp/out.json"

    def test_execute_flag_requires_confirm_target(self):
        """``--execute`` without ``--confirm-target`` must be rejected.

        PR #3 will own the actual cascade, but the safety gate belongs to
        the parser and must be visible in PR #2.
        """
        script = _load_script()
        # Set the env allowlist to enable the gate.
        import os

        os.environ["BACKFILL_ALLOWED_TARGETS"] = "staging,prod"
        try:
            with pytest.raises(SystemExit):
                script.build_parser().parse_args(["--execute"])
        finally:
            os.environ.pop("BACKFILL_ALLOWED_TARGETS", None)


class TestCISnapshot:
    """RED -> GREEN: CI availability snapshot is captured once, not per bucket.

    The cascade decision in PR #3 uses a frozen snapshot of CI availability
    captured at run start. PR #2's inventory must seed that snapshot via a
    single query (not 4× per CI).
    """

    def test_snapshot_helper_issues_single_query(self):
        script = _load_script()
        session = _FakeNeo4jSession()
        # Single query returns BOTH CIs in one batch (head(collect(s)) per CI).
        session.set_sequence(
            [
                [
                    {"ci_id": "ci-1", "latest_value": 0.0},
                    {"ci_id": "ci-2", "latest_value": 1.0},
                ],
            ]
        )

        snapshot = script.capture_ci_snapshot(session)

        # One query captured the entire CI availability state.
        assert len(session.queries) == 1
        assert "HAS_AVAILABILITY_SAMPLE" in session.queries[0]["query"].upper()
        # Snapshot returns a dict keyed by ci_id.
        assert snapshot == {"ci-1": 0.0, "ci-2": 1.0}

    def test_snapshot_returns_empty_dict_when_no_samples(self):
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence([[]])

        snapshot = script.capture_ci_snapshot(session)

        assert snapshot == {}

    def test_snapshot_is_called_exactly_once_per_dry_run(self, monkeypatch):
        """``dry_run`` must call ``capture_ci_snapshot`` exactly once.

        We monkeypatch ``capture_ci_snapshot`` to count invocations instead
        of inspecting query substrings — bucket 3 (``_QUERY_DOWN_CI``) also
        joins ``:HAS_AVAILABILITY_SAMPLE``, so a substring filter would
        over-count.
        """
        script = _load_script()
        session = _FakeNeo4jSession()
        # 1 snapshot (replaced by the spy, never consumed) + 4 inventory buckets.
        session.set_sequence(
            [
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
                [{"count": 0}],
            ]
        )

        call_count = 0

        def spy(session):
            nonlocal call_count
            call_count += 1
            return {"ci-1": 1.0}

        monkeypatch.setattr(script, "capture_ci_snapshot", spy)

        script.dry_run(session)

        assert call_count == 1, (
            f"Snapshot must be captured exactly once per dry_run; got " f"{call_count} calls"
        )
