"""Shared test fixtures for the Path A RCA chain integration tests.

The centerpiece test in `test_path_a_rca_chain.py` exercises the real
`poll_snmp()` write path against a `MockNeo4jDriver`. The fixture factory
here wires up:

- CI ids and metric definitions for a fan-out or chain topology
- A `ChainMockNeo4jSession` subclass that dispatches on query params
  (so `find_open_parent_event(ci_id=X)` returns the correct parent for
  each `ci_id`, not the same canned response for every call)
- Stubbed SNMP poller measurements (no real network)
- Patches for `SessionLocal`, `bulk_insert_metrics`, scheduler side-effects
- Captures every CREATE Event query so tests can assert what was written
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

# Ensure backend root is on the import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.conftest import MockNeo4jSession  # noqa: E402


# ---------------------------------------------------------------------------
# Topology helpers
# ---------------------------------------------------------------------------


def _fan_out_layout(root_count: int, dependent_count: int) -> Dict[str, Any]:
    """A (root) is the parent; B, C, D, ... are dependents that fail when A fails."""
    root_ids = [f"ci-A{i}" for i in range(root_count)] if root_count > 1 else ["ci-A"]
    dependent_ids = [f"ci-{chr(ord('B') + i)}" for i in range(dependent_count)]
    parent_of = {ci: root_ids[0] for ci in dependent_ids}
    return {
        "root_ids": root_ids,
        "dependent_ids": dependent_ids,
        "parent_of": parent_of,
    }


def _chain_layout(root_count: int, dependent_count: int) -> Dict[str, Any]:
    """A -> B -> C (one root, dependent_count chained descendants)."""
    # dependent_count includes the immediate child. e.g. dependent_count=2 → A->B->C.
    chain = ["ci-A"] + [f"ci-{chr(ord('B') + i)}" for i in range(dependent_count - 1)]
    parent_of = {chain[i + 1]: chain[i] for i in range(len(chain) - 1)}
    return {
        "root_ids": ["ci-A"],
        "dependent_ids": chain[1:],
        "parent_of": parent_of,
    }


# ---------------------------------------------------------------------------
# Mock session that dispatches on params
# ---------------------------------------------------------------------------


class ChainMockNeo4jSession(MockNeo4jSession):
    """Extends MockNeo4jSession with per-ci parent event lookups.

    `find_open_parent_event(ci_id=X, max_depth=3)` is matched by the
    "DEPENDS_ON|HOSTED_ON|CONNECTS_TO" substring of its Cypher. The
    default MockNeo4jSession returns the same canned records for every
    matching query. This subclass dispatches on `params['ci_id']` and
    looks up parent event info from a pre-loaded `parent_lookup` dict.

    CREATE Event queries are captured into `created_events` (keyed by the
    ci_id param) so the test can assert which Event rows were written.
    """

    def __init__(self):
        super().__init__()
        self.parent_lookup: Dict[str, Dict[str, Any]] = {}
        self.parent_lookups: List[Dict[str, Any]] = []
        self.created_events: Dict[str, List[Dict[str, Any]]] = {}
        self._parent_query_substring = "depends_on|hosted_on|connects_to"
        self._create_event_substring = "create (created:event"
        self._counter_query_substring = "count(distinct n) as cis_monitored"
        self._cis_monitored: int = 0

    def configure(
        self,
        parent_lookup: Dict[str, Dict[str, Any]],
        ci_records: List[Dict[str, Any]],
        cis_monitored: int = 0,
    ) -> None:
        """Pre-load parent lookup table and the initial CI+Metric records."""
        self.parent_lookup = dict(parent_lookup)
        # Default response for the initial MATCH (n:CI)-[r:HAS_METRIC]→(m:MetricDef)
        self._default_ci_records = list(ci_records)
        self._cis_monitored = cis_monitored if cis_monitored else len(self._default_ci_records)
        # Also set the substring-based default so any non-overridden MATCH
        # query returns the CI list.
        self.set_response("match (n:ci)-[r:has_metric]->(m:metricdef", self._default_ci_records)
        self.set_response("count(distinct n) as cis_monitored", [{"cis_monitored": self._cis_monitored}])
        self.set_default_response([])

    def run(self, query: str, **params):
        query_lower = query.lower()
        # 1. Initial CI+Metric MATCH (the query that enumerates CIs to poll)
        if "match (n:ci)-[r:has_metric]->(m:metricdef)" in query_lower:
            from tests.conftest import MockNeo4jResult
            return MockNeo4jResult(self._default_ci_records)
        if self._counter_query_substring in query_lower:
            from tests.conftest import MockNeo4jResult
            return MockNeo4jResult([{"cis_monitored": self._cis_monitored}])
        # 2. find_open_parent_event queries — dispatch on ci_id param
        if self._parent_query_substring in query_lower:
            from tests.conftest import MockNeo4jResult
            ci_id = params.get("ci_id")
            parent = self.parent_lookup.get(ci_id) if ci_id else None
            self.parent_lookups.append({"ci_id": ci_id, "parent": parent})
            return MockNeo4jResult([parent] if parent else [])
        # 3. CREATE Event queries — capture params for assertions
        if self._create_event_substring in query_lower:
            from tests.conftest import MockNeo4jResult
            created_params: Dict[str, Any] = dict(params)
            # UNWIND $failures / $availability_events / $breaches — capture the full list
            # and the query text so the test can assert correlation tags per row.
            for key in ("failures", "availability_events", "breaches"):
                if key in params and isinstance(params[key], list) and params[key]:
                    for row in params[key]:
                        if not isinstance(row, dict):
                            continue
                        node_id = row.get("node_id")
                        if node_id is None:
                            continue
                        self.created_events.setdefault(node_id, []).append(
                            {"query": query, "params": {key: [row]}}
                        )
                    return MockNeo4jResult([])
            # CREATE Event without an UNWIND list (not used in Path A, but kept for safety).
            self.created_events.setdefault("ci-unknown", []).append(
                {"query": query, "params": created_params}
            )
            return MockNeo4jResult([])
        return super().run(query, **params)


class ChainMockNeo4jDriver:
    """MockNeo4jDriver variant that yields a ChainMockNeo4jSession."""

    def __init__(self):
        self.session = MagicMock()
        self._mock_session = ChainMockNeo4jSession()
        self.session.return_value = self._mock_session

    @property
    def mock_session(self) -> ChainMockNeo4jSession:
        return self._mock_session


# ---------------------------------------------------------------------------
# Fixture factory
# ---------------------------------------------------------------------------


def _build_metric_record(
    ci_id: str,
    metric_id: str = "PING-CHECK",
    protocol: str = "ICMP",
    metric_kind: str = "availability",
    availability_source: Optional[str] = "ICMP",
    criticality: int = 3,
    metric_name: str = "Ping availability",
) -> Dict[str, Any]:
    return {
        "node_id": ci_id,
        "ip": f"10.0.0.{abs(hash(ci_id)) % 250 + 1}",
        "community": "public",
        "port": 161,
        "metric_id": metric_id,
        "metric_name": metric_name,
        "protocol": protocol,
        "oid": None,
        "criticality": criticality,
        "metric_kind": metric_kind,
        "availability_source": availability_source,
        "interval": 60,
    }


_SEVERITY_TO_CRITICALITY = {"CRITICAL": 3, "WARNING": 2, "INFO": 1}


def _severity_for(
    ci_id: str,
    layout: Dict[str, Any],
    severities: Optional[Dict[str, str]],
) -> str:
    if severities and ci_id in severities:
        return severities[ci_id]
    # Default: root CRITICAL, descendants WARNING
    if ci_id in layout["root_ids"]:
        return "CRITICAL"
    return "WARNING"


def _criticality_for(severity: str) -> int:
    return _SEVERITY_TO_CRITICALITY.get(severity.upper(), 3)


def _poller_stub_for(severity: str) -> Any:
    """Stub `fetch_icmp_ping` (and a few others) so poll_snmp doesn't hit the network.

    Returns a mock that always produces a DOWN (0.0) measurement, which
    triggers an AVAILABILITY event with the given severity.
    """
    from polling.icmp_measurements import PingMeasurement

    return PingMeasurement(available=False, latency_ms=None)


def _build_parent_lookup(layout: Dict[str, Any], root_event_id: str = "evt-A-root") -> Dict[str, Dict[str, Any]]:
    """Build the parent_lookup table: for each dependent CI, map to A's open event."""
    return {
        ci: {
            "parent_event_id": root_event_id,
            "parent_ci_id": layout["root_ids"][0],
            "root_cause_ci_id": layout["root_ids"][0],
            "correlation_type": "ROOT",
        }
        for ci in layout["parent_of"].keys()
    }


