"""Unit tests for seed_roles idempotent permission upgrades — feat-cmdb-ai-handoff.

Tests validate that the additive upgrade mechanism yields both:
- AI_* roles carrying AI_PROPOSE_CI on existing deployments
- OPERATOR carrying CI_APPROVE_PROPOSAL
- ADMIN carrying CI_APPROVE_PROPOSAL (already covered by spread)

The upgrade path is exercised by stubbing the driver so no live Neo4j is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_driver():
    """Patch ``database.driver`` so seed_roles can run without a live Neo4j.

    Patches at the ``database.driver`` module global (not ``neo4j.GraphDatabase.driver``)
    because ``database.py`` captures the driver at module-import time.
    """
    import database as _db_module

    driver = MagicMock()
    original = _db_module.driver
    _db_module.driver = driver
    try:
        yield driver
    finally:
        _db_module.driver = original


def test_operator_seed_includes_ci_approve_proposal(stub_driver):
    """Fresh OPERATOR seed MUST include CI_APPROVE_PROPOSAL (REQ-CMAP-005)."""
    import asyncio

    import seed_roles

    driver = stub_driver
    session = driver.session.return_value.__enter__.return_value

    # Empty graph — no role exists yet, so the create branch is taken.
    session.run.return_value.single.return_value = None

    asyncio.run(seed_roles.seed_roles())

    # Find the CREATE call for OPERATOR and assert CI_APPROVE_PROPOSAL is in perms.
    create_calls = [c for c in session.run.call_args_list if "CREATE (r:Role" in str(c.args[0])]
    operator_create = [c for c in create_calls if c.kwargs.get("name") == "OPERATOR"]
    assert operator_create, "OPERATOR role was not created"
    perms = operator_create[0].kwargs["perms"]
    assert "CI_APPROVE_PROPOSAL" in perms, f"OPERATOR must seed CI_APPROVE_PROPOSAL; got {perms}"


@pytest.mark.parametrize("role_name", ["AI_DIAGNOSTIC", "AI_OPERATOR"])
def test_ai_roles_seed_ai_propose_ci(stub_driver, role_name):
    """Fresh AI_* seed MUST include AI_PROPOSE_CI (REQ-CMAP-004)."""
    import asyncio

    import seed_roles

    session = stub_driver.session.return_value.__enter__.return_value
    session.run.return_value.single.return_value = None

    asyncio.run(seed_roles.seed_roles())

    create_calls = [c for c in session.run.call_args_list if "CREATE (r:Role" in str(c.args[0])]
    role_create = [c for c in create_calls if c.kwargs.get("name") == role_name]
    assert role_create, f"{role_name} role was not created"
    perms = role_create[0].kwargs["perms"]
    assert "AI_PROPOSE_CI" in perms, f"{role_name} must seed AI_PROPOSE_CI; got {perms}"


def test_ai_roles_never_get_ci_approve_proposal(stub_driver):
    """CI_APPROVE_PROPOSAL MUST NOT be granted to any AI_* role (REQ-CMAP-005 scenario 2)."""
    import asyncio

    import seed_roles

    session = stub_driver.session.return_value.__enter__.return_value
    session.run.return_value.single.return_value = None

    asyncio.run(seed_roles.seed_roles())

    create_calls = [c for c in session.run.call_args_list if "CREATE (r:Role" in str(c.args[0])]
    for ai_role in ("AI_DIAGNOSTIC", "AI_OPERATOR"):
        ai_create = [c for c in create_calls if c.kwargs.get("name") == ai_role]
        assert ai_create, f"{ai_role} role was not created"
        perms = ai_create[0].kwargs["perms"]
        assert (
            "CI_APPROVE_PROPOSAL" not in perms
        ), f"{ai_role} must NEVER grant CI_APPROVE_PROPOSAL; got {perms}"


def test_upgrade_adds_missing_permissions_to_existing_system_role(stub_driver):
    """Idempotent upgrade MUST add CI_APPROVE_PROPOSAL to existing OPERATOR."""
    import asyncio

    import seed_roles

    session = stub_driver.session.return_value.__enter__.return_value

    existing_role = {
        "name": "OPERATOR",
        "description": "Operational Staff",
        "permissions": ["EVENT_VIEW", "CI_VIEW"],  # missing CI_APPROVE_PROPOSAL
        "is_system": True,
    }

    def _make_existing_mock(role_data):
        m = MagicMock()
        m.get.return_value = role_data
        m.__getitem__.side_effect = lambda k: role_data if k == "r" else None
        return m

    # Configure `single()` to return the OPERATOR existing mock ONLY when the
    # MATCH query is for OPERATOR; return None for everything else (so other
    # roles are created fresh, isolating the upgrade path).
    def _single_for(*args, **kwargs):
        query = args[0] if args else kwargs.get("query", "")
        if "MATCH (r:Role" not in query:
            return MagicMock()
        name = kwargs.get("name")
        if name == "OPERATOR":
            return _make_existing_mock(existing_role)
        return MagicMock()  # no existing role -> CREATE branch

    session.run.return_value.single.side_effect = _single_for

    asyncio.run(seed_roles.seed_roles())

    # Find the upgrade call specifically for OPERATOR (its SET r.permissions call).
    upgrade_calls = [
        c
        for c in session.run.call_args_list
        if "SET r.permissions" in str(c.args[0]) and c.kwargs.get("name") == "OPERATOR"
    ]
    assert upgrade_calls, "Idempotent upgrade path did not issue SET r.permissions for OPERATOR"

    last_perms = upgrade_calls[-1].kwargs.get("perms") or []
    assert (
        "CI_APPROVE_PROPOSAL" in last_perms
    ), f"Upgrade path must add CI_APPROVE_PROPOSAL; got {last_perms}"
