"""feat-539 / T5 — the degraded ``PROPAGATED`` child has ONE implementation.

Locked decision #1 of issue #539 (``degrade_severity_and_propagate``): a
propagation that crosses a PhysicalLink whose status is ``UNKNOWN`` is
materialized as a ``PROPAGATED`` Event at ``WARNING`` severity, carrying the
four degradation markers (``severity_degraded``, ``degradation_reason``,
``physical_link_id``, ``physical_link_status``). The ROOT Event keeps its own
severity and the child's ``root_cause_ci_id`` keeps pointing at the ROOT CI.

Three writers can materialize that Event:

* ``engines/snmp_worker.py``    — the modern SNMP worker (a SEPARATE child);
* ``services/snmp_service.py``  — the legacy SNMP path;
* ``polling/event_writer.py``   — the leased / queued writer.

Before this slice the decision lived in the modern worker only, so the legacy
path produced a second, un-degraded child for the same failure and the leased
writer wrote the envelope's severity verbatim. The rules pinned here:

1. The decision, the status literals and the degradation reason have ONE
   owner: the correlation contract, reached through the shared
   degraded-propagation module. No writer may hardcode them.
2. Every writer reads the policy from the contract, so switching the
   contract's decision off disables the degradation everywhere at once.
3. The three writers agree on the degraded child: the same severity and the
   same four markers.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import MockNeo4jDriver

ROOT_CI_ID = "ci-root"
AFFECTED_CI_ID = "ci-child"
ROOT_EVENT_ID = "evt-root"
LINK_ID = "pl-unknown-1"
METRIC_ID = "cpu"

WRITER_MODULES = (
    "engines/snmp_worker.py",
    "services/snmp_service.py",
    "polling/event_writer.py",
)
CONTRACT_SOURCE = (
    Path(__file__).resolve().parents[1] / "services" / ("correlation_propagation_contract.py")
)
SHARED_SOURCE = (
    Path(__file__).resolve().parents[1] / "services" / ("correlation_propagation_events.py")
)


# ---------------------------------------------------------------------------
# Rule 1 — the decision has one owner
# ---------------------------------------------------------------------------


def test_the_degradation_decision_has_a_single_owner():
    """No writer may hardcode the decision, the status or the reason."""
    backend_root = Path(__file__).resolve().parents[1]

    for relative in WRITER_MODULES:
        source = (backend_root / relative).read_text(encoding="utf-8")
        assert "degrade_severity_and_propagate" not in source, relative
        assert "PHYSICAL_LINK_UNKNOWN" not in source, relative
        # No writer may DEFINE the vocabulary — only the contract does.
        assert "DEGRADING_PHYSICAL_LINK_STATUS = " not in source, relative
        assert "DEGRADED_PROPAGATED_SEVERITY = " not in source, relative
        assert "DEGRADED_PROPAGATED_REASON = " not in source, relative
        # Every writer delegates to the shared implementation.
        assert "correlation_propagation_events" in source, relative

    # The bare degrading-status literal never appears in a writer either.
    # (``services/snmp_service.py`` has an unrelated CollectorStatus
    # fallback, so only the two writers with no other use are checked.)
    for relative in ("engines/snmp_worker.py", "polling/event_writer.py"):
        source = (backend_root / relative).read_text(encoding="utf-8")
        assert '"UNKNOWN"' not in source, relative

    shared_source = SHARED_SOURCE.read_text(encoding="utf-8")
    assert "degrade_severity_and_propagate" not in shared_source
    assert "PHYSICAL_LINK_UNKNOWN" not in shared_source
    assert "DEGRADING_PHYSICAL_LINK_STATUS = " not in shared_source
    # The shared module reads the policy from the contract.
    assert "correlation_propagation_contract" in shared_source

    contract_source = CONTRACT_SOURCE.read_text(encoding="utf-8")
    assert "degrade_severity_and_propagate" in contract_source
    assert "PHYSICAL_LINK_UNKNOWN" in contract_source


# ---------------------------------------------------------------------------
# Rule 2 — every writer reads the policy from the contract
# ---------------------------------------------------------------------------


def _legacy_child_params(driver, parent):
    """Run the legacy SNMP writer and return the created Event's parameters."""
    snmp_service = importlib.import_module("services.snmp_service")
    session = driver.mock_session
    session.set_response("MATCH (existing:Event)", [])
    session.set_response("MATCH (ci:CI", [])

    fake_pg = MagicMock()
    fake_pg.__enter__.return_value = fake_pg
    fake_pg.__exit__.return_value = False

    with (
        patch("services.snmp_service.SessionLocal", return_value=fake_pg),
        patch("services.snmp_service.insert_metric_value"),
        patch("repositories.topology_repo.find_open_parent_event", return_value=parent),
    ):
        snmp_service.store_metric_result(
            {"id": AFFECTED_CI_ID, "ip": "10.0.0.2", "name": "Switch"},
            {
                "id": METRIC_ID,
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

    create_event = next(q for q in session.queries if "CREATE (e:Event" in q["query"])
    return create_event["params"]


def _leased_row(driver):
    """Run the leased writer and return the breach row it wrote."""
    from polling.event_writer import batch_update_events

    batch_update_events(
        driver,
        [
            {
                "idempotency_key": None,
                "ci_id": AFFECTED_CI_ID,
                "metric_id": METRIC_ID,
                "protocol": "SNMP",
                "source": "10.0.0.2:161",
                "observed_at": None,
                "status": "OK",
                "value": {"numeric": 97.0, "raw": 97.0},
                "error": {"message": None},
                "metadata": {
                    "name": "cpu",
                    "criticality": 3,
                    "critical": 90,
                    "operator": ">=",
                    "correlation_type": "PROPAGATED",
                    "propagated_from": ROOT_EVENT_ID,
                    "root_cause_ci_id": ROOT_CI_ID,
                    "link_id": LINK_ID,
                    "link_status": "UNKNOWN",
                },
            }
        ],
    )

    breach_query = next(
        q
        for q in driver.mock_session.queries
        if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
    )
    return breach_query["params"]["rows"][0]


def _unknown_link_parent():
    return {
        "parent_event_id": ROOT_EVENT_ID,
        "root_cause_ci_id": ROOT_CI_ID,
        "correlation_type": "ROOT",
        "link_id": LINK_ID,
        "link_status": "UNKNOWN",
    }


def test_switching_the_contract_policy_off_disables_the_degradation_everywhere(monkeypatch):
    """The contract is the single switch every writer honours."""
    monkeypatch.setattr(
        "services.correlation_propagation_contract.should_propagate_unknown_severity_degrade",
        lambda: False,
    )

    legacy_params = _legacy_child_params(MockNeo4jDriver(), _unknown_link_parent())
    assert legacy_params["correlation_type"] == "PROPAGATED"
    assert legacy_params["sev"] == "CRITICAL"
    assert not legacy_params.get("severity_degraded")

    leased_row = _leased_row(MockNeo4jDriver())
    assert leased_row["correlation_type"] == "PROPAGATED"
    assert leased_row["severity"] == "CRITICAL"
    assert not leased_row.get("severity_degraded")


# ---------------------------------------------------------------------------
# Rule 3 — the three writers agree on the degraded child
# ---------------------------------------------------------------------------


def test_the_legacy_and_leased_writers_agree_on_the_degraded_child():
    """Same severity, same four markers, same root cause."""
    legacy_params = _legacy_child_params(MockNeo4jDriver(), _unknown_link_parent())
    leased_row = _leased_row(MockNeo4jDriver())

    assert legacy_params["sev"] == leased_row["severity"] == "WARNING"
    assert legacy_params["severity_degraded"] is True
    assert leased_row["severity_degraded"] is True
    assert legacy_params["degradation_reason"] == leased_row["degradation_reason"]
    assert legacy_params["physical_link_id"] == leased_row["physical_link_id"] == LINK_ID
    assert legacy_params["physical_link_status"] == leased_row["physical_link_status"]
    # The root cause is the ROOT CI on both writers, never the PhysicalLink.
    assert legacy_params["root_cause_ci_id"] == leased_row["root_cause_ci_id"] == ROOT_CI_ID
    assert legacy_params["root_cause_ci_id"] != LINK_ID
    assert leased_row["root_cause_ci_id"] != LINK_ID


# ---------------------------------------------------------------------------
# Rule 3 — the modern SNMP worker agrees with the other two writers
# ---------------------------------------------------------------------------


def _modern_worker_degraded_child():
    """Run the modern SNMP worker's public ``poll_snmp`` surface.

    Returns the degraded ``PROPAGATED`` child payload the worker wrote.
    """
    from unittest.mock import MagicMock

    import config as _config
    from tests.conftest import MockNeo4jSession

    def _poll_record(node_id):
        return {
            "node_id": node_id,
            "metric_id": METRIC_ID,
            "protocol": "ICMP",
            "ip": "192.168.1.1",
            "community": "public",
            "oid": None,
            "port": 161,
            "metric_name": METRIC_ID,
            "criticality": 3,
            "metric_kind": "availability",
            "availability_source": "PING",
            "interval": 60,
        }

    mock_session = MockNeo4jSession()
    mock_session.set_default_response([])
    mock_session.set_response(
        "match",
        [_poll_record(ROOT_CI_ID), _poll_record(AFFECTED_CI_ID)],
    )

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=None)

    rebuilt_cache = {
        (AFFECTED_CI_ID, METRIC_ID): {
            "parent_event_id": ROOT_EVENT_ID,
            "root_cause_ci_id": ROOT_CI_ID,
            "link_id": LINK_ID,
            "link_status": "UNKNOWN",
        }
    }

    icmp_settings = _config.get_icmp_settings().model_copy(update={"debounce_count": 1})

    with (
        patch("engines.snmp_worker.driver", mock_driver),
        patch("engines.snmp_worker.SessionLocal", return_value=MagicMock()),
        patch("engines.snmp_worker.bulk_insert_metrics"),
        patch("engines.snmp_worker.fetch_icmp_ping", return_value=0.0),
        patch("engines.snmp_worker.get_icmp_settings", return_value=icmp_settings),
        patch("engines.snmp_worker.build_open_parent_index", side_effect=[{}, rebuilt_cache]),
        patch(
            "engines.snmp_worker.get_topology_relations",
            return_value={AFFECTED_CI_ID: {ROOT_CI_ID}},
        ),
    ):
        from engines.snmp_worker import poll_snmp

        poll_snmp()

    degraded_calls = [call for call in mock_session.queries if "degraded_rows" in call["query"]]
    assert len(degraded_calls) == 1, "expected exactly one degraded-child write"
    rows = degraded_calls[0]["params"]["degraded_rows"]
    assert len(rows) == 1
    return rows[0]


def test_the_modern_worker_agrees_with_the_legacy_and_leased_writers():
    """The modern worker emits the same degraded child as the other two."""
    modern_row = _modern_worker_degraded_child()
    legacy_params = _legacy_child_params(MockNeo4jDriver(), _unknown_link_parent())
    leased_row = _leased_row(MockNeo4jDriver())

    # Same severity.
    assert modern_row["severity"] == legacy_params["sev"] == leased_row["severity"] == "WARNING"
    # Same degradation reason.
    assert (
        modern_row["degradation_reason"]
        == legacy_params["degradation_reason"]
        == leased_row["degradation_reason"]
        == "PHYSICAL_LINK_UNKNOWN"
    )
    # Same crossed PhysicalLink.
    assert (
        modern_row["link_id"]
        == legacy_params["physical_link_id"]
        == leased_row["physical_link_id"]
        == LINK_ID
    )
    assert (
        modern_row["link_status"]
        == legacy_params["physical_link_status"]
        == leased_row["physical_link_status"]
        == "UNKNOWN"
    )
    # Same root cause: the ROOT CI, never the PhysicalLink.
    assert (
        modern_row["root_cause_ci_id"]
        == legacy_params["root_cause_ci_id"]
        == leased_row["root_cause_ci_id"]
        == ROOT_CI_ID
    )
    assert modern_row["root_cause_ci_id"] != LINK_ID