def build_dependency_chain(
    topology: str = "fan_out",
    root_count: int = 1,
    dependent_count: int = 3,
    severities: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a chain fixture: returns a dict with the wired-up mocks.

    The test is expected to:
        fixture = build_dependency_chain(...)
        with patch("engines.snmp_worker.driver", fixture["driver"]), \
             patch("engines.snmp_worker.SessionLocal", return_value=fixture["db"]), \
             patch("engines.snmp_worker.bulk_insert_metrics"), \
             patch("engines.snmp_worker.fetch_icmp_ping", return_value=fixture["ping_measurement"]):
            poll_snmp()

    Then assert on fixture["session"].created_events and
    fixture["session"].parent_lookups.

    Keys returned:
        driver: ChainMockNeo4jDriver
        session: ChainMockNeo4jSession (driver.mock_session)
        db: MagicMock for SQLAlchemy SessionLocal
        layout: dict with root_ids, dependent_ids, parent_of
        ci_ids: list of all CI ids in the chain
        ci_records: list of (ci, metric) records returned by the initial MATCH
        severities: resolved severity per ci_id
        ping_measurement: deterministic PingMeasurement that forces DOWN
        root_event_id: id used for A's open ROOT event
    """
    if topology == "fan_out":
        layout = _fan_out_layout(root_count, dependent_count)
    elif topology == "chain":
        layout = _chain_layout(root_count, dependent_count)
    else:
        raise ValueError(f"unknown topology {topology!r}")

    all_ci_ids = layout["root_ids"] + layout["dependent_ids"]
    resolved_severities = {ci: _severity_for(ci, layout, severities) for ci in all_ci_ids}

    # Build initial CI+Metric MATCH records — one per (CI, metric).
    # Each CI's criticality is derived from its requested severity so the
    # poll_snmp's _base_severity_from_criticality helper reproduces the
    # right severity in the captured row.
    ci_records = [
        _build_metric_record(
            ci_id=ci,
            metric_id="PING-CHECK",
            protocol="ICMP",
            metric_kind="availability",
            availability_source="ICMP",
            criticality=_criticality_for(resolved_severities[ci]),
            metric_name=f"Ping-{ci}",
        )
        for ci in all_ci_ids
    ]

    parent_lookup = _build_parent_lookup(layout)
    root_event_id = "evt-A-root"

    driver = ChainMockNeo4jDriver()
    driver.mock_session.configure(
        parent_lookup=parent_lookup,
        ci_records=ci_records,
        cis_monitored=len(all_ci_ids),
    )

    db = MagicMock()
    db.execute.return_value.first.return_value = None

    return {
        "driver": driver,
        "session": driver.mock_session,
        "db": db,
        "layout": layout,
        "ci_ids": all_ci_ids,
        "ci_records": ci_records,
        "severities": resolved_severities,
        "ping_measurement": _poller_stub_for("CRITICAL"),
        "root_event_id": root_event_id,
    }
