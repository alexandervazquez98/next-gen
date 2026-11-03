"""feat-539 — the PhysicalLink correlation rollout flag.

The reconciled contract, ``docs/correlation-topology-guide.md`` and the
OpenSpec proposal all promise the same thing: "The PhysicalLink chain ships
behind ``FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED``, default
off; it is flipped on only after the whole reconciled chain (PR2a1 -> PR2c2)
lands and CI is green."

This file pins that promise:

* the flag defaults to OFF;
* while it is OFF the correlation traversal renders ONLY the pre-#539 pure-CI
  walk, so the modern SNMP engine AND the legacy engine behave exactly as
  they did before #539 — no PhysicalLink crossing, no status gate, no
  degraded child;
* while it is ON the crossing, the status gate and the link metadata are
  rendered;
* the ROOT-only correlation-parent rule is NOT gated: it is a bug fix, not
  part of the new feature.
"""

from __future__ import annotations

import pytest
from repositories.topology_repo import (
    _correlation_edge_branches,
    _correlation_parent_branches,
)
from services.correlation_propagation_contract import (
    FEATURE_FLAG_PHYSICAL_LINK_CORRELATION,
)


@pytest.fixture(autouse=True)
def _physical_link_correlation_enabled(monkeypatch):
    """Keep the #939 rollout flag OFF in this module.

    Same name as the suite-wide ``conftest`` fixture, so it overrides it:
    this module pins the SHIPPED default-off behaviour, while the rest of the
    suite exercises the flag-ON behaviour.
    """
    import config

    monkeypatch.delenv(FEATURE_FLAG_PHYSICAL_LINK_CORRELATION, raising=False)
    monkeypatch.setattr(config, "_polling_pipeline_settings", None, raising=False)
    yield


@pytest.fixture
def reset_polling_settings():
    """Drop the cached polling settings so the flag is re-read from the env."""
    import config

    previous = config._polling_pipeline_settings  # noqa: SLF001
    config._polling_pipeline_settings = None  # noqa: SLF001
    yield
    config._polling_pipeline_settings = previous  # noqa: SLF001


@pytest.fixture
def flag_off(monkeypatch, reset_polling_settings):
    """The flag is absent from the environment — the shipped default."""
    monkeypatch.delenv(FEATURE_FLAG_PHYSICAL_LINK_CORRELATION, raising=False)


@pytest.fixture
def flag_on(monkeypatch, reset_polling_settings):
    """The operator flipped the flag on."""
    monkeypatch.setenv(FEATURE_FLAG_PHYSICAL_LINK_CORRELATION, "true")


class TestFlagDefault:
    """The shipped default is OFF, as three documents promise."""

    def test_the_flag_defaults_to_off(self, flag_off):
        from config import get_polling_pipeline_settings

        assert get_polling_pipeline_settings().enable_physical_link_correlation is False

    def test_the_flag_reads_the_name_owned_by_the_contract(self):
        """The env var name has ONE owner: the correlation contract module."""
        assert FEATURE_FLAG_PHYSICAL_LINK_CORRELATION == (
            "FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED"
        )

    def test_the_flag_can_be_flipped_on(self, flag_on):
        from config import get_polling_pipeline_settings

        assert get_polling_pipeline_settings().enable_physical_link_correlation is True


class TestFlagOffRendersThePre539Walk:
    """With the flag OFF the traversal is the pre-#539 pure-CI walk."""

    def test_no_physical_link_crossing_is_rendered(self, flag_off):
        branches = _correlation_parent_branches(3)

        assert ":PhysicalLink" not in branches
        assert "CONNECTED_VIA" not in branches
        assert "propagating_link_statuses" not in branches

    def test_the_pure_ci_walk_is_still_rendered(self, flag_off):
        branches = _correlation_parent_branches(3)

        assert "DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3" in branches
        assert "RETURN parent, null AS link_id, null AS link_status" in branches

    def test_the_adjacency_branches_render_no_crossing_either(self, flag_off):
        branches = _correlation_edge_branches(3)

        assert ":PhysicalLink" not in branches
        assert "CONNECTED_VIA" not in branches
        assert "relationships(path)" in branches


class TestFlagOnRendersTheCrossing:
    """With the flag ON the crossing, the status gate and the metadata return."""

    def test_the_crossing_is_rendered(self, flag_on):
        branches = _correlation_parent_branches(3)

        assert ":PhysicalLink" in branches
        assert "CONNECTED_VIA" in branches
        assert "WHERE pl.status IN $propagating_link_statuses" in branches
        assert "pl.id AS link_id" in branches
        assert "pl.status AS link_status" in branches

    def test_every_logical_position_is_rendered(self, flag_on):
        branches = _correlation_parent_branches(3)

        # One pure-CI branch plus one branch per (link position, total hops).
        assert branches.count("RETURN parent") == 7

    def test_the_adjacency_branches_render_the_crossing(self, flag_on):
        branches = _correlation_edge_branches(3)

        assert ":PhysicalLink" in branches
        assert "CONNECTED_VIA" in branches


class TestRootParentRuleIsNotGated:
    """The ROOT-only correlation-parent rule is a bug fix, not part of the feature.

    Before #539 a degraded child could become the correlation parent and the CI
    behind it produced NO event at all. That rule must hold in BOTH flag
    states: it removes an ambiguity, it does not add a behaviour.
    """

    def test_the_root_parent_filter_is_present_with_the_flag_off(self, flag_off):
        branches = _correlation_parent_branches(3)

        assert "ROOT" not in branches  # the filter lives outside the branches

        # The rendered query of the batched lookup is the public surface.
        query = _rendered_batch_query()
        assert "coalesce(pe.correlation_type, 'ROOT') = 'ROOT'" in query

    def test_the_root_parent_filter_is_present_with_the_flag_on(self, flag_on):
        query = _rendered_batch_query()

        assert "coalesce(pe.correlation_type, 'ROOT') = 'ROOT'" in query


def _rendered_batch_query() -> str:
    """Render the batched lookup query without running it."""
    from repositories import topology_repo

    captured: dict[str, str] = {}

    class _Session:
        def run(self, query, **params):
            captured["query"] = query
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Driver:
        def session(self, *args, **kwargs):
            return _Session()

    original = topology_repo.get_db
    topology_repo.get_db = lambda: _Driver()  # type: ignore[assignment]
    try:
        topology_repo.build_open_parent_index(_Session(), {("ci-child", "cpu-load")})
    finally:
        topology_repo.get_db = original  # type: ignore[assignment]
    return captured["query"]
