"""Tests for the modern SNMP path's degraded ``PROPAGATED`` child Events.

feat-539 / T4 — locked decision #1 of issue #539
(``degrade_severity_and_propagate``): when a propagation crosses a
PhysicalLink whose status is ``UNKNOWN``, the modern SNMP path materializes a
**separate** ``PROPAGATED`` Event at ``WARNING`` severity instead of only
enriching the ROOT Event. The ROOT Event keeps its original severity, the
child stays linked to the affected CI, and ``root_cause_ci_id`` keeps pointing
at the ROOT CI — never at the PhysicalLink.

The rules pinned here:

1. An ``UNKNOWN`` crossing produces a separate ``PROPAGATED`` child at
   ``WARNING`` severity.
2. The child stays linked to the affected CI and keeps the ROOT CI as its
   ``root_cause_ci_id`` (never the PhysicalLink id).
3. Creation is idempotent — the write reuses the module's existing
   ``OPTIONAL MATCH`` + ``head(collect(...))`` + ``FOREACH(CREATE)``
   deduplication machinery, and one failure observed twice in a batch yields a
   single child.
4. A pure-CI parent (no link metadata) keeps the legacy behaviour: the ROOT
   Event is enriched, no child Event is created.
5. An ``UP`` PhysicalLink propagates without degrading the severity.
6. The child write runs under the event-writer triplet lock that the refresh
   helper already acquires.
7. The degradation policy is read from
   ``services.correlation_propagation_contract`` — never hardcoded.
8. The child write can never match or re-severity a ROOT Event.
9. A failing child write never aborts the polling cycle.

Strict TDD: every rule below was observed RED before the implementation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from engines import snmp_worker

ROOT_CI_ID = "ci-A"
AFFECTED_CI_ID = "ci-E"
ROOT_EVENT_ID = "evt-A"
LINK_ID = "pl-1"
METRIC_ID = "cpu-load"

SNMP_WORKER_SOURCE = Path(snmp_worker.__file__).resolve()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _cache_with_link(link_status: str = "UNKNOWN", metric_id: str = METRIC_ID) -> dict:
    """Correlation cache entry produced by an UNKNOWN/UP PhysicalLink crossing."""
    return {
        (AFFECTED_CI_ID, metric_id): {
            "parent_event_id": ROOT_EVENT_ID,
            "root_cause_ci_id": ROOT_CI_ID,
            "link_id": LINK_ID,
            "link_status": link_status,
        }
    }


def _collection_failure_row() -> dict:
    return {
        "node_id": AFFECTED_CI_ID,
        "metric_id": METRIC_ID,
        "severity": "CRITICAL",
        "message": "Metric Collection Failed: timeout",
        "event_type": "COLLECTION_FAILURE",
        "failure_family": "SNMP_NO_RESPONSE",
        "source_protocol": "SNMP",
    }


def _session() -> MagicMock:
    session = MagicMock()
    session.run = MagicMock(return_value=MagicMock())
    return session


def _degraded_calls(session: MagicMock) -> list:
    """Every session.run call that carries the degraded-child payload."""
    return [call for call in session.run.call_args_list if "degraded_rows" in call.kwargs]


def _root_enrichment_calls(session: MagicMock) -> list:
    """Every session.run call that carries the legacy ROOT-enrichment payload."""
    return [call for call in session.run.call_args_list if "propagated_rows" in call.kwargs]


def _refresh(session, rows, cache, lock_db=None) -> None:
    snmp_worker._refresh_snmp_collection_failures(
        session,
        rows,
        cache=cache,
        lock_db=lock_db,
    )


# ---------------------------------------------------------------------------
# Rule 1 — an UNKNOWN crossing produces a separate WARNING PROPAGATED child
# ---------------------------------------------------------------------------


def test_unknown_link_crossing_creates_a_separate_warning_propagated_event():
    """The modern path materializes a child Event instead of only enriching the ROOT."""
    session = _session()

    _refresh(session, [_collection_failure_row()], _cache_with_link("UNKNOWN"))

    degraded = _degraded_calls(session)
    assert len(degraded) == 1, "expected exactly one degraded-child write"

    query = degraded[0].args[0]
    rows = degraded[0].kwargs["degraded_rows"]
    assert len(rows) == 1
    row = rows[0]

    # A SEPARATE Event node is created — not an update of the ROOT Event.
    assert "CREATE (created:Event" in query
    assert "correlation_type: 'PROPAGATED'" in query
    # The degraded child is emitted at WARNING, not at the parent's severity.
    assert row["severity"] == "WARNING"
    assert row["correlation_type"] == "PROPAGATED" or "PROPAGATED" in query
    # It is a distinct write from the ROOT enrichment.
    assert _root_enrichment_calls(session), "the legacy ROOT enrichment must still run"


# ---------------------------------------------------------------------------
# Rule 2 — the child stays on the affected CI and names the ROOT CI
# ---------------------------------------------------------------------------


def test_degraded_child_stays_linked_to_the_affected_ci_and_names_the_root_ci():
    """HAS_EVENT targets the affected CI; root_cause_ci_id is the ROOT CI, not the link."""
    session = _session()

    _refresh(session, [_collection_failure_row()], _cache_with_link("UNKNOWN"))

    degraded = _degraded_calls(session)
    assert len(degraded) == 1
    query = degraded[0].args[0]
    row = degraded[0].kwargs["degraded_rows"][0]

    # The child is attached to the affected CI (the CI whose metric failed).
    assert "MATCH (n:CI {id: row.node_id})" in query
    assert "MERGE (n)-[:HAS_EVENT]->(created)" in query
    assert row["node_id"] == AFFECTED_CI_ID

    # The root cause stays the ROOT CI. The PhysicalLink id is carried in its
    # own field and never leaks into root_cause_ci_id.
    assert row["root_cause_ci_id"] == ROOT_CI_ID
    assert row["root_cause_ci_id"] != row["link_id"]
    assert row["link_id"] == LINK_ID
    assert row["propagated_from"] == ROOT_EVENT_ID


# ---------------------------------------------------------------------------
# Rule 3 — idempotency
# ---------------------------------------------------------------------------


def test_degraded_child_write_reuses_the_existing_deduplication_machinery():
    """The child write reuses OPTIONAL MATCH + head(collect) + FOREACH(CREATE)."""
    session = _session()

    _refresh(session, [_collection_failure_row()], _cache_with_link("UNKNOWN"))

    query = _degraded_calls(session)[0].args[0]

    assert "OPTIONAL MATCH" in query
    assert "head(collect(existing))" in query
    assert "FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |" in query
    assert "FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |" in query
    # The existing-child matcher is scoped to the same root Event, so a
    # repeated poll updates the child instead of creating a second one.
    assert "existing.propagated_from = row.propagated_from" in query
    assert "existing.event_type = row.event_type" in query


def test_the_same_failure_observed_twice_in_one_batch_yields_a_single_child():
    """A duplicated observation in one cycle must not produce two child Events."""
    session = _session()
    row = _collection_failure_row()

    _refresh(session, [row, dict(row)], _cache_with_link("UNKNOWN"))

    degraded = _degraded_calls(session)
    assert len(degraded) == 1
    assert len(degraded[0].kwargs["degraded_rows"]) == 1


# ---------------------------------------------------------------------------
# Rule 4 — a pure-CI parent keeps the legacy behaviour
# ---------------------------------------------------------------------------


def test_pure_ci_parent_keeps_the_legacy_behaviour_and_creates_no_child_event():
    """No link metadata ⇒ the legacy ROOT enrichment only, no child Event."""
    session = _session()
    legacy_cache = {
        (AFFECTED_CI_ID, METRIC_ID): {
            "parent_event_id": ROOT_EVENT_ID,
            "root_cause_ci_id": ROOT_CI_ID,
        }
    }

    _refresh(session, [_collection_failure_row()], legacy_cache)

    assert _degraded_calls(session) == []
    enrichment = _root_enrichment_calls(session)
    assert len(enrichment) == 1
    assert enrichment[0].kwargs["propagated_rows"][0]["node_id"] == AFFECTED_CI_ID


# ---------------------------------------------------------------------------
# Rule 5 — an UP link propagates without degrading
# ---------------------------------------------------------------------------


def test_up_physical_link_propagates_without_degrading_the_severity():
    """A confirmed-up link keeps the parent's severity — no degraded child."""
    session = _session()

    _refresh(session, [_collection_failure_row()], _cache_with_link("UP"))

    assert _degraded_calls(session) == []
    assert _root_enrichment_calls(session), "the legacy ROOT enrichment must still run"


