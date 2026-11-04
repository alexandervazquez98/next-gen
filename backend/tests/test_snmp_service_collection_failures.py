import importlib
import sys
from unittest.mock import MagicMock, patch

from tests.conftest import MockNeo4jDriver


def _load_snmp_service_module():
    sys.modules.pop("services.snmp_service", None)
    return importlib.import_module("services.snmp_service")


def _make_context_mock():
    """Build a MagicMock that supports the ``with`` statement and returns
    itself from ``__enter__``.

    Used by tests that patch ``services.snmp_service.SessionLocal`` after the
    #322 restructure moved metric persistence into a single
    ``with SessionLocal() as pg_db:`` block.
    """
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    return fake


def test_snmp_collection_failure_on_critical_metric_is_warning_with_discriminators(
    mock_neo4j_driver,
):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    fake_pg = _make_context_mock()

    with patch("services.snmp_service.SessionLocal", return_value=fake_pg):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "ifInOctets", "name": "ifInOctets", "protocol": "SNMP", "criticality": 3},
            None,
            "TIMEOUT",
            "No SNMP response received before timeout",
            mock_neo4j_driver,
        )

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert create_event["params"]["sev"] == "WARNING"
    assert create_event["params"]["event_type"] == "COLLECTION_FAILURE"
    assert create_event["params"]["failure_family"] == "SNMP_NO_RESPONSE"
    assert create_event["params"]["source_protocol"] == "SNMP"


def test_snmp_generic_error_is_not_labeled_no_response(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    fake_pg = _make_context_mock()

    with patch("services.snmp_service.SessionLocal", return_value=fake_pg):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "ifInOctets", "name": "ifInOctets", "protocol": "SNMP", "criticality": 3},
            None,
            "ERROR",
            "could not convert string to float",
            mock_neo4j_driver,
        )

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert create_event["params"]["sev"] == "CRITICAL"
    assert create_event["params"]["event_type"] == "COLLECTION_FAILURE"
    assert create_event["params"]["failure_family"] is None


def test_snmp_valid_value_recovers_only_collection_failure(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cpu", "name": "cpu", "protocol": "SNMP", "criticality": 3},
            "42",
            "OK",
            None,
            mock_neo4j_driver,
        )

    queries = "\n".join(q["query"] for q in mock_neo4j_driver.mock_session.queries)
    assert "COLLECTION_FAILURE" in queries
    assert "Metric Collection Failed:" in queries
    assert "THRESHOLD_BREACH" not in queries


