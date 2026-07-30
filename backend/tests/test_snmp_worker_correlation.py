"""Tests for engines.snmp_worker correlation wiring (Tasks 2, 3, 4, 10).

Strict TDD: tests written FIRST, then implementation.

Covers:
- Task 2: ``_resolve_correlation`` helper (pure dict lookup, never raises).
- Task 3: ``poll_snmp`` cache-build wiring (ENABLE_TOPOLOGY_RCA kill-switch,
  cache built BEFORE the three refresh helpers, local to one cycle).
- Task 4: propagated rows enrich root-event affected-CI metadata instead of
  creating child operator events.
- Task 10: failure-fallback resilience (cache-build raises → events still
  created as ROOT, UNWIND...CREATE ran, warning logged).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from engines.snmp_worker import _resolve_correlation

# ---------------------------------------------------------------------------
# Task 2 — _resolve_correlation helper
# ---------------------------------------------------------------------------


def test_resolve_correlation_propagated_on_cache_hit():
    cache = {("ci-E", "cpu-load"): {"parent_event_id": "evt-A", "root_cause_ci_id": "ci-A"}}

    result = _resolve_correlation(cache, "ci-E", "cpu-load")

    assert result == {
        "correlation_type": "PROPAGATED",
        "propagated_from": "evt-A",
        "root_cause_ci_id": "ci-A",
    }


def test_resolve_correlation_root_on_cache_miss():
    result = _resolve_correlation({}, "ci-E", "cpu-load")

    assert result == {
        "correlation_type": "ROOT",
        "propagated_from": None,
        "root_cause_ci_id": "ci-E",
    }


@pytest.mark.parametrize("bad_cache", [None, "not-a-dict", 42, object()])
def test_resolve_correlation_never_raises_on_malformed_cache(bad_cache):
    """The hot CREATE path must stay exception-free — _resolve_correlation never raises."""
    result = _resolve_correlation(bad_cache, "ci-E", "cpu-load")  # type: ignore[arg-type]

    assert result["correlation_type"] == "ROOT"
    assert result["root_cause_ci_id"] == "ci-E"


def test_resolve_correlation_handles_missing_parent_event_id():
    """A cache entry without parent_event_id is treated as a miss → ROOT."""
    cache = {("ci-E", "cpu-load"): {"root_cause_ci_id": "ci-A"}}  # no parent_event_id

    result = _resolve_correlation(cache, "ci-E", "cpu-load")

    assert result["correlation_type"] == "ROOT"


def test_resolve_correlation_degrades_to_root_when_root_cause_ci_id_missing():
    """If root_cause_ci_id is missing, degrades to ROOT rather than writing an
    EVENT id into a CI-id field.

    Contract: root_cause_ci_id must NEVER be an event id. If a valid CI-level
    root cause cannot be resolved, the row must NOT be tagged PROPAGATED.
    """
    cache = {("ci-E", "cpu-load"): {"parent_event_id": "evt-A"}}  # no root_cause_ci_id

    result = _resolve_correlation(cache, "ci-E", "cpu-load")

    assert result["correlation_type"] == "ROOT"
    assert result["propagated_from"] is None
    assert result["root_cause_ci_id"] == "ci-E"


def test_resolve_correlation_uses_ci_metric_pair_key():
    """Two metrics on the same CI with different cache entries resolve independently."""
    cache = {
        ("ci-E", "cpu-load"): {"parent_event_id": "evt-A", "root_cause_ci_id": "ci-A"},
        ("ci-E", "mem-load"): {"parent_event_id": "evt-B", "root_cause_ci_id": "ci-B"},
    }

    cpu = _resolve_correlation(cache, "ci-E", "cpu-load")
    mem = _resolve_correlation(cache, "ci-E", "mem-load")

    assert cpu["propagated_from"] == "evt-A"
    assert mem["propagated_from"] == "evt-B"


# ---------------------------------------------------------------------------
# Task 4 — propagated rows enrich root metadata instead of creating child Events
# ---------------------------------------------------------------------------
# Each _refresh_* helper accepts an optional ``cache`` parameter (default empty
# dict for backward compatibility with pre-existing tests). A row whose
# (node_id, metric_id) hits the cache is routed to root-event affected-CI
# enrichment; cache misses remain ROOT rows and use the existing Event
# create/update path.


def test_snmp_collection_failure_propagates_when_parent_open():
    """Propagated collection-failure rows update parent ROOT metadata, no child rows."""
    from engines.snmp_worker import _refresh_snmp_collection_failures

    session = MagicMock()
    session.run = MagicMock(return_value=MagicMock())
    cache = {("ci-E", "cpu-load"): {"parent_event_id": "evt-A", "root_cause_ci_id": "ci-A"}}

    _refresh_snmp_collection_failures(
        session,
        [
            {
                "node_id": "ci-E",
                "metric_id": "cpu-load",
                "severity": "WARNING",
                "message": "Metric Collection Failed: cpu-load",
                "event_type": "COLLECTION_FAILURE",
                "failure_family": "SNMP_NO_RESPONSE",
                "source_protocol": "SNMP",
            }
        ],
        cache=cache,
    )

    calls = [c for c in session.run.call_args_list if "UNWIND" in c.args[0]]
    assert calls, "expected an UNWIND call"
    query = calls[0].args[0]
    rows_param = calls[0].kwargs["propagated_rows"]
    assert rows_param[0]["correlation_type"] == "PROPAGATED"
    assert rows_param[0]["propagated_from"] == "evt-A"
    assert rows_param[0]["root_cause_ci_id"] == "ci-A"
    assert "CREATE (created" not in query
    assert "row.node_id IN root.affected_ci_ids" in query
    assert "row.affected_ci_comment IN root.comments" in query
    assert "root.last_seen = datetime()" not in query


def test_snmp_collection_failure_root_when_no_parent():
    """No upstream OPEN → ROOT fallback, root_cause_ci_id = self."""
    from engines.snmp_worker import _refresh_snmp_collection_failures

    session = MagicMock()
    session.run = MagicMock(return_value=MagicMock())

    _refresh_snmp_collection_failures(
        session,
        [
            {
                "node_id": "ci-E",
                "metric_id": "cpu-load",
                "severity": "WARNING",
                "message": "Metric Collection Failed: cpu-load",
                "event_type": "COLLECTION_FAILURE",
                "failure_family": "SNMP_NO_RESPONSE",
                "source_protocol": "SNMP",
            }
        ],
        cache={},
    )

    calls = [c for c in session.run.call_args_list if "UNWIND" in c.args[0]]
    rows_param = calls[0].kwargs["failures"]
    assert rows_param[0]["correlation_type"] == "ROOT"
    assert rows_param[0]["propagated_from"] is None
    assert rows_param[0]["root_cause_ci_id"] == "ci-E"


def test_icmp_availability_propagates_when_parent_open():
    """Availability propagation updates parent ROOT metadata, not child rows."""
    from engines.snmp_worker import _refresh_icmp_availability_events

    session = MagicMock()
    session.run = MagicMock(return_value=MagicMock())
    cache = {("ci-E", "PING-CHECK"): {"parent_event_id": "evt-A", "root_cause_ci_id": "ci-A"}}

    _refresh_icmp_availability_events(
        session,
        [
            {
                "node_id": "ci-E",
                "metric_id": "PING-CHECK",
                "protocol": "ICMP",
                "source_protocol": "ICMP",
                "availability_source": "PING",
                "event_type": "AVAILABILITY",
                "severity": "CRITICAL",
                "message": "Service/Host Down: PING-CHECK",
                "value": 0.0,
            }
        ],
        cache=cache,
    )

    calls = [c for c in session.run.call_args_list if "UNWIND" in c.args[0]]
    query = calls[0].args[0]
    rows_param = calls[0].kwargs["propagated_rows"]
    assert rows_param[0]["correlation_type"] == "PROPAGATED"
    assert rows_param[0]["propagated_from"] == "evt-A"
    assert rows_param[0]["root_cause_ci_id"] == "ci-A"
    assert "CREATE (created" not in query
    assert "row.node_id IN root.affected_ci_ids" in query
    assert "root.last_seen = datetime()" not in query


def test_icmp_availability_root_when_no_parent():
    """Availability CREATE site: ROOT fallback when no parent."""
    from engines.snmp_worker import _refresh_icmp_availability_events

    session = MagicMock()
    session.run = MagicMock(return_value=MagicMock())

    _refresh_icmp_availability_events(
        session,
        [
            {
                "node_id": "ci-E",
                "metric_id": "PING-CHECK",
                "protocol": "ICMP",
                "source_protocol": "ICMP",
                "availability_source": "PING",
                "event_type": "AVAILABILITY",
                "severity": "CRITICAL",
                "message": "Service/Host Down: PING-CHECK",
                "value": 0.0,
            }
        ],
        cache={},
    )

    calls = [c for c in session.run.call_args_list if "UNWIND" in c.args[0]]
    rows_param = calls[0].kwargs["availability_events"]
    assert rows_param[0]["correlation_type"] == "ROOT"
    assert rows_param[0]["root_cause_ci_id"] == "ci-E"


def test_icmp_latency_breach_propagates_when_parent_open():
    """Latency propagation updates parent ROOT metadata, not child rows."""
    from engines.snmp_worker import _refresh_icmp_latency_events

    session = MagicMock()
    session.run = MagicMock(return_value=MagicMock())
    cache = {("ci-E", "icmp_latency_ms"): {"parent_event_id": "evt-A", "root_cause_ci_id": "ci-A"}}

    _refresh_icmp_latency_events(
        session,
        [
            {
                "node_id": "ci-E",
                "metric_id": "icmp_latency_ms",
                "protocol": "ICMP",
                "source_protocol": "ICMP",
                "event_type": "THRESHOLD_BREACH",
                "status": "WARNING",
                "message": "Latency warning",
            }
        ],
        cache=cache,
    )

    calls = [c for c in session.run.call_args_list if "UNWIND" in c.args[0]]
    query = calls[0].args[0]
    rows_param = calls[0].kwargs["propagated_rows"]
    assert rows_param[0]["correlation_type"] == "PROPAGATED"
    assert rows_param[0]["propagated_from"] == "evt-A"
    assert rows_param[0]["root_cause_ci_id"] == "ci-A"
    assert "CREATE (created" not in query
    assert "row.node_id IN root.affected_ci_ids" in query
    assert "root.last_seen = datetime()" not in query


class _FakeUpdateResult:
    def __init__(self, updated_roots: int):
        self._updated_roots = updated_roots

    def single(self):
        return {"updated_roots": self._updated_roots}


class _FakeRootUpdateSession:
    def __init__(self):
        self.root = {
            "id": "evt-A",
            "status": "OPEN",
            "correlation_type": "ROOT",
            "affected_ci_ids": [],
            "affected_ci_count": 0,
            "comments": [],
            "last_seen": "root-observed-at",
        }
        self.child_events = []
        self.queries = []

    def run(self, query, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        updated = 0
        for row in kwargs.get("propagated_rows", []):
            if row.get("propagated_from") != self.root["id"]:
                continue
            if self.root.get("status") not in {"OPEN", "ACK", "RECOVERED"}:
                continue
            if self.root.get("correlation_type", "ROOT") != "ROOT":
                continue
            node_id = row.get("node_id")
            comment = row.get("affected_ci_comment")
            if node_id and node_id not in self.root["affected_ci_ids"]:
                self.root["affected_ci_ids"].append(node_id)
            self.root["affected_ci_count"] = len(self.root["affected_ci_ids"])
            if comment and comment not in self.root["comments"]:
                self.root["comments"].append(comment)
            updated += 1
        return _FakeUpdateResult(updated)


def test_propagated_rows_do_not_generate_duplicate_child_events_or_notes_on_repeated_polls():
    """Repeated propagated rows update one root-event affected entry exactly once."""
    from engines.snmp_worker import _update_propagated_root_events

    session = _FakeRootUpdateSession()
    row = {
        "node_id": "ci-E",
        "metric_id": "cpu-load",
        "correlation_type": "PROPAGATED",
        "propagated_from": "evt-A",
        "root_cause_ci_id": "ci-A",
    }

    _update_propagated_root_events(session, [dict(row)])
    _update_propagated_root_events(session, [dict(row)])

    assert session.child_events == []
    assert session.root["affected_ci_ids"] == ["ci-E"]
    assert session.root["affected_ci_count"] == 1
    assert len(session.root["comments"]) == 1
    assert session.root["last_seen"] == "root-observed-at"
    assert all("CREATE (created" not in entry["query"] for entry in session.queries)
    assert all("root.last_seen = datetime()" not in entry["query"] for entry in session.queries)


def test_propagated_root_update_logs_when_cached_parent_is_stale(caplog):
    """A stale propagated_from cache hit must produce an operational signal."""
    from engines.snmp_worker import _update_propagated_root_events

    session = _FakeRootUpdateSession()
    row = {
        "node_id": "ci-E",
        "metric_id": "cpu-load",
        "correlation_type": "PROPAGATED",
        "propagated_from": "missing-root-event",
        "root_cause_ci_id": "ci-A",
    }

    with caplog.at_level(logging.WARNING):
        _update_propagated_root_events(session, [row])

    assert session.root["affected_ci_ids"] == []
    assert "topology_rca_propagated_root_update_partial" in caplog.text


def test_icmp_latency_breach_root_when_no_parent():
    """Latency CREATE site: ROOT fallback."""
    from engines.snmp_worker import _refresh_icmp_latency_events

    session = MagicMock()
    session.run = MagicMock(return_value=MagicMock())

    _refresh_icmp_latency_events(
        session,
        [
            {
                "node_id": "ci-E",
                "metric_id": "icmp_latency_ms",
                "protocol": "ICMP",
                "source_protocol": "ICMP",
                "event_type": "THRESHOLD_BREACH",
                "status": "WARNING",
                "message": "Latency warning",
            }
        ],
        cache={},
    )

    calls = [c for c in session.run.call_args_list if "UNWIND" in c.args[0]]
    rows_param = calls[0].kwargs["breaches"]
    assert rows_param[0]["correlation_type"] == "ROOT"
    assert rows_param[0]["root_cause_ci_id"] == "ci-E"


def test_refresh_helpers_accept_cache_kwarg_backward_compat():
    """Pre-existing callers (no cache kwarg) still work — defaults to {} (all ROOT).

    This protects the existing tests in test_snmp_worker.py that call
    _refresh_icmp_*_events(session, updates) positionally.
    """
    from engines.snmp_worker import _refresh_icmp_latency_events

    session = MagicMock()
    session.run = MagicMock(return_value=MagicMock())

    # No cache kwarg — must not raise.
    _refresh_icmp_latency_events(
        session,
        [
            {
                "node_id": "ci-E",
                "metric_id": "icmp_latency_ms",
                "protocol": "ICMP",
                "source_protocol": "ICMP",
                "event_type": "THRESHOLD_BREACH",
                "status": "WARNING",
                "message": "Latency warning",
            }
        ],
    )

    calls = [c for c in session.run.call_args_list if "UNWIND" in c.args[0]]
    rows_param = calls[0].kwargs["breaches"]
    assert rows_param[0]["correlation_type"] == "ROOT"


# ---------------------------------------------------------------------------
# Task 3 — poll_snmp cache-build wiring (kill-switch + call order)
# ---------------------------------------------------------------------------


def _build_poll_snmp_mocks():
    """Build the common mock scaffolding for a poll_snmp() cycle.

    Uses the shared MockNeo4jSession from conftest so queries that call
    ``.single()`` or iterate both work correctly.
    """
    from tests.conftest import MockNeo4jSession

    mock_session = MockNeo4jSession()
    mock_session.set_default_response([])

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)
    return mock_session, mock_driver


_POLL_RECORD = {
    "node_id": "ci-001",
    "metric_id": "CPU",
    "protocol": "SNMP",
    "ip": "192.168.1.1",
    "community": "public",
    "oid": "1.3.6.1",
    "port": 161,
    "metric_name": "CPU",
    "criticality": 3,
    "metric_kind": None,
    "availability_source": None,
    "interval": 60,
}


def test_enable_topology_rca_false_skips_cache_build(monkeypatch):
    """ENABLE_TOPOLOGY_RCA=false → build_open_parent_index NOT called.

    Uses an SNMP-no-response failure (fetch_snmp_value=None) so pairs WOULD
    exist — proving it's the flag (not empty pairs) that skips the cache-build.
    """
    # The setting is a singleton; reset it so the env var takes effect.
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "false")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", [_POLL_RECORD])

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch("engines.snmp_worker.build_open_parent_index") as mock_build,
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    mock_build.assert_not_called()


def test_enable_topology_rca_true_calls_build_open_parent_index(monkeypatch):
    """ENABLE_TOPOLOGY_RCA=true → build_open_parent_index IS called with a pairs set.

    Uses an SNMP-no-response failure (fetch_snmp_value=None) so failure_updates is
    populated, giving the cache-build real (ci_id, metric_id) pairs to resolve.
    """
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", [_POLL_RECORD])

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch("engines.snmp_worker.build_open_parent_index", return_value={}) as mock_build,
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    mock_build.assert_called()
    # Two passes per cycle (initial + rebuild) — both with the same
    # (ci_id, metric_id) pairs set.
    assert mock_build.call_count == 2
    for call in mock_build.call_args_list:
        args, _ = call
        assert isinstance(args[1], set)
        assert ("ci-001", "CPU") in args[1]


def test_enable_topology_rca_defaults_to_true_when_unset(monkeypatch):
    """No env var set → topology RCA is ON by default (kill-switch default true)."""
    import config as _config

    monkeypatch.delenv("ENABLE_TOPOLOGY_RCA", raising=False)
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", [_POLL_RECORD])

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch("engines.snmp_worker.build_open_parent_index", return_value={}) as mock_build,
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    # Two-pass flow calls build_open_parent_index twice per cycle
    # (initial + rebuild).
    assert mock_build.call_count == 2


def test_cache_failure_falls_back_to_root_and_still_creates_events(monkeypatch, caplog):
    """Task 10 (S4): cache-build raises → warning logged, events still created as ROOT.

    Proves the hot CREATE path stays exception-free — we assert the UNWIND...CREATE
    session.run call still happened with ROOT rows, not just that a warning was logged.
    Uses fetch_snmp_value=None to produce a real SNMP_NO_RESPONSE failure so the
    failure_updates path is exercised end-to-end.
    """
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", [_POLL_RECORD])

    def always_fail(*args, **kwargs):
        raise RuntimeError("neo4j connection lost")

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=always_fail,
        ) as mock_build,
        caplog.at_level(logging.WARNING),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()  # must not raise

    # Cache-build was attempted and raised (twice — initial + rebuild).
    assert mock_build.call_count == 2

    # The UNWIND...CREATE call for SNMP collection failures still ran.
    create_calls = [
        c for c in mock_session.queries if "UNWIND" in c["query"] and "CREATE" in c["query"]
    ]
    assert create_calls, (
        "UNWIND...CREATE must still run after cache-build failure — "
        "events must be created as ROOT, not skipped"
    )
    # And the rows it would have created are ROOT (cache empty after failure).
    failures_param = create_calls[0]["params"].get("failures", [])
    assert failures_param, "expected at least one failure row"
    for row in failures_param:
        assert row["correlation_type"] == "ROOT"
        assert row["root_cause_ci_id"] == row["node_id"]


def test_cache_is_local_to_poll_snmp_cycle(monkeypatch):
    """W2: cache state is LOCAL to one poll_snmp() cycle — no module-level leak.

    Two consecutive cycles: first fails (cache={}), second succeeds (cache populated).
    The second cycle's cache must not inherit the first's empty state.
    """
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", [_POLL_RECORD])

    # Two cache-build calls per cycle (initial + rebuild), two cycles total.
    # Cycle 1: both raise. Cycle 2: both succeed.
    call_returns = [
        RuntimeError("transient"),
        RuntimeError("transient"),
        {"nonempty": True},
        {"nonempty": True},
    ]

    def fake_build(*args, **kwargs):
        result = call_returns.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch("engines.snmp_worker.build_open_parent_index", side_effect=fake_build) as mock_build,
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()  # cycle 1: cache-build raises → cache={}
        poll_snmp()  # cycle 2: cache-build returns dict → cache used

    assert mock_build.call_count == 4


# ---------------------------------------------------------------------------
# Task — end-to-end poll_snmp cache-hit → PROPAGATED CREATE (C1 guard)
# ---------------------------------------------------------------------------


def test_poll_snmp_cache_hit_propagates_to_create_row_end_to_end(monkeypatch):
    """End-to-end: build_open_parent_index cache hit flows through poll_snmp()
    into a propagated child update against the parent ROOT.

    Guards the C1 regression (cache built BEFORE the CREATE sites). Unlike the
    Task-3 tests which patch build_open_parent_index to return {}, this test
    populates the cache with a real parent entry and asserts the propagated
    metadata update query is used instead of creating child events.
    """
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", [_POLL_RECORD])

    populated_cache = {
        ("ci-001", "CPU"): {
            "parent_event_id": "evt-A",
            "root_cause_ci_id": "ci-A",
        }
    }

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            return_value=populated_cache,
        ) as mock_build,
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    # Cache-build was called twice (initial + rebuild).
    assert mock_build.call_count == 2

    # Find the propagated-root update call captured on the session and inspect rows.
    propagated_calls = [
        c
        for c in mock_session.queries
        if "UNWIND" in c["query"] and "propagated_rows" in c["query"]
    ]
    assert propagated_calls, "expected a propagated_rows UNWIND call to be captured"

    rows = propagated_calls[0]["params"].get("propagated_rows", [])
    assert rows, "expected at least one propagated row from poll_snmp"

    row = rows[0]
    assert row["correlation_type"] == "PROPAGATED"
    assert row["propagated_from"] == "evt-A"
    assert row["root_cause_ci_id"] == "ci-A"


# ---------------------------------------------------------------------------
# P0 (fix #416) — end-to-end poll_snmp same-cycle correlation matrix
# (SCN-001..011).
#
# These tests cover the three-pass correlation flow inside poll_snmp:
#   Pass 1 (Collect)    → failure_updates / availability_updates / latency_updates
#   Pass 2 (Materialize)→ _refresh_*(candidates, cache={}) → forces ROOT writes
#   Rebuild cache       → build_open_parent_index now sees the new ROOTs
#   Pass 3 (Attach)     → _refresh_*(non_candidates, cache=rebuilt) → PROPAGATED
#                          routing + _update_propagated_root_events attach
#
# Each scenario uses a side_effect list of caches for build_open_parent_index
# to model the (initial empty cache) → (rebuilt cache with new ROOT events)
# progression that the production two-pass flow produces.
# ---------------------------------------------------------------------------


def _record(node_id, metric_id, **overrides):
    """Build a poll_snmp source record for one (ci, metric) pair."""
    rec = {
        "node_id": node_id,
        "metric_id": metric_id,
        "protocol": "SNMP",
        "ip": "192.168.1.1",
        "community": "public",
        "oid": "1.3.6.1",
        "port": 161,
        "metric_name": metric_id,
        "criticality": 3,
        "metric_kind": None,
        "availability_source": None,
        "interval": 60,
    }
    rec.update(overrides)
    return rec


def _set_scn_sequence_responses(mock_session):
    """Configure the mock session for the no-response (failure) path.

    The polled CI/metric returns no SNMP value → the failure path is taken
    in poll_snmp → ``_refresh_snmp_collection_failures`` is called with
    cache={} (Pass 2) and then with the rebuilt cache (Pass 3).
    """
    # Any "match" query returns an empty Result (no parent event found);
    # the default response is already [] in the helper.
    mock_session.set_default_response([])


def _propagated_root_update_calls(mock_session):
    """Return every UNWIND+propagated_rows query the session captured.

    Each entry is the captured query dict (with ``params``); the
    ``propagated_rows`` list inside ``params`` is what the root-update
    query will MERGE into root events.
    """
    return [
        c
        for c in mock_session.queries
        if "UNWIND" in c["query"] and "propagated_rows" in c["query"]
    ]


def _root_create_calls(mock_session):
    """Return every UNWIND+CREATE call the session captured.

    These are the FOREACH(CREATE (created:Event...)) sites inside
    ``_refresh_snmp_collection_failures`` / ``_refresh_icmp_availability_events``
    / ``_refresh_icmp_latency_events`` that materialize a new ROOT Event
    for the cycle. SCN-001/004/006/011 assert exactly one such call.
    """
    return [c for c in mock_session.queries if "UNWIND" in c["query"] and "CREATE" in c["query"]]


def test_first_cycle_parent_and_children_materializes_one_root_and_attaches_dependents(
    monkeypatch,
):
    """First cycle: an empty open-event cache still yields one ROOT plus N attachments."""
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    parent_id = "ci-parent"
    child_ids = ["ci-child-1", "ci-child-2", "ci-child-3"]
    records = [
        _record(parent_id, "cpu-load"),
        *(_record(child_id, "cpu-load") for child_id in child_ids),
    ]
    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", records)

    parent_event_id = "evt-parent-root"
    rebuilt_cache = {
        (child_id, "cpu-load"): {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": parent_id,
        }
        for child_id in child_ids
    }
    topology_relations = {child_id: {parent_id} for child_id in child_ids}

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=[{}, rebuilt_cache],
        ),
        patch(
            "engines.snmp_worker.get_topology_relations",
            return_value=topology_relations,
        ) as mock_get_relations,
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    mock_get_relations.assert_called_once_with(
        mock_session,
        {parent_id, *child_ids},
    )
    create_calls = _root_create_calls(mock_session)
    created_rows = [row for call in create_calls for row in call["params"].get("failures", [])]
    assert {row["node_id"] for row in created_rows} == {parent_id}

    propagated = _propagated_root_update_calls(mock_session)
    assert propagated, "expected first-cycle dependents to reach the attach pass"
    attached_rows = propagated[-1]["params"]["propagated_rows"]
    assert {row["node_id"] for row in attached_rows} == set(child_ids)
    assert all(row["propagated_from"] == parent_event_id for row in attached_rows)


def test_scn_001_parent_then_children_no_amplification_in_subsequent_cycle(monkeypatch):
    """SCN-001: in a subsequent cycle (parent ROOT already exists in the
    topology cache), the parent and N children all fail in the same
    cycle. The two-pass flow MUST suppress same-cycle child amplification:
    no child Event rows are created, every child CI is attached to the
    parent's existing ROOT via the affected-CI set, and the Set(affected_ci_ids)
    is deduped by the existing IN guard inside _update_propagated_root_events.

    Note: SCN-001 in the spec is the ideal outcome (1 ROOT + N attached).
    The production cache (``build_open_parent_index``) is built from
    OPEN/ACK events, so a *first* cycle where the parent is brand new
    cannot resolve the children's topology parent (the parent has no
    event yet) — that scenario collapses to "all ROOT, no attach" and
    is a known limitation of an event-based cache. The unit tests for
    ``cycle_root_candidates`` in ``test_event_correlation.py`` cover the
    first-cycle selector behaviour in isolation.
    """
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    parent_id = "ci-parent"
    child_ids = ["ci-child-1", "ci-child-2", "ci-child-3"]
    records = [
        _record(parent_id, "cpu-load"),
        *(_record(cid, "cpu-load") for cid in child_ids),
    ]

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", records)
    _set_scn_sequence_responses(mock_session)

    # The parent already has a ROOT event from a prior cycle, so both
    # initial and rebuilt caches resolve the children to it.
    parent_event_id = "evt-parent-root"
    populated_cache = {
        (cid, "cpu-load"): {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": parent_id,
        }
        for cid in child_ids
    }
    # Parent is also in the cache as "no upstream parent" so the
    # helper tags it as ROOT. The existing _resolve_correlation uses
    # this contract: cache miss → ROOT.
    populated_cache[(parent_id, "cpu-load")] = {
        "parent_event_id": None,
        "root_cause_ci_id": parent_id,
    }

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=[populated_cache, populated_cache],
        ),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    # Every child is attached in the propagated_rows UNWIND call — this
    # is the SCN-001 invariant: no child Event rows, every dependent
    # surfaces as a propagated row that hits the existing parent ROOT's
    # affected-CI set. The parent itself is a candidate (parent_event_id
    # in the cache is None) and goes through Pass 2, not Pass 3.
    propagated = _propagated_root_update_calls(mock_session)
    assert propagated, "expected a propagated_rows UNWIND call (attach pass)"
    attached_rows = propagated[-1]["params"]["propagated_rows"]
    attached_node_ids = sorted(row["node_id"] for row in attached_rows)
    assert attached_node_ids == sorted(child_ids)
    for row in attached_rows:
        assert row["correlation_type"] == "PROPAGATED"
        assert row["propagated_from"] == parent_event_id


def test_scn_002_children_then_parent_no_amplification_in_subsequent_cycle(monkeypatch):
    """SCN-002: reverse observation order — same no-amplification outcome."""
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    parent_id = "ci-parent"
    child_ids = ["ci-child-1", "ci-child-2", "ci-child-3"]
    records = [
        *(_record(cid, "cpu-load") for cid in child_ids),
        _record(parent_id, "cpu-load"),
    ]

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", records)
    _set_scn_sequence_responses(mock_session)

    parent_event_id = "evt-parent-root"
    populated_cache = {
        (cid, "cpu-load"): {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": parent_id,
        }
        for cid in child_ids
    }
    populated_cache[(parent_id, "cpu-load")] = {
        "parent_event_id": None,
        "root_cause_ci_id": parent_id,
    }

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=[populated_cache, populated_cache],
        ),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    propagated = _propagated_root_update_calls(mock_session)
    assert propagated
    attached_rows = propagated[-1]["params"]["propagated_rows"]
    attached_node_ids = sorted(row["node_id"] for row in attached_rows)
    assert attached_node_ids == sorted(child_ids)


def test_scn_003_interleaved_order_no_amplification_in_subsequent_cycle(monkeypatch):
    """SCN-003: any interleaved observation order produces the same no-amplification outcome."""
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    parent_id = "ci-parent"
    child_ids = ["ci-child-1", "ci-child-2", "ci-child-3"]
    interleaved = [
        _record(child_ids[0], "cpu-load"),
        _record(parent_id, "cpu-load"),
        _record(child_ids[1], "cpu-load"),
        _record(child_ids[2], "cpu-load"),
    ]

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", interleaved)
    _set_scn_sequence_responses(mock_session)

    parent_event_id = "evt-parent-root"
    populated_cache = {
        (cid, "cpu-load"): {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": parent_id,
        }
        for cid in child_ids
    }
    populated_cache[(parent_id, "cpu-load")] = {
        "parent_event_id": None,
        "root_cause_ci_id": parent_id,
    }

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=[populated_cache, populated_cache],
        ),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    propagated = _propagated_root_update_calls(mock_session)
    assert propagated
    attached_node_ids = sorted(
        row["node_id"] for row in propagated[-1]["params"]["propagated_rows"]
    )
    assert attached_node_ids == sorted(child_ids)


def test_scn_004_multi_affected_metric_dedupes_affected_ci(monkeypatch):
    """SCN-004: one parent failure with N children with multiple metrics per CI.

    The child's affected-CI entry must appear ONCE regardless of how many
    metrics produced events for it. Pass 3's _update_propagated_root_events
    uses an IN guard + size() so duplicates are silently dropped at the
    Cypher level — the Set(affected_ci_ids) at the ROOT event is deduped.
    """
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    parent_id = "ci-parent"
    multi_metric_child = "ci-multi-child"
    records = [
        _record(parent_id, "cpu-load"),
        _record(multi_metric_child, "cpu-load"),
        _record(multi_metric_child, "mem-load"),
    ]

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", records)
    _set_scn_sequence_responses(mock_session)

    parent_event_id = "evt-parent-root"
    populated_cache = {
        (multi_metric_child, "cpu-load"): {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": parent_id,
        },
        (multi_metric_child, "mem-load"): {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": parent_id,
        },
    }
    populated_cache[(parent_id, "cpu-load")] = {
        "parent_event_id": None,
        "root_cause_ci_id": parent_id,
    }

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=[populated_cache, populated_cache],
        ),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    propagated = _propagated_root_update_calls(mock_session)
    assert propagated
    attached_rows = propagated[-1]["params"]["propagated_rows"]
    child_rows = [r for r in attached_rows if r["node_id"] == multi_metric_child]
    assert len(child_rows) == 2
    assert all(r["propagated_from"] == parent_event_id for r in child_rows)
    # The ROOT event's affected_ci_ids set dedupes the child down to a
    # single entry — the actual dedup is enforced by the Cypher IN guard
    # inside _update_propagated_root_events, which the unit test
    # ``test_propagated_rows_do_not_generate_duplicate_child_events_or_notes_on_repeated_polls``
    # pins down at the helper level.


def test_scn_006_no_parent_relationship_results_in_root(monkeypatch):
    """SCN-006: a failing CI with no resolvable parent → ROOT, no attach."""
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    isolated_id = "ci-isolated"
    records = [_record(isolated_id, "cpu-load")]

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", records)
    _set_scn_sequence_responses(mock_session)

    # Both initial and rebuilt cache are empty — the CI has no parent.
    empty_cache: dict = {}

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=[empty_cache, empty_cache],
        ),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    # Pass 2 writes one ROOT; Pass 3 has no non-candidates to process.
    create_calls = _root_create_calls(mock_session)
    assert len(create_calls) == 1
    assert [row["node_id"] for row in create_calls[0]["params"]["failures"]] == [isolated_id]


def test_scn_009_lookup_failure_does_not_abort_cycle(monkeypatch, caplog):
    """SCN-009: cache-build raises → events still created as ROOT (no data loss)."""
    import logging

    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    records = [_record("ci-001", "cpu-load")]

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", records)
    _set_scn_sequence_responses(mock_session)

    def always_fail(*args, **kwargs):
        raise RuntimeError("simulated neo4j connection lost")

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch("engines.snmp_worker.build_open_parent_index", side_effect=always_fail),
        caplog.at_level(logging.WARNING),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()  # MUST NOT raise

    # At least one UNWIND...CREATE ran with ROOT rows — no data loss.
    create_calls = _root_create_calls(mock_session)
    assert create_calls, "events must still be created as ROOT after cache failure"
    assert all(
        row["correlation_type"] == "ROOT"
        for call in create_calls
        for row in call["params"].get("failures", [])
    )


def test_scn_010_pass3_attachment_idempotent_on_repeated_attach(monkeypatch):
    """SCN-010: Pass 3 attach is idempotent — Set(affected_ci_ids) never duplicates.

    The existing _update_propagated_root_events query uses an IN guard +
    size() so re-running it for the same root/dependent pair is a no-op.
    We assert that across two consecutive poll_snmp cycles, the captured
    propagated_rows carry the SAME node_id (the root-update query itself
    enforces dedup at the database side).
    """
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    parent_id = "ci-parent"
    child_id = "ci-child-1"
    records = [_record(parent_id, "cpu-load"), _record(child_id, "cpu-load")]

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", records)
    _set_scn_sequence_responses(mock_session)

    parent_event_id = "evt-parent-root"
    populated_cache = {
        (child_id, "cpu-load"): {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": parent_id,
        },
        (parent_id, "cpu-load"): {
            "parent_event_id": None,
            "root_cause_ci_id": parent_id,
        },
    }

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=[populated_cache, populated_cache, populated_cache, populated_cache],
        ),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()
        poll_snmp()

    propagated = _propagated_root_update_calls(mock_session)
    # Each cycle attaches the child once. Across two cycles the same child
    # is attached in each — but the root-event affected_ci_ids set itself
    # never grows beyond a single entry (the existing IN guard). The unit
    # test ``test_propagated_rows_do_not_generate_duplicate_child_events_or_notes_on_repeated_polls``
    # already pins the per-row dedup at the query level; here we assert
    # the call shape is consistent across cycles.
    assert len(propagated) >= 2
    for call in propagated:
        rows = call["params"]["propagated_rows"]
        child_rows = [r for r in rows if r["node_id"] == child_id]
        assert all(r["propagated_from"] == parent_event_id for r in child_rows)


def test_scn_011_all_three_event_families_route_through_pass2(monkeypatch):
    """SCN-011: the three event families (collection / availability / latency)
    follow the same two-pass correlation flow.

    The unit tests in ``TestMaterializeCurrentCycleRoots`` already prove
    per-family routing in isolation. Here we exercise the collection
    family end-to-end to assert that the orchestrator (Pass 1 → Pass 2
    → Pass 3) correctly routes the collection-failure row through
    cycle_root_candidates → materialize → attach.
    """
    import config as _config

    monkeypatch.setenv("ENABLE_TOPOLOGY_RCA", "true")
    monkeypatch.setattr(_config, "_polling_pipeline_settings", None)

    parent_id = "ci-parent"
    child_id = "ci-child-1"
    records = [_record(parent_id, "cpu-load"), _record(child_id, "cpu-load")]

    mock_session, mock_driver = _build_poll_snmp_mocks()
    mock_session.set_response("match", records)
    _set_scn_sequence_responses(mock_session)

    parent_event_id = "evt-parent-root"
    populated_cache = {
        (child_id, "cpu-load"): {
            "parent_event_id": parent_event_id,
            "root_cause_ci_id": parent_id,
        },
        (parent_id, "cpu-load"): {
            "parent_event_id": None,
            "root_cause_ci_id": parent_id,
        },
    }

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=[populated_cache, populated_cache],
        ),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    # The collection-failure family routed the child through Pass 3's
    # propagated_rows UNWIND (no child Event rows, attached to parent
    # ROOT). The parent is a candidate and goes through Pass 2, so it
    # is NOT in the propagated_rows payload.
    propagated = _propagated_root_update_calls(mock_session)
    assert propagated
    attached_rows = propagated[-1]["params"]["propagated_rows"]
    assert sorted(row["node_id"] for row in attached_rows) == [child_id]
    for row in attached_rows:
        assert row["correlation_type"] == "PROPAGATED"
        assert row["propagated_from"] == parent_event_id
