"""Tests for validate_scope and validate_relationship_types (WU-2)."""

from __future__ import annotations

import pytest


class TestValidateScope:
    def test_ap_is_accepted(self):
        from openspec.scripts.cmdb_backfill_orphans import validate_scope

        assert validate_scope("ap") is None

    def test_switch_rejected_with_exact_message(self):
        from openspec.scripts.cmdb_backfill_orphans import validate_scope

        with pytest.raises(ValueError) as exc_info:
            validate_scope("switch")
        assert str(exc_info.value) == "error: invalid --scope switch; allowed: ap"

    def test_router_rejected(self):
        from openspec.scripts.cmdb_backfill_orphans import validate_scope

        with pytest.raises(ValueError) as exc_info:
            validate_scope("router")
        assert "error: invalid --scope router" in str(exc_info.value)
        assert "allowed: ap" in str(exc_info.value)

    def test_empty_scope_rejected(self):
        from openspec.scripts.cmdb_backfill_orphans import validate_scope

        with pytest.raises(ValueError):
            validate_scope("")


class TestValidateRelationshipTypes:
    def test_none_defaults_to_default_rels(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        assert validate_relationship_types(None) == ["DEPENDS_ON", "HOSTED_ON"]

    def test_explicit_default_rels_accepted(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        assert validate_relationship_types(["DEPENDS_ON", "HOSTED_ON"]) == [
            "DEPENDS_ON",
            "HOSTED_ON",
        ]

    def test_connects_to_explicitly_rejected(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        with pytest.raises(ValueError) as exc_info:
            validate_relationship_types(["CONNECTS_TO"])
        assert "CONNECTS_TO" in str(exc_info.value)

    def test_cypher_injection_rejected(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        with pytest.raises(ValueError):
            validate_relationship_types(["MATCH (n) DELETE n"])

    def test_known_manages_and_runs_on_accepted(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        result = validate_relationship_types(["MANAGES", "RUNS_ON"])
        assert result == ["MANAGES", "RUNS_ON"]
        assert set(result) == {"MANAGES", "RUNS_ON"}

    def test_duplicates_are_deduped(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        result = validate_relationship_types(
            ["DEPENDS_ON", "DEPENDS_ON", "HOSTED_ON"]
        )
        assert result == ["DEPENDS_ON", "HOSTED_ON"]

    def test_order_preserved(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        result = validate_relationship_types(["RUNS_ON", "DEPENDS_ON", "MANAGES"])
        assert result == ["RUNS_ON", "DEPENDS_ON", "MANAGES"]

    def test_one_bad_apple_rejects_whole_list(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        with pytest.raises(ValueError):
            validate_relationship_types(["DEPENDS_ON", "BOGUS_EDGE"])

    def test_empty_list_falls_back_to_default(self):
        from openspec.scripts.cmdb_backfill_orphans import (
            validate_relationship_types,
        )

        result = validate_relationship_types([])
        assert result == ["DEPENDS_ON", "HOSTED_ON"]