def test_snmp_threshold_breach_uses_threshold_event_type_not_collection_failure(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {
                "id": "cpu",
                "name": "cpu",
                "protocol": "SNMP",
                "criticality": 3,
                "critical": 90,
                "operator": ">=",
            },
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert create_event["params"]["sev"] == "CRITICAL"
    assert create_event["params"]["event_type"] == "THRESHOLD_BREACH"
    assert create_event["params"]["failure_family"] is None


def test_snmp_threshold_breach_still_recovers_existing_collection_failure(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {
                "id": "cpu",
                "name": "cpu",
                "protocol": "snmp",
                "criticality": 3,
                "critical": 90,
                "operator": ">=",
            },
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    recovery_queries = [
        q
        for q in session.queries
        if "SET e.status = 'RECOVERED'" in q["query"] and "COLLECTION_FAILURE" in q["query"]
    ]
    assert (
        recovery_queries
    ), "valid SNMP values must recover collection failures before threshold handling"
    assert "coalesce(m.can_propagate, true) = true" in recovery_queries[0]["query"]
    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert create_event["params"]["event_type"] == "THRESHOLD_BREACH"


def test_repeated_collection_failure_updates_exact_matched_event(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response(
        "MATCH (existing:Event)",
        [{"existing_status": "OPEN", "existing_element_id": "element-collection"}],
    )

    fake_pg = _make_context_mock()

    with patch("services.snmp_service.SessionLocal", return_value=fake_pg):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "ifInOctets", "name": "ifInOctets", "protocol": "SNMP", "criticality": 3},
            None,
            "TIMEOUT",
            "No SNMP response received before timeout",
            mock_neo4j_driver,
        )

    lookup_event = next(q for q in session.queries if "MATCH (existing:Event)" in q["query"])
    assert (
        "$failure_family IS NULL OR existing.failure_family = $failure_family"
        not in lookup_event["query"]
    )
    assert "$failure_family IS NULL AND existing.failure_family IS NULL" in lookup_event["query"]
    assert "$failure_family IS NOT NULL" in lookup_event["query"]
    update_event = next(
        q for q in session.queries if "elementId(existing) = $existing_element_id" in q["query"]
    )
    assert update_event["params"]["existing_element_id"] == "element-collection"
    assert "existing.status = $old_status" not in update_event["query"]


def test_non_breach_value_recovers_non_collection_events(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {"id": "cpu", "name": "cpu", "protocol": "SNMP", "criticality": 3, "critical": 90},
            "42",
            "OK",
            None,
            mock_neo4j_driver,
        )

    queries = "\n".join(q["query"] for q in mock_neo4j_driver.mock_session.queries)
    assert "e.event_type <> 'COLLECTION_FAILURE'" in queries
    assert (
        "NOT (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')"
        in queries
    )


def test_valid_non_snmp_threshold_breach_recovers_collection_failures(mock_neo4j_driver):
    snmp_service = _load_snmp_service_module()
    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])
    fake_pg = MagicMock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {
                "id": "cli-health",
                "name": "cli-health",
                "protocol": "CLI",
                "criticality": 3,
                "critical": 90,
            },
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    recovery_queries = [
        q
        for q in session.queries
        if "SET e.status = 'RECOVERED'" in q["query"] and "Metric Collection Failed:" in q["query"]
    ]
    assert (
        recovery_queries
    ), "valid non-SNMP samples must recover collection failures even when breaching"
    assert "toUpper(e.source_protocol) = $source_protocol" in recovery_queries[0]["query"]
    assert (
        "e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:'"
        in recovery_queries[0]["query"]
    )


def test_poll_metric_non_timeout_error_indication_returns_error_not_timeout():
    snmp_service = _load_snmp_service_module()

    with patch(
        "services.snmp_service.getCmd",
        return_value=iter([("authorization failure", None, None, [])]),
    ):
        value, status, error = snmp_service.poll_metric(
            {"id": "ci-1", "ip": "10.0.0.1"},
            {"id": "ifInOctets", "protocol": "SNMP", "oid": "1.2.3"},
            {"readCommunity": "public", "port": 161},
        )

    assert value is None
    assert status == "ERROR"
    assert error == "authorization failure"


def test_poll_metric_timeout_error_indication_returns_timeout():
    snmp_service = _load_snmp_service_module()

    with patch(
        "services.snmp_service.getCmd",
        return_value=iter([("No SNMP response received before timeout", None, None, [])]),
    ):
        value, status, error = snmp_service.poll_metric(
            {"id": "ci-1", "ip": "10.0.0.1"},
            {"id": "ifInOctets", "protocol": "SNMP", "oid": "1.2.3"},
            {"readCommunity": "public", "port": 161},
        )

    assert value is None
    assert status == "TIMEOUT"
    assert error == "No SNMP response received before timeout"


# ---------------------------------------------------------------------------
# #322 / PR2 — pg_advisory_xact_lock wiring + session-lifetime restructure
# (tasks 5.1 / 5.2). Two positive flipped assertions, replacing the old
# implicit assumption that pg_db closed before the Neo4j session started.
# ---------------------------------------------------------------------------


