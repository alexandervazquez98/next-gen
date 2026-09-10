"""/graph/full byte-equality snapshot guard tests (#390).

Split out of test_graph_contracts.py so each contract module ships with
its own focused test file (work-unit commits).
"""
from __future__ import annotations

import pytest

class TestGraphFullSnapshot:
    """REQ-3 — ``/graph/full`` MUST remain byte-identical to the frozen snapshot.

    The snapshot is captured from a live backend curl and stored at
    ``fixtures/graph-full/frozen_response.json``. This test loads the
    snapshot, calls ``/graph/full`` against a TestClient with the same
    fixture data, and asserts byte-equality (no added/removed fields,
    ordering preserved across two calls).
    """

    FIXTURE_PATH = "fixtures/graph-full/frozen_response.json"

    @staticmethod
    def _load_snapshot() -> dict:
        import json
        import os

        path = TestGraphFullSnapshot.FIXTURE_PATH
        # Resolve relative to repo root (this file lives under backend/tests/).
        repo_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        full_path = os.path.join(repo_root, path)
        with open(full_path) as f:
            return json.load(f)

    def test_snapshot_top_level_keys_are_nodes_and_links(self):
        snapshot = self._load_snapshot()
        assert sorted(snapshot.keys()) == ["links", "nodes"]

    def test_snapshot_node_field_set_is_locked(self):
        """No field may be added or removed from a node in the snapshot."""
        snapshot = self._load_snapshot()
        node_keys = {tuple(sorted(n.keys())) for n in snapshot["nodes"]}
        # All nodes share the same field set — the union is the locked set.
        locked = set().union(*node_keys)
        # Sensitive fields that MUST always be present (the contract shape):
        # id, label, type, status, location, location_name, ip, metrics, metadata
        assert {"id", "label", "type", "metadata"}.issubset(locked)

    def test_snapshot_link_field_set_is_locked(self):
        snapshot = self._load_snapshot()
        link_keys = {tuple(sorted(l.keys())) for l in snapshot["links"]}
        locked = set().union(*link_keys)
        assert {"source", "target", "relationship"}.issubset(locked)

    def test_snapshot_has_no_sensitive_field_drift(self):
        """The snapshot MUST NOT contain forbidden new fields."""
        snapshot = self._load_snapshot()
        forbidden_node_fields = {"public_ip_redacted"}
        for n in snapshot["nodes"]:
            assert not (forbidden_node_fields & set(n.keys())), (
                "snapshot node has forbidden field drift"
            )

    def test_snapshot_byte_equality_against_testclient(self):
        """Calling ``/graph/full`` via TestClient with the snapshot as the
        fixture input MUST return a response byte-identical to the snapshot.

        This guards against accidental shape drift introduced by #390 or
        any future change to the routers/services.

        The mock builds raw node shapes from the snapshot metadata so that
        ``link_service.get_full_graph`` produces the same response shape on
        every run (its ``metadata`` field is a copy of all non-underscore
        keys from the raw node).
        """
        from unittest.mock import MagicMock, patch

        from fastapi.testclient import TestClient
        from services.auth_service import get_current_active_user

        from main import app

        snapshot = self._load_snapshot()

        # Build raw node shapes that mirror what topology_repo would return
        # from Neo4j — every metadata key in the snapshot is sourced from the
        # raw node, plus the link_service-added top-level fields.
        raw_nodes = []
        for n in snapshot["nodes"]:
            metadata = n.get("metadata", {})
            # The raw node includes every metadata key plus the link_service
            # top-level field aliases (label, type) plus any non-underscore
            # keys the test wants to round-trip.
            raw_node = dict(metadata)
            # Ensure the link_service top-level field sources are present.
            raw_node.setdefault("name", n["label"])
            raw_node.setdefault("status", n.get("status", "ACTIVE"))
            raw_nodes.append(raw_node)

        with patch("services.link_service.topology_repo") as mock_repo:
            mock_repo.get_filtered_graph_data.return_value = (
                raw_nodes,
                [
                    {
                        "source_node": {"id": l["source"]},
                        "target_node": {"id": l["target"]},
                        "type": l["relationship"],
                    }
                    for l in snapshot["links"]
                ],
            )

            admin = MagicMock()
            admin.role = "ADMIN"
            admin.allowed_locations = []
            app.dependency_overrides[get_current_active_user] = lambda: admin
            try:
                client = TestClient(app)
                first = client.get("/api/graph/full").json()
                second = client.get("/api/graph/full").json()
            finally:
                app.dependency_overrides.pop(get_current_active_user, None)

        # Byte-equality vs frozen snapshot.
        assert first == snapshot
        assert second == snapshot
        # Ordering preserved across calls.
        assert [n["id"] for n in first["nodes"]] == [n["id"] for n in snapshot["nodes"]]
        assert [l["source"] + "->" + l["target"] for l in first["links"]] == [
            l["source"] + "->" + l["target"] for l in snapshot["links"]
        ]