# ---------------------------------------------------------------------------
# Rule 6 — the child write runs under the event-writer triplet lock
# ---------------------------------------------------------------------------


def test_degraded_child_write_runs_under_the_event_writer_triplet_lock():
    """The (ci, metric, event_type) triplet lock is held before the child write."""
    session = _session()
    lock_db = MagicMock()
    call_order: list[str] = []

    def capture_lock(_lock_db, ci_id, metric_id, event_type, *, writer_context):
        call_order.append(f"lock:{ci_id}|{metric_id}|{event_type}")

    original_run = session.run

    def tracking_run(query, **params):
        if "degraded_rows" in params:
            call_order.append("neo4j:degraded")
        return original_run(query, **params)

    session.run = tracking_run

    with patch("engines.snmp_worker.acquire_event_triplet_lock", side_effect=capture_lock):
        _refresh(
            session,
            [_collection_failure_row()],
            _cache_with_link("UNKNOWN"),
            lock_db=lock_db,
        )

    assert f"lock:{AFFECTED_CI_ID}|{METRIC_ID}|COLLECTION_FAILURE" in call_order
    assert "neo4j:degraded" in call_order
    assert call_order.index(
        f"lock:{AFFECTED_CI_ID}|{METRIC_ID}|COLLECTION_FAILURE"
    ) < call_order.index("neo4j:degraded")