def test_store_metric_result_keeps_pg_session_open_during_neo4j_write(mock_neo4j_driver):
    """#322 / design §3 — the PG session MUST stay open across the Neo4j write.

    Current state: ``pg_db.close()`` is called at line 431 BEFORE the Neo4j
    ``driver.session()`` block at line 433. This would release the
    ``pg_advisory_xact_lock`` lock BEFORE the Neo4j read-then-create block,
    defeating the cross-writer serialization guarantee.

    Required state: one ``with SessionLocal() as pg_db:`` block wraps BOTH
    the Timescale metric insert AND the Neo4j write. The PG context exits
    AFTER the Neo4j write completes.
    """
    import services.snmp_service as snmp_service

    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    fake_pg = _make_context_mock()
    call_order: list[str] = []

    def pg_enter(_self=None, *_args, **_kwargs):
        call_order.append("pg_enter")
        return fake_pg

    def pg_exit(_self=None, *_args):
        call_order.append("pg_exit")
        return False

    fake_pg.__enter__ = pg_enter
    fake_pg.__exit__ = pg_exit

    original_run = session.run

    def tracking_run(query, **params):
        call_order.append("neo4j_run")
        return original_run(query, **params)

    session.run = tracking_run

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {
                "id": "cpu",
                "name": "cpu",
                "protocol": "SNMP",
                "criticality": 3,
                "critical": 90,
                "operator": ">=",
            },
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    # The PG context MUST be entered BEFORE the Neo4j write.
    assert "pg_enter" in call_order, "pg context was never entered"
    assert "neo4j_run" in call_order, "neo4j session.run never executed"
    assert call_order.index("pg_enter") < call_order.index(
        "neo4j_run"
    ), f"pg context enter must precede neo4j run; order={call_order}"

    # The PG context MUST NOT exit BEFORE the Neo4j write completes —
    # otherwise the advisory lock would be released mid-transaction.
    assert "pg_exit" in call_order, "pg context was never exited"
    assert call_order.index("pg_exit") > call_order.index("neo4j_run"), (
        f"pg context exited BEFORE neo4j run (lock released too early); " f"order={call_order}"
    )


def test_store_metric_result_acquires_pg_advisory_lock_before_neo4j_read(mock_neo4j_driver):
    """#322 / design §3-§4 — POSITIVE flipped assertion.

    ``store_metric_result`` MUST call ``acquire_event_triplet_lock`` with
    the open PG session and the (ci_id, metric_id, event_type) triplet
    BEFORE the Neo4j read at line 493. Otherwise concurrent writers can
    create duplicate OPEN Events for the same triplet.
    """
    import services.snmp_service as snmp_service

    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    fake_pg = _make_context_mock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
        patch("services.snmp_service.acquire_event_triplet_lock") as mock_lock,
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {
                "id": "cpu",
                "name": "cpu",
                "protocol": "SNMP",
                "criticality": 3,
                "critical": 90,
                "operator": ">=",
            },
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    assert mock_lock.call_count >= 1, "acquire_event_triplet_lock was never called"

    # Locate the call that matches the breach triplet (ci-1, cpu, THRESHOLD_BREACH).
    matching = [
        call
        for call in mock_lock.call_args_list
        if len(call.args) >= 4
        and call.args[1] == "ci-1"
        and call.args[2] == "cpu"
        and call.args[3] == "THRESHOLD_BREACH"
    ]
    assert matching, (
        f"no acquire_event_triplet_lock call with triplet (ci-1, cpu, THRESHOLD_BREACH); "
        f"got calls={mock_lock.call_args_list!r}"
    )
    # The first matching call MUST use the open PG session as the lock target.
    assert (
        matching[0].args[0] is fake_pg
    ), f"lock helper must receive the writer's open PG session; got {matching[0].args[0]!r}"
    assert matching[0].kwargs["writer_context"] == "snmp_service"


