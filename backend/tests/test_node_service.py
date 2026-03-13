"""
test_node_service.py

TDD tests for Issue #16 fixes in backend/services/node_service.py.

Scope:
  - Bug 2: get_nodes must include 'pollingInterval' in the returned node_data dict
  - Bug 1: get_nodes must include 'owner' at top level in node_data dict
  - create_update_node must pass owner and pollingInterval correctly to upsert_node

All Neo4j / topology_repo calls are mocked via unittest.mock so no live DB is needed.

NOTE: We use patch.object() throughout to avoid string-path resolution ambiguity
that arises from the backend/ sub-directory not being the pytest rootdir.
"""

import sys
import os

# ── Make backend packages importable without installing them ──────────────────
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Pre-import modules so patch.object() can reference them reliably
import repositories.topology_repo as topology_repo_mod
import services.node_service as node_service_mod
import services.auth_service as auth_service_mod

import pytest
from unittest.mock import patch, MagicMock
from models.core import Node


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_raw_node(overrides: dict | None = None) -> dict:
    """
    Return a dict that looks like a Neo4j node record as returned by
    topology_repo.get_nodes (the 'node' key inside each record).
    """
    base = {
        "id": "CI-TEST01",
        "name": "Test Router",
        "status": "ACTIVE",
        "ip": "10.0.0.1",
        "layer": "INFRASTRUCTURE",
        "owner": "NetOps",
        "brand": "Cisco",
        "model": "ASR-1001X",
        "serialNumber": "SN-TEST1234",
        "firmwareVersion": "17.6.4",
        "pollingInterval": 120,
        "snmp": None,
        "location": None,
        "location_name": "Madrid DC",
    }
    if overrides:
        base.update(overrides)
    return base


def _make_raw_record(node_overrides: dict | None = None) -> dict:
    """
    Return a full record dict as returned by topology_repo.get_nodes.
    Simulates: {"node": <Neo4j-node-dict>, "category": "...", "metrics": [...]}
    """
    node = _make_raw_node(node_overrides)
    return {
        "node": node,
        "category": "NETWORK",
        "metrics": [],
    }


def _make_admin_user() -> MagicMock:
    user = MagicMock()
    user.role = "ADMIN"
    user.allowed_locations = []
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Tests: get_nodes — pollingInterval (Bug 2)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetNodesPollingInterval:
    """Bug 2 — pollingInterval must be included in node_data returned by get_nodes."""

    def test_get_nodes_includes_polling_interval_in_result(self):
        """
        GIVEN a CI stored in Neo4j with pollingInterval=120
        WHEN get_nodes is called
        THEN the returned dict includes pollingInterval=120
        """
        raw_records = [_make_raw_record({"pollingInterval": 120})]

        with patch.object(topology_repo_mod, "get_nodes", return_value=raw_records):
            result = node_service_mod.get_nodes(_make_admin_user())

        assert len(result) == 1
        assert result[0]["pollingInterval"] == 120

    def test_get_nodes_polling_interval_defaults_to_60_when_absent(self):
        """
        GIVEN a CI stored in Neo4j with no pollingInterval property (None / missing)
        WHEN get_nodes is called
        THEN the returned dict has pollingInterval=60 (default)
        """
        raw_records = [_make_raw_record({"pollingInterval": None})]

        with patch.object(topology_repo_mod, "get_nodes", return_value=raw_records):
            result = node_service_mod.get_nodes(_make_admin_user())

        assert result[0]["pollingInterval"] == 60

    def test_get_nodes_polling_interval_preserved_at_custom_value(self):
        """
        GIVEN a CI with pollingInterval=300 (5 minutes)
        WHEN get_nodes is called
        THEN the returned dict has pollingInterval=300 (not overwritten to default)
        """
        raw_records = [_make_raw_record({"pollingInterval": 300})]

        with patch.object(topology_repo_mod, "get_nodes", return_value=raw_records):
            result = node_service_mod.get_nodes(_make_admin_user())

        assert result[0]["pollingInterval"] == 300