# ---------------------------------------------------------------------------
# Rule 7 — the policy comes from the contract module
# ---------------------------------------------------------------------------


def test_degradation_policy_is_read_from_the_correlation_contract(monkeypatch):
    """The contract helper decides whether the severity is degraded."""
    monkeypatch.setattr(
        snmp_worker,
        "should_propagate_unknown_severity_degrade",
        lambda: False,
    )
    session = _session()

    _refresh(session, [_collection_failure_row()], _cache_with_link("UNKNOWN"))

    assert _degraded_calls(session) == []


def test_the_policy_literal_never_appears_in_the_worker_source():
    """REQ-CORR-PROP-5: the decision string lives only in the contract module."""
    source = SNMP_WORKER_SOURCE.read_text(encoding="utf-8")

    assert "degrade_severity_and_propagate" not in source
    assert "services.correlation_propagation_contract" in source


# ---------------------------------------------------------------------------
# Rule 8 — the child write can never touch the ROOT Event
# ---------------------------------------------------------------------------


def test_degraded_child_write_can_never_match_or_reseverity_the_root_event():
    """The existing-event matcher only accepts a PROPAGATED child."""
    session = _session()

    _refresh(session, [_collection_failure_row()], _cache_with_link("UNKNOWN"))

    query = _degraded_calls(session)[0].args[0]

    assert "coalesce(existing.correlation_type, 'ROOT') = 'PROPAGATED'" in query
    assert "MATCH (root:Event" not in query
    assert "root.affected_ci_ids" not in query


# ---------------------------------------------------------------------------
# Rule 9 — the refresh never erases an operator acknowledgement
# ---------------------------------------------------------------------------


def test_degraded_child_write_never_erases_an_operator_acknowledgement():
    """An ACKed degraded child stays ACKed when the next poll refreshes it.

    The worker polls every few seconds; resetting the ack flag on every poll
    would silently discard the operator's acknowledgement, and resetting the
    status to OPEN would produce a state (OPEN + ack) the codebase never
    creates — acknowledging an Event sets ``status = 'ACK'``.
    """
    session = _session()

    _refresh(session, [_collection_failure_row()], _cache_with_link("UNKNOWN"))

    query = _degraded_calls(session)[0].args[0]

    # The ack flag is never cleared unconditionally ...
    assert "existing.ack = false" not in query
    # ... and the previous status drives both the status and the ack.
    assert "previous_status = 'ACK'" in query
    assert "existing.status = 'OPEN'" not in query


# ---------------------------------------------------------------------------
# Rule 10 — a failing child write never aborts the polling cycle
# ---------------------------------------------------------------------------


def test_degraded_child_write_failure_does_not_abort_the_cycle(caplog, monkeypatch):
    """A Neo4j error on the child write is logged, not raised."""
    # The test environment stubs ``neo4j.exceptions`` with a MagicMock, so the
    # undefined-parameter guard needs a real exception class to work with.
    monkeypatch.setattr(
        "services.neo4j_write_guard._CLIENT_ERROR_CLASS",
        RuntimeError,
        raising=False,
    )
    session = _session()
    original_run = session.run

    def failing_run(query, **params):
        if "degraded_rows" in params:
            raise RuntimeError("neo4j unavailable")
        return original_run(query, **params)

    session.run = MagicMock(side_effect=failing_run)

    with caplog.at_level(logging.WARNING):
        _refresh(session, [_collection_failure_row()], _cache_with_link("UNKNOWN"))

    assert "topology_rca_degraded_propagated_write_failed" in caplog.text
    assert _root_enrichment_calls(session), "the legacy ROOT enrichment must still run"