def test_store_metric_result_persists_poll_collector_id_on_event_create(mock_neo4j_driver):
    """#322 / spec §Poll collector identity persistence — every Event CREATE
    MUST include ``poll_collector_id`` so the host that observed the failure
    is recorded for forensic correlation.
    """
    import services.snmp_service as snmp_service

    session = mock_neo4j_driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    fake_pg = _make_context_mock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
    ):
        snmp_service.store_metric_result(
            {"id": "ci-1", "ip": "10.0.0.1", "name": "Router"},
            {
                "id": "cpu",
                "name": "cpu",
                "protocol": "SNMP",
                "criticality": 3,
                "critical": 90,
                "operator": ">=",
            },
            "97",
            "OK",
            None,
            mock_neo4j_driver,
        )

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    assert (
        "poll_collector_id" in create_event["query"]
    ), f"poll_collector_id MUST be set in CREATE clause; query={create_event['query']!r}"
    assert create_event["params"].get("poll_collector_id"), (
        f"poll_collector_id MUST be passed as a non-empty parameter; "
        f"params={create_event['params']!r}"
    )
    from services.snmp_service import POLL_COLLECTOR_ID

    assert create_event["params"]["poll_collector_id"] == POLL_COLLECTOR_ID, (
        f"poll_collector_id MUST match the cached POLL_COLLECTOR_ID; "
        f"got={create_event['params']['poll_collector_id']!r}, expected={POLL_COLLECTOR_ID!r}"
    )


# ---------------------------------------------------------------------------
# feat-539 / T5 — the legacy SNMP path must produce the SAME degraded
# ``PROPAGATED`` child as the modern SNMP worker.
#
# Locked decision #1 of issue #539 (``degrade_severity_and_propagate``): a
# propagation that crosses a PhysicalLink whose status is ``UNKNOWN`` is
# materialized as a ``PROPAGATED`` Event at ``WARNING`` severity, carrying the
# four degradation markers. The ROOT Event keeps its own severity and the
# child's ``root_cause_ci_id`` keeps pointing at the ROOT CI — never at the
# PhysicalLink.
#
# Before this slice the legacy path created the ``PROPAGATED`` child with the
# metric's own severity and no markers at all, so the same failure produced
# two children with two severities depending on which engine ran.
# ---------------------------------------------------------------------------

LEGACY_ROOT_CI_ID = "ci-root"
LEGACY_AFFECTED_CI_ID = "ci-child"
LEGACY_ROOT_EVENT_ID = "evt-root"
LEGACY_LINK_ID = "pl-unknown-1"
LEGACY_METRIC_ID = "cpu"


def _unknown_link_parent():
    """The correlation result of a crossing over an ``UNKNOWN`` PhysicalLink."""
    return {
        "parent_event_id": LEGACY_ROOT_EVENT_ID,
        "root_cause_ci_id": LEGACY_ROOT_CI_ID,
        "correlation_type": "ROOT",
        "link_id": LEGACY_LINK_ID,
        "link_status": "UNKNOWN",
    }


def _legacy_store_metric_result(driver, parent=None):
    """Drive the legacy SNMP writer for one breaching metric.

    ``parent`` is the correlation result the topology lookup returns; ``None``
    means the CI has no open parent event (the pre-#539 ROOT case).
    """
    snmp_service = _load_snmp_service_module()
    session = driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    fake_pg = _make_context_mock()

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
        patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=parent,
        ),
    ):
        snmp_service.store_metric_result(
            {"id": LEGACY_AFFECTED_CI_ID, "ip": "10.0.0.2", "name": "Switch"},
            {
                "id": LEGACY_METRIC_ID,
                "name": "cpu",
                "protocol": "SNMP",
                "criticality": 3,
                "critical": 90,
                "operator": ">=",
            },
            "97",
            "OK",
            None,
            driver,
        )
    return session


def test_legacy_path_creates_a_degraded_warning_propagated_child(mock_neo4j_driver):
    """An ``UNKNOWN`` crossing yields a ``WARNING`` child with the four markers."""
    session = _legacy_store_metric_result(mock_neo4j_driver, _unknown_link_parent())

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    params = create_event["params"]

    assert params["correlation_type"] == "PROPAGATED"
    # The metric breached CRITICAL, but the crossing is not confirmed, so the
    # child is degraded to WARNING.
    assert params["sev"] == "WARNING"
    assert params["severity_degraded"] is True
    assert params["degradation_reason"] == "PHYSICAL_LINK_UNKNOWN"
    assert params["physical_link_id"] == LEGACY_LINK_ID
    assert params["physical_link_status"] == "UNKNOWN"


