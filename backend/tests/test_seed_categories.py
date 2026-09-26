"""Unit tests for ``seed_categories`` idempotent boot-time seeding — feat-489 pre-flight.

Mirrors ``test_seed_roles_cmdb.py`` style: stub the Neo4j driver and assert the
right Cypher is issued across fresh/upgrade/skip paths. No live Neo4j required.

Coverage:
- Fresh graph: every DEFAULT_CATEGORIES entry is MERGE'd with the resolved icon_key.
- Existing category: skip branch taken (no SET issued).
- Existing category with NULL icon_key: backfilled via the update branch.
- Re-running on a fully-seeded graph is idempotent (no MERGE issued twice).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_driver():
    """Patch ``database.driver`` so seed_categories can run without a live Neo4j.

    Same trick as ``test_seed_roles_cmdb.py``: patch at the module global because
    ``database.py`` captures the driver at import time.
    """
    import database as _db_module

    driver = MagicMock()
    original = _db_module.driver
    _db_module.driver = driver
    try:
        yield driver
    finally:
        _db_module.driver = original


def _existing_mock(icon_key):
    m = MagicMock()
    m.get.side_effect = lambda k: icon_key if k == "icon_key" else None
    return m


def _empty_single(*args, **kwargs):
    """Default single() returning None — simulates fresh graph (no Category nodes)."""
    return None


def test_fresh_graph_creates_all_default_categories(stub_driver):
    """On a fresh stack every DEFAULT_CATEGORIES entry MUST be MERGE'd."""
    import asyncio

    import seed_categories

    session = stub_driver.session.return_value.__enter__.return_value
    session.run.return_value.single.side_effect = _empty_single

    asyncio.run(seed_categories.seed_categories())

    # Collect every MERGE call on :Category — there should be one per default.
    merge_calls = [c for c in session.run.call_args_list if "MERGE (c:Category" in str(c.args[0])]
    seeded_names = {c.kwargs.get("name") for c in merge_calls}
    assert seeded_names == set(
        seed_categories.DEFAULT_CATEGORIES
    ), f"Expected all DEFAULT_CATEGORIES to be MERGE'd; got {seeded_names}"

    # Router must resolve to icon_key='router' (canonical mapping in category_icons).
    router_call = next(c for c in merge_calls if c.kwargs.get("name") == "Router")
    assert (
        router_call.kwargs.get("icon_key") == "router"
    ), f"Router should resolve to icon_key='router'; got {router_call.kwargs.get('icon_key')}"


def test_existing_category_with_icon_is_skipped(stub_driver):
    """If the Category already has an icon_key, seed MUST NOT overwrite it."""
    import asyncio

    import seed_categories

    session = stub_driver.session.return_value.__enter__.return_value

    def _single_with_icon(*args, **kwargs):
        return _existing_mock("custom_icon_xyz")

    session.run.return_value.single.side_effect = _single_with_icon

    asyncio.run(seed_categories.seed_categories())

    # No MERGE should fire — every category already exists with an icon.
    merge_calls = [c for c in session.run.call_args_list if "MERGE (c:Category" in str(c.args[0])]
    assert (
        merge_calls == []
    ), f"Existing categories must not be re-MERGE'd; got {len(merge_calls)} calls"


def test_existing_category_with_null_icon_is_backfilled(stub_driver):
    """A Category with icon_key=NULL MUST be backfilled with the resolved default."""
    import asyncio

    import seed_categories

    session = stub_driver.session.return_value.__enter__.return_value
    session.run.return_value.single.side_effect = lambda *a, **kw: _existing_mock(None)

    asyncio.run(seed_categories.seed_categories())

    # Find the backfill SET — must use the resolved icon_key.
    backfill_calls = [
        c
        for c in session.run.call_args_list
        if "SET c.icon_key" in str(c.args[0]) and "IS NULL" in str(c.args[0])
    ]
    assert backfill_calls, "Backfill path did not issue SET c.icon_key ... IS NULL"
    # All defaults except 'Other' have a canonical icon mapping; 'Other' falls
    # back to 'generic'. Either is acceptable as long as backfill fired.
    icon_keys = {c.kwargs.get("icon_key") for c in backfill_calls}
    assert icon_keys <= {
        None,
        "router",
        "server",
        "generic",
    }, f"Unexpected icon_keys in backfill: {icon_keys}"


def test_seed_is_idempotent_across_two_runs(stub_driver):
    """Running seed_categories twice on a fully-populated graph MUST be a no-op.

    Both runs must issue exactly one MATCH per category and zero MERGEs / SETs.
    We swap a fresh session mock between runs to avoid call-list accumulation
    across the two ``asyncio.run`` invocations.
    """
    import asyncio

    import seed_categories

    def fresh_session():
        s = MagicMock()
        s.run.return_value.single.side_effect = lambda *a, **kw: _existing_mock("router")
        return s

    # Run 1
    stub_driver.session.return_value.__enter__.return_value = fresh_session()
    asyncio.run(seed_categories.seed_categories())
    first_calls = [
        str(c.args[0])
        for c in stub_driver.session.return_value.__enter__.return_value.run.call_args_list
    ]

    # Run 2 on the same (populated) graph state
    stub_driver.session.return_value.__enter__.return_value = fresh_session()
    asyncio.run(seed_categories.seed_categories())
    second_calls = [
        str(c.args[0])
        for c in stub_driver.session.return_value.__enter__.return_value.run.call_args_list
    ]

    for label, calls in (("first", first_calls), ("second", second_calls)):
        assert all(
            "MERGE (c:Category" not in q for q in calls
        ), f"{label} run issued MERGEs on a populated graph: {calls}"
        assert all(
            "SET c.icon_key" not in q for q in calls
        ), f"{label} run issued icon_key SETs on a populated graph: {calls}"
        match_calls = [q for q in calls if "MATCH (c:Category" in q]
        assert len(match_calls) == len(seed_categories.DEFAULT_CATEGORIES), (
            f"{label} run: expected {len(seed_categories.DEFAULT_CATEGORIES)} MATCH calls; "
            f"got {len(match_calls)}"
        )
