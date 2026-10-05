"""Regression test for tunnel polling byte-equivalence — feat-443 (PR2, slice 4/4).

REQ-PHYSLINK-UTIL-3: "backward-compat: tunnel link_service semantics
unchanged". The new PhysicalLink polling bridge MUST NOT perturb the
tunnel polling path.

TDD coverage (PR2): T18.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "true")


def _tunnel_topology():
    raw_nodes = [{"id": "ci-hub-a", "name": "Hub-A", "_labels": ["CI"], "layer": "vpn_hub"}]
    raw_links = [
        {
            "source_node": {"id": "ci-hub-a"},
            "target_node": {"id": "ci-edge-b"},
            "type": "CONNECTS_TO",
            "medium": "vpn",
        },
        {
            "source_node": {"id": "ci-hub-a"},
            "target_node": {"id": "ci-edge-b"},
            "type": "CONNECTS_TO",
            "medium": "sd_wan",
        },
    ]
    return raw_nodes, raw_links


# T18: link_service output is byte-equivalent before/after the bridge runs


def test_t18_link_service_get_full_graph_byte_equivalent_with_bridge_enabled(mock_neo4j_driver):
    from services import link_service

    raw_nodes, raw_links = _tunnel_topology()

    with patch("services.link_service.topology_repo") as mock_topo:
        mock_topo.get_filtered_graph_data.return_value = (raw_nodes, raw_links)
        before = link_service.get_full_graph(current_user=None)

    # Run the bridge (feature flag ON, fresh sample) on the test driver.
    bridge_driver = mock_neo4j_driver
    bridge_driver.mock_session.set_response(
        "match (pl:physicallink)",
        [
            {
                "id": "pl-fiber-01",
                "endpoints": ["ci-hub-a", "ci-edge-b"],
                "status": "UNKNOWN",
                "capacity_gbps": 10.0,
            }
        ],
    )
    fixed_now = datetime(2026, 10, 3, 20, 54, 37, tzinfo=UTC)

    import repositories.physical_link_repo as pl_repo_module
    from polling.physical_link_bridge import run_once
    from repositories import metric_repo

    pl_repo_module._physical_link_repo = None
    try:
        with (
            patch("database.driver", bridge_driver),
            patch("database.verify_connection", return_value=None),
            patch.object(
                metric_repo,
                "get_metric_window",
                lambda *a, **k: [{"time": fixed_now - timedelta(seconds=10), "value": 1.0}],
            ),
        ):
            run_once(
                type(
                    "S",
                    (),
                    {
                        "feature_enabled": True,
                        "fresh_window_seconds": 60,
                        "stale_after_seconds": 1800,
                    },
                )(),
                bridge_driver,
                fixed_now,
            )
    finally:
        # Reset the repo singleton so subsequent tests (alphabetically
        # after this file) get a fresh repo wired to their own driver.
        # The PhysicalLinkRepo caches the driver on first use; without
        # this reset, the PR1 bridge tests would inherit T18's driver.
        pl_repo_module._physical_link_repo = None

    with patch("services.link_service.topology_repo") as mock_topo:
        mock_topo.get_filtered_graph_data.return_value = (raw_nodes, raw_links)
        after = link_service.get_full_graph(current_user=None)

    # Byte-equivalence is the whole point of the regression test.
    assert before == after
    # The bridge must NOT touch tunnel Cypher (no :CONNECTED_VIA, no medium).
    for query in bridge_driver.mock_session.queries:
        lowered = query["query"].lower()
        assert "connected_via" not in lowered
        assert "r.medium" not in lowered