# ─────────────────────────────────────────────────────────────────────────────
# Tests: get_nodes — owner (Bug 1)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetNodesOwner:
    """Bug 1 — owner must be exposed at top level in node_data (not buried in metadata)."""

    def test_get_nodes_includes_owner_at_top_level(self):
        """
        GIVEN a CI with owner='NetOps' in Neo4j
        WHEN get_nodes is called
        THEN the returned dict has owner='NetOps' as a top-level key
        """
        raw_records = [_make_raw_record({"owner": "NetOps"})]

        with patch.object(topology_repo_mod, "get_nodes", return_value=raw_records):
            result = node_service_mod.get_nodes(_make_admin_user())

        assert result[0]["owner"] == "NetOps"

    def test_get_nodes_owner_is_none_when_not_set(self):
        """
        GIVEN a CI with no owner in Neo4j
        WHEN get_nodes is called
        THEN the returned dict has owner=None at top level
        """
        raw_records = [_make_raw_record({"owner": None})]

        with patch.object(topology_repo_mod, "get_nodes", return_value=raw_records):
            result = node_service_mod.get_nodes(_make_admin_user())

        assert result[0]["owner"] is None

    def test_get_nodes_owner_is_a_top_level_key_not_only_in_metadata(self):
        """
        GIVEN a CI with owner='SecOps'
        WHEN get_nodes is called
        THEN the 'owner' key is present at node_data root (not only inside metadata)
        """
        raw_records = [_make_raw_record({"owner": "SecOps"})]

        with patch.object(topology_repo_mod, "get_nodes", return_value=raw_records):
            result = node_service_mod.get_nodes(_make_admin_user())

        node_data = result[0]
        assert "owner" in node_data, "owner must be a top-level key in node_data"
        assert node_data["owner"] == "SecOps"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: get_nodes — serialNumber and firmwareVersion (Bugs 3 & 4 — backend side)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetNodesHardwareFields:
    """Bugs 3 & 4 — serialNumber and firmwareVersion already in node_data (pre-existing);
    this confirms they remain correctly populated after the Bug 1+2 fixes."""

    def test_get_nodes_includes_serial_number(self):
        """
        GIVEN a CI with serialNumber='SN-ABCD1234'
        WHEN get_nodes is called
        THEN the returned dict has serialNumber='SN-ABCD1234'
        """
        raw_records = [_make_raw_record({"serialNumber": "SN-ABCD1234"})]

        with patch.object(topology_repo_mod, "get_nodes", return_value=raw_records):
            result = node_service_mod.get_nodes(_make_admin_user())

        assert result[0]["serialNumber"] == "SN-ABCD1234"

    def test_get_nodes_includes_firmware_version(self):
        """
        GIVEN a CI with firmwareVersion='17.6.4'
        WHEN get_nodes is called
        THEN the returned dict has firmwareVersion='17.6.4'
        """
        raw_records = [_make_raw_record({"firmwareVersion": "17.6.4"})]

        with patch.object(topology_repo_mod, "get_nodes", return_value=raw_records):
            result = node_service_mod.get_nodes(_make_admin_user())

        assert result[0]["firmwareVersion"] == "17.6.4"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: create_update_node — owner and pollingInterval passed to upsert_node
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateUpdateNode:
    """Verify create_update_node correctly passes owner and pollingInterval to upsert_node."""

    def _make_node(self, **kwargs) -> Node:
        defaults = dict(
            id="CI-TEST01",
            label="Test Router",
            type="INFRASTRUCTURE",
            status="ACTIVE",
            ip="10.0.0.1",
            owner="NetOps",
            pollingInterval=120,
            serialNumber="SN-ABCD1234",
            firmwareVersion="17.6.4",
        )
        defaults.update(kwargs)
        return Node(**defaults)

    def _make_user(self) -> MagicMock:
        user = MagicMock()
        user.role = "ADMIN"
        return user

    def test_create_update_node_calls_upsert_with_correct_owner(self):
        """
        GIVEN a Node with owner='NetOps'
        WHEN create_update_node is called
        THEN topology_repo.upsert_node receives the node with owner='NetOps'
        """
        node = self._make_node(owner="NetOps")

        with (
            patch.object(topology_repo_mod, "upsert_node") as mock_upsert,
            patch.object(topology_repo_mod, "create_default_ping_metric"),
            patch.object(auth_service_mod, "check_permission", return_value=True),
            patch.dict(
                "sys.modules",
                {
                    "services.metric_service": MagicMock(
                        reconcile_node_metrics=MagicMock()
                    )
                },
            ),
        ):
            node_service_mod.create_update_node(node, self._make_user())

        mock_upsert.assert_called_once()
        upserted_node = mock_upsert.call_args[0][0]
        assert upserted_node.owner == "NetOps"

    def test_create_update_node_calls_upsert_with_correct_polling_interval(self):
        """
        GIVEN a Node with pollingInterval=120
        WHEN create_update_node is called
        THEN topology_repo.upsert_node receives the node with pollingInterval=120
        """
        node = self._make_node(pollingInterval=120)

        with (
            patch.object(topology_repo_mod, "upsert_node") as mock_upsert,
            patch.object(topology_repo_mod, "create_default_ping_metric"),
            patch.object(auth_service_mod, "check_permission", return_value=True),
            patch.dict(
                "sys.modules",
                {
                    "services.metric_service": MagicMock(
                        reconcile_node_metrics=MagicMock()
                    )
                },
            ),
        ):
            node_service_mod.create_update_node(node, self._make_user())

        mock_upsert.assert_called_once()
        upserted_node = mock_upsert.call_args[0][0]
        assert upserted_node.pollingInterval == 120

    def test_create_update_node_calls_upsert_with_serial_and_firmware(self):
        """
        GIVEN a Node with serialNumber and firmwareVersion set
        WHEN create_update_node is called
        THEN topology_repo.upsert_node receives the node with both fields intact
        """
        node = self._make_node(serialNumber="SN-ABCD1234", firmwareVersion="17.6.4")

        with (
            patch.object(topology_repo_mod, "upsert_node") as mock_upsert,
            patch.object(topology_repo_mod, "create_default_ping_metric"),
            patch.object(auth_service_mod, "check_permission", return_value=True),
            patch.dict(
                "sys.modules",
                {
                    "services.metric_service": MagicMock(
                        reconcile_node_metrics=MagicMock()
                    )
                },
            ),
        ):
            node_service_mod.create_update_node(node, self._make_user())

        mock_upsert.assert_called_once()
        upserted_node = mock_upsert.call_args[0][0]
        assert upserted_node.serialNumber == "SN-ABCD1234"
        assert upserted_node.firmwareVersion == "17.6.4"
