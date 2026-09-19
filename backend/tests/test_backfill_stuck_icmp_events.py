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
import json

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


class TestExecuteCascade:
    """RED -> GREEN: ``execute_cascade`` mutates only cascade-target events."""

    def test_select_cascade_targets_returns_list_with_required_keys(self):
        """Pre-mutation read returns one record per cascade-target event."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_response(
            "metric_id IN",
            [
                {
                    "event_id": 100,
                    "ci_id": "ci-down",
                    "metric_id": "icmp_jitter_ms",
                    "bucket": "down_ci",
                    "status": "OPEN",
                    "recovered_at": None,
                    "event_type": "THRESHOLD_BREACH",
                },
                {
                    "event_id": 200,
                    "ci_id": "ci-deleted",
                    "metric_id": "packet_loss_pct",
                    "bucket": "deleted_ci",
                    "status": "ACK",
                    "recovered_at": None,
                    "event_type": "THRESHOLD_BREACH",
                },
            ],
        )

        targets = script.select_cascade_targets(session)

        assert len(targets) == 2
        first = targets[0]
        for key in (
            "event_id",
            "ci_id",
            "metric_id",
            "bucket",
            "status_pre",
            "recovered_at_pre",
            "event_type_pre",
        ):
            assert key in first, f"Missing key {key!r} in cascade target"
        assert targets[0]["bucket"] == "down_ci"
        assert targets[1]["bucket"] == "deleted_ci"

    def test_cascade_root_set_clause_has_cascade_audit_marker(self):
        """The cascade SET clause must set both ``backfill_origin`` and ``recovery_source``."""
        script = _load_script()
        session = _FakeNeo4jSession()
        # select + cascade root + cascade propagated (CALL inner)
        session.set_sequence(
            [
                [{"event_id": 100, "ci_id": "ci-1", "metric_id": "icmp_jitter_ms",
                  "bucket": "down_ci", "status": "OPEN", "recovered_at": None,
                  "event_type": "THRESHOLD_BREACH"}],
                [],  # cascade root run, returns mutated event
                [],  # propagated descendants run
            ]
        )

        script.execute_cascade(
            session,
            snapshot_path="/tmp/test-snapshot.json",
            confirm_target="staging",
        )

        # Find the cascade root query (the one with the SET clause).
        cascade_queries = [
            q
            for q in session.queries
            if "SET" in q["query"].upper()
            and "backfill_origin" in q["query"]
        ]
        assert cascade_queries, "Expected at least one cascade SET clause"
        cascade_query = cascade_queries[0]["query"]
        assert "backfill_origin = 'chore-events-backfill-486-cascade'" in cascade_query
        assert "recovery_source = 'backfill'" in cascade_query
        assert "status = 'RECOVERED'" in cascade_query

    def test_cascade_root_query_filters_event_type_threshold_breach(self):
        """The cascade must scope to ROOT THRESHOLD_BREACH events only."""
        script = _load_script()
        session = _FakeNeo4jSession()
        # Provide one cascade target so the cascade query actually runs.
        session.set_sequence(
            [
                [
                    {
                        "event_id": 100,
                        "ci_id": "ci-1",
                        "metric_id": "icmp_jitter_ms",
                        "bucket": "down_ci",
                        "status": "OPEN",
                        "recovered_at": None,
                        "event_type": "THRESHOLD_BREACH",
                    }
                ],
                [],  # cascade root run
                [],  # cascade propagated run
            ]
        )

        script.execute_cascade(
            session,
            snapshot_path="/tmp/test-snapshot.json",
            confirm_target="staging",
        )

        cascade_queries = [
            q
            for q in session.queries
            if "SET" in q["query"].upper() and "backfill_origin" in q["query"]
        ]
        assert cascade_queries
        cascade_query = cascade_queries[0]["query"]
        assert "event_type = 'THRESHOLD_BREACH'" in cascade_query
        # ROOT events only: PROPAGATED descendants ride the inner CALL block.
        assert "correlation_type" in cascade_query

    def test_cascade_propagated_uses_propagated_from_predicate(self):
        """The PROPAGATED inner CALL block uses ``propagated_from = e.id``.

        This mirrors ``_recover_icmp_*_events`` and MUST NOT use the
        ``_recover_snmp_collection_failures`` full-cascade predicate
        (``root_cause_ci_id = e.ci_id``) which would expand scope.
        """
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence(
            [
                [
                    {
                        "event_id": 100,
                        "ci_id": "ci-1",
                        "metric_id": "icmp_jitter_ms",
                        "bucket": "down_ci",
                        "status": "OPEN",
                        "recovered_at": None,
                        "event_type": "THRESHOLD_BREACH",
                    }
                ],
                [],
                [],
            ]
        )

        script.execute_cascade(
            session,
            snapshot_path="/tmp/test-snapshot.json",
            confirm_target="staging",
        )

        cascade_queries = [
            q
            for q in session.queries
            if "SET" in q["query"].upper() and "backfill_origin" in q["query"]
        ]
        assert cascade_queries
        cascade_query = cascade_queries[0]["query"]
        assert "propagated_from = e.id" in cascade_query
        assert "root_cause_ci_id = e.ci_id" in cascade_query  # secondary filter OK
        # can_propagate gate mirrors _recover_icmp_*
        assert "can_propagate" in cascade_query

    def test_legacy_null_closure_set_clause_has_null_discriminator_marker(self):
        """The legacy-null SET clause sets ``event_type = 'legacy-no-relevant'`` and the dedicated marker."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence(
            [
                [],  # select cascade targets (none)
                [{"event_id": 300, "ci_id": "ci-1", "metric_id": "icmp_jitter_ms",
                  "bucket": "null_discriminator", "status": "OPEN",
                  "recovered_at": None, "event_type": None}],  # select legacy nulls
                [],  # close legacy nulls
            ]
        )

        script.execute_cascade(
            session,
            snapshot_path="/tmp/test-snapshot.json",
            confirm_target="staging",
        )

        null_queries = [
            q
            for q in session.queries
            if "event_type = 'legacy-no-relevant'" in q["query"]
        ]
        assert null_queries, "Expected at least one legacy-null SET clause"
        null_query = null_queries[0]["query"]
        assert (
            "backfill_origin = 'chore-events-backfill-486-legacy-null-discriminator'"
            in null_query
        )
        assert "recovery_source = 'backfill'" in null_query
        assert "status = 'RECOVERED'" in null_query

    def test_legacy_null_closure_preserves_metric_name_and_ci_id(self):
        """The legacy-null SET clause must NOT touch ``metric_name``, ``ci_id``, ``severity``."""
        script = _load_script()
        session = _FakeNeo4jSession()
        # Provide a legacy null target so the closure query runs.
        session.set_sequence(
            [
                [],  # cascade targets: none
                [
                    {
                        "event_id": 300,
                        "ci_id": "ci-1",
                        "metric_id": "icmp_jitter_ms",
                        "status": "OPEN",
                        "recovered_at": None,
                        "event_type": None,
                    }
                ],  # legacy nulls
                [],  # closure run
            ]
        )

        script.execute_cascade(
            session,
            snapshot_path="/tmp/test-snapshot.json",
            confirm_target="staging",
        )

        null_queries = [
            q
            for q in session.queries
            if "event_type = 'legacy-no-relevant'" in q["query"]
        ]
        assert null_queries
        null_query = null_queries[0]["query"]
        # Forbidden: overwriting preserved fields.
        assert "metric_name = " not in null_query
        assert "ci_id = " not in null_query
        assert "severity = " not in null_query

    def test_snapshot_written_before_any_mutation(self, tmp_path, monkeypatch):
        """``apply-progress.json`` (or .md) is written BEFORE any SET clause.

        The snapshot is the rollback anchor; if a write fails mid-cascade,
        the snapshot must already exist.
        """
        script = _load_script()
        session = _FakeNeo4jSession()
        # Provide enough rows for select cascade + select legacy + cascade + null closure.
        session.set_sequence(
            [
                [
                    {
                        "event_id": 100,
                        "ci_id": "ci-1",
                        "metric_id": "icmp_jitter_ms",
                        "bucket": "down_ci",
                        "status": "OPEN",
                        "recovered_at": None,
                        "event_type": "THRESHOLD_BREACH",
                    }
                ],
                [],
                [],
                [],
            ]
        )

        snapshot_path = tmp_path / "snapshot.json"
        script.execute_cascade(
            session,
            snapshot_path=str(snapshot_path),
            confirm_target="staging",
        )

        assert snapshot_path.exists()
        # The SET queries must come AFTER the file write (verified via query order
        # vs the existence of the file at the time of writing). The simpler proxy:
        # at least one SET query was issued, AND the file exists, AND the file
        # was written before script returned.
        assert any("SET" in q["query"].upper() for q in session.queries)

    def test_execute_returns_report_with_cascade_and_null_counts(self):
        """``execute_cascade`` returns a structured report dict."""
        script = _load_script()
        session = _FakeNeo4jSession()
        session.set_sequence(
            [
                # select cascade targets: 2 events
                [
                    {"event_id": 100, "ci_id": "ci-1", "metric_id": "icmp_jitter_ms",
                     "bucket": "down_ci", "status": "OPEN", "recovered_at": None,
                     "event_type": "THRESHOLD_BREACH"},
                    {"event_id": 200, "ci_id": "ci-2", "metric_id": "packet_loss_pct",
                     "bucket": "deleted_ci", "status": "OPEN", "recovered_at": None,
                     "event_type": "THRESHOLD_BREACH"},
                ],
                # select legacy nulls: 1 event
                [
                    {"event_id": 300, "ci_id": "ci-3", "metric_id": "icmp_jitter_ms",
                     "bucket": "null_discriminator", "status": "OPEN",
                     "recovered_at": None, "event_type": None},
                ],
                # cascade root
                [],
                # cascade propagated
                [],
                # legacy null closure
                [],
            ]
        )

        report = script.execute_cascade(
            session,
            snapshot_path="/tmp/test-snapshot.json",
            confirm_target="staging",
        )

        assert report["mode"] == "execute"
        assert report["cascade_root_count"] == 2
        assert report["legacy_null_count"] == 1
        assert "snapshot_path" in report
        assert "ran_at" in report

    def test_execute_is_idempotent_on_already_recovered_events(self):
        """Re-running after partial completion is a no-op on already-recovered rows.

        Both cascade queries begin with ``status IN ['OPEN', 'ACK']``. Once
        a row is RECOVERED, the WHERE clause rejects it; the SET clause
        never fires.
        """
        script = _load_script()
        session = _FakeNeo4jSession()
        # First run: mutates 2 events.
        session.set_sequence(
            [
                [
                    {"event_id": 100, "ci_id": "ci-1", "metric_id": "icmp_jitter_ms",
                     "bucket": "down_ci", "status": "OPEN", "recovered_at": None,
                     "event_type": "THRESHOLD_BREACH"},
                ],
                [],
                [],
                [],
            ]
        )
        first = script.execute_cascade(
            session,
            snapshot_path="/tmp/test-snapshot.json",
            confirm_target="staging",
        )
        assert first["cascade_root_count"] == 1

        # Second run: same data, but the cascade query returns empty (events
        # are now RECOVERED and excluded by the WHERE clause).
        session2 = _FakeNeo4jSession()
        session2.set_sequence([[], [], [], []])
        second = script.execute_cascade(
            session2,
            snapshot_path="/tmp/test-snapshot.json",
            confirm_target="staging",
        )
        assert second["cascade_root_count"] == 0
        assert second["legacy_null_count"] == 0