def test_legacy_degraded_child_names_the_root_ci_and_never_the_physical_link(
    mock_neo4j_driver,
):
    """The child stays on the affected CI and keeps the ROOT CI as its root cause."""
    session = _legacy_store_metric_result(mock_neo4j_driver, _unknown_link_parent())

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    params = create_event["params"]

    # The child is hosted by the affected CI (the CI whose metric failed).
    assert params["nid"] == LEGACY_AFFECTED_CI_ID
    # The root cause is the ROOT CI; the PhysicalLink id lives in its own
    # marker field and never leaks into root_cause_ci_id.
    assert params["root_cause_ci_id"] == LEGACY_ROOT_CI_ID
    assert params["propagated_from"] == LEGACY_ROOT_EVENT_ID
    assert params["root_cause_ci_id"] != params["physical_link_id"]


def test_legacy_degraded_child_is_idempotent_and_keeps_the_operator_acknowledgement(
    mock_neo4j_driver,
):
    """A repeated poll updates the same child and never erases its degradation."""
    first = _legacy_store_metric_result(mock_neo4j_driver, _unknown_link_parent())
    first_create = next(q for q in first.queries if "CREATE (e:Event" in q["query"])
    assert first_create["params"]["sev"] == "WARNING"

    # Second poll: the child already exists and the operator acknowledged it.
    second_driver = MockNeo4jDriver()
    second_session = second_driver.mock_session
    second_session.set_response(
        "MATCH (existing:Event)",
        [{"existing_status": "ACK", "existing_element_id": "el-degraded"}],
    )
    second_session.set_response("MATCH (ci:CI", [])

    snmp_service = _load_snmp_service_module()
    fake_pg = _make_context_mock()
    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
        patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=_unknown_link_parent(),
        ),
    ):
        snmp_service.store_metric_result(
            {"id": LEGACY_AFFECTED_CI_ID, "ip": "10.0.0.2", "name": "Switch"},
            {
                "id": LEGACY_METRIC_ID,
                "name": "cpu",
                "protocol": "SNMP",
                "criticality": 3,
                "critical": 90,
                "operator": ">=",
            },
            "97",
            "OK",
            None,
            second_driver,
        )

    # The same failure observed twice yields ONE child: no second CREATE.
    assert [q for q in second_session.queries if "CREATE (e:Event" in q["query"]] == []

    update = next(
        q
        for q in second_session.queries
        if "elementId(existing) = $existing_element_id" in q["query"]
    )
    # The refreshed child keeps its degraded severity and its markers ...
    assert update["params"]["sev"] == "WARNING"
    assert update["params"]["severity_degraded"] is True
    # ... and the operator acknowledgement survives the refresh.
    assert "previous_status = 'ACK'" in update["query"]


def test_legacy_root_write_never_clobbers_a_degraded_child(mock_neo4j_driver):
    """The legacy existing-Event lookup is scoped by the correlation type.

    The modern SNMP worker already guards its ROOT write with
    ``coalesce(existing.correlation_type, 'ROOT') = 'ROOT'`` so a degraded
    ``PROPAGATED`` child can never be selected and re-severitied. The legacy
    path must use the same pattern, otherwise a later ROOT write for the same
    ``(ci_id, metric_id)`` selects the degraded child and erases its explicit
    ``WARNING`` downgrade.
    """
    session = _legacy_store_metric_result(mock_neo4j_driver, _unknown_link_parent())

    lookup = next(
        q
        for q in session.queries
        if "MATCH (existing:Event)" in q["query"] and "LIMIT 1" in q["query"]
    )
    assert "coalesce(existing.correlation_type, 'ROOT') = $correlation_type" in lookup["query"]
    assert lookup["params"]["correlation_type"] == "PROPAGATED"
