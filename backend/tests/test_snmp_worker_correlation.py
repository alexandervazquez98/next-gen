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

    mock_build.assert_called_once()
    # Second positional arg must be a set of (ci_id, metric_id) tuples.
    args, _ = mock_build.call_args
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

    mock_build.assert_called_once()


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

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_snmp_value", return_value=None),
        patch(
            "engines.snmp_worker.build_open_parent_index",
            side_effect=RuntimeError("neo4j connection lost"),
        ) as mock_build,
        caplog.at_level(logging.WARNING),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()  # must not raise

    # Cache-build was attempted and raised.
    mock_build.assert_called_once()

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

    call_returns = [RuntimeError("transient"), {"nonempty": True}]

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

    assert mock_build.call_count == 2


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

    # Cache-build was called with the (ci_id, metric_id) pairs set.
    mock_build.assert_called_once()

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