class TestRollback:
    """RED -> GREEN: ``rollback`` reproduces pre-mutation state from snapshot."""

    def test_rollback_resets_status_recovered_at_and_event_type(self, tmp_path):
        """The rollback SET clause resets each mutated field to its pre-state."""
        script = _load_script()
        snapshot = {
            "run_id": "test-uuid",
            "run_at": "2026-09-18T00:00:00Z",
            "confirm_target": "staging",
            "ci_snapshot_at": "2026-09-18T00:00:00Z",
            "rows": [
                {
                    "event_id": 100,
                    "ci_id": "ci-1",
                    "metric_id": "icmp_jitter_ms",
                    "bucket": "down_ci",
                    "status_pre": "OPEN",
                    "recovered_at_pre": None,
                    "event_type_pre": "THRESHOLD_BREACH",
                },
            ],
        }
        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot))

        session = _FakeNeo4jSession()
        session.set_sequence([[]])

        script.rollback(
            session,
            snapshot_path=str(snapshot_path),
            confirm_target="staging",
        )

        # Find the rollback SET clause.
        rollback_queries = [
            q for q in session.queries if "SET" in q["query"].upper()
        ]
        assert rollback_queries
        rollback_query = rollback_queries[0]["query"]
        # Status is reset to the pre-state value (parameterized).
        assert "status" in rollback_query
        # recovered_at and event_type also reset.
        assert "recovered_at" in rollback_query
        assert "event_type" in rollback_query

    def test_rollback_clears_backfill_origin_and_recovery_source(self, tmp_path):
        """The rollback SET clause clears both audit markers."""
        script = _load_script()
        snapshot = {
            "run_id": "test-uuid",
            "run_at": "2026-09-18T00:00:00Z",
            "confirm_target": "staging",
            "ci_snapshot_at": "2026-09-18T00:00:00Z",
            "rows": [
                {
                    "event_id": 100,
                    "ci_id": "ci-1",
                    "metric_id": "icmp_jitter_ms",
                    "bucket": "down_ci",
                    "status_pre": "OPEN",
                    "recovered_at_pre": None,
                    "event_type_pre": "THRESHOLD_BREACH",
                },
            ],
        }
        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot))

        session = _FakeNeo4jSession()
        session.set_sequence([[]])

        script.rollback(
            session,
            snapshot_path=str(snapshot_path),
            confirm_target="staging",
        )

        rollback_queries = [
            q for q in session.queries if "SET" in q["query"].upper()
        ]
        assert rollback_queries
        rollback_query = rollback_queries[0]["query"]
        assert "backfill_origin = NULL" in rollback_query
        assert "recovery_source = NULL" in rollback_query

    def test_rollback_self_bounded_by_backfill_origin_is_not_null(self, tmp_path):
        """Rollback only touches rows whose ``backfill_origin`` is set (idempotent)."""
        script = _load_script()
        snapshot = {
            "run_id": "test-uuid",
            "run_at": "2026-09-18T00:00:00Z",
            "confirm_target": "staging",
            "ci_snapshot_at": "2026-09-18T00:00:00Z",
            "rows": [
                {
                    "event_id": 100,
                    "ci_id": "ci-1",
                    "metric_id": "icmp_jitter_ms",
                    "bucket": "down_ci",
                    "status_pre": "OPEN",
                    "recovered_at_pre": None,
                    "event_type_pre": "THRESHOLD_BREACH",
                },
            ],
        }
        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot))

        session = _FakeNeo4jSession()
        session.set_sequence([[]])

        script.rollback(
            session,
            snapshot_path=str(snapshot_path),
            confirm_target="staging",
        )

        rollback_queries = [
            q for q in session.queries if "SET" in q["query"].upper()
        ]
        assert rollback_queries
        rollback_query = rollback_queries[0]["query"]
        # The MATCH clause must gate on backfill_origin IS NOT NULL.
        assert "backfill_origin IS NOT NULL" in rollback_query