# ---------------------------------------------------------------------------
# Rule 12 — a ROOT write never clobbers a PROPAGATED child
# ---------------------------------------------------------------------------


class _FakeClientError(Exception):
    """Real exception class so the undefined-parameter guard can be exercised."""

    def __init__(self, message=""):
        super().__init__(message)
        self.message = message


def test_collection_failure_root_write_never_clobbers_a_propagated_child(monkeypatch):
    """The collection-failure ROOT matcher must skip PROPAGATED events.

    The collection-failure ROOT write selects an existing event by
    ``(ci_id, metric_id)`` only. Without a correlation-type guard it can pick a
    PROPAGATED child — including the degraded child this slice creates — and
    overwrite its severity and message, which would erase the explicit
    WARNING downgrade. The availability, latency, jitter and packet-loss
    families already carry the guard; the collection-failure family was the
    only gap.
    """
    root_row = {
        "node_id": AFFECTED_CI_ID,
        "metric_id": METRIC_ID,
        "severity": "CRITICAL",
        "message": "Metric Collection Failed: timeout",
        "event_type": "COLLECTION_FAILURE",
        "failure_family": "SNMP_NO_RESPONSE",
        "source_protocol": "SNMP",
    }

    session = _session()
    _refresh(session, [dict(root_row)], {})
    root_calls = [call for call in session.run.call_args_list if "failures" in call.kwargs]
    assert root_calls, "expected the collection-failure ROOT write"
    assert "coalesce(existing.correlation_type, 'ROOT') = 'ROOT'" in root_calls[0].args[0]

    # The fallback query must carry the same guard.
    monkeypatch.setattr(
        "services.neo4j_write_guard._CLIENT_ERROR_CLASS",
        _FakeClientError,
        raising=False,
    )
    fallback_session = MagicMock()
    raised = {"done": False}

    def fallback_run(query, **params):
        if "UNWIND $failures" in query and not raised["done"]:
            raised["done"] = True
            raise _FakeClientError("Variable poll_collector_id not defined")
        return MagicMock()

    fallback_session.run = MagicMock(side_effect=fallback_run)
    _refresh(fallback_session, [dict(root_row)], {})
    assert fallback_session.run.call_count == 2
    fallback_query = fallback_session.run.call_args_list[1].args[0]
    assert "coalesce(existing.correlation_type, 'ROOT') = 'ROOT'" in fallback_query


# ---------------------------------------------------------------------------
# Rule 11 — every event family uses the same degraded-child machinery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("refresh_name", "row"),
    [
        (
            "_refresh_snmp_collection_failures",
            {
                "node_id": AFFECTED_CI_ID,
                "metric_id": METRIC_ID,
                "severity": "CRITICAL",
                "message": "Metric Collection Failed: timeout",
                "event_type": "COLLECTION_FAILURE",
                "failure_family": "SNMP_NO_RESPONSE",
                "source_protocol": "SNMP",
            },
        ),
        (
            "_refresh_icmp_availability_events",
            {
                "node_id": AFFECTED_CI_ID,
                "metric_id": METRIC_ID,
                "protocol": "ICMP",
                "source_protocol": "ICMP",
                "availability_source": "PING",
                "event_type": "AVAILABILITY",
                "severity": "CRITICAL",
                "message": "Service/Host Down: PING-CHECK",
                "value": 0.0,
            },
        ),
        (
            "_refresh_icmp_latency_events",
            {
                "node_id": AFFECTED_CI_ID,
                "metric_id": "icmp_latency_ms",
                "protocol": "ICMP",
                "source_protocol": "ICMP",
                "event_type": "THRESHOLD_BREACH",
                "status": "CRITICAL",
                "message": "Latency breach",
            },
        ),
    ],
)
def test_every_event_family_emits_the_degraded_child(refresh_name, row):
    """Collection failure, availability and threshold breach share the machinery."""
    session = _session()

    getattr(snmp_worker, refresh_name)(
        session,
        [dict(row)],
        cache=_cache_with_link("UNKNOWN", metric_id=row["metric_id"]),
    )

    degraded = _degraded_calls(session)
    assert len(degraded) == 1, f"{refresh_name} must emit one degraded child"
    assert degraded[0].kwargs["degraded_rows"][0]["severity"] == "WARNING"
    assert degraded[0].kwargs["degraded_rows"][0]["event_type"] == row["event_type"]
