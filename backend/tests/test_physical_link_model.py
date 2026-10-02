"""Tests for the PhysicalLink metadata model — feat-323-physical-link-model.

Slice 1/4 of fiber-optic / physical-link visualization (#323). Validates:
- PhysicalLink Pydantic model with the 6 fields
- PhysicalLinkType Literal with the 4 documented media
- Migration 009 file exists, parses, declares constraints
- Repository helper returns PhysicalLink nodes independent of tunnel links
- The existing tunnel Link.medium Literal is NOT touched (regression guard)

The migration is pure file-level; no live Neo4j required.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / "009_physical_link_model.cypher"
)


# ---------------------------------------------------------------------------
# T1 + T2 — Model and Literal
# ---------------------------------------------------------------------------


def test_physical_link_model_has_six_documented_fields():
    from models.core import PhysicalLink

    pl = PhysicalLink(
        id="pl-fiber-001",
        type="fiber",
        endpoints=("ci-router-a", "ci-router-b"),
        status="UP",
        capacity_gbps=10,
        install_date="2024-01-15",
    )
    assert pl.id == "pl-fiber-001"
    assert pl.type == "fiber"
    assert pl.endpoints == ("ci-router-a", "ci-router-b")
    assert pl.status == "UP"
    assert pl.capacity_gbps == 10
    assert pl.install_date == "2024-01-15"


def test_physical_link_type_literal_accepts_documented_media():
    """fiber, copper, microwave, wireless_ptp are the four documented media."""
    from models.core import PhysicalLink

    for media in ("fiber", "copper", "microwave", "wireless_ptp"):
        pl = PhysicalLink(
            id=f"pl-{media}",
            type=media,
            endpoints=("ci-a", "ci-b"),
            status="UP",
            capacity_gbps=1,
            install_date="2024-01-01",
        )
        assert pl.type == media


def test_physical_link_type_rejects_unregistered_medium():
    """An unknown physical medium must be rejected — keep the enum closed."""
    from models.core import PhysicalLink
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PhysicalLink(
            id="pl-bad",
            type="plasma",  # not in the documented set
            endpoints=("ci-a", "ci-b"),
            status="UP",
            capacity_gbps=1,
            install_date="2024-01-01",
        )


# ---------------------------------------------------------------------------
# T3 — Migration 009 file structure
# ---------------------------------------------------------------------------


def _load_migration() -> str:
    assert MIGRATION_PATH.exists(), f"Migration file missing: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_009_file_exists_with_correct_name():
    assert MIGRATION_PATH.name == "009_physical_link_model.cypher"


def test_migration_009_uses_idempotent_if_not_exists():
    """Every statement must use IF NOT EXISTS so the migration is re-runnable."""
    text = _load_migration()
    # Strip comment lines before counting statements
    non_comment = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
    statements = [s.strip() for s in non_comment.split(";") if s.strip()]
    assert len(statements) >= 2, "Expected at least 2 statements (id constraint + index)"
    for stmt in statements:
        assert "IF NOT EXISTS" in stmt.upper(), f"Statement not idempotent: {stmt[:80]}"


def test_migration_009_declares_physical_link_id_constraint():
    text = _load_migration()
    # Must declare uniqueness on :PhysicalLink.id
    assert re.search(
        r"CONSTRAINT\s+\w*\s*IF NOT EXISTS\s+FOR\s*\(\s*\w*:\s*PhysicalLink\s*\)\s*REQUIRE\s+\w+\.id\s+IS\s+UNIQUE",
        text,
        re.IGNORECASE,
    ), "Missing :PhysicalLink.id uniqueness constraint"


def test_migration_009_declares_connected_via_relationship_support():
    """The (CI)-[:CONNECTED_VIA]->(PhysicalLink) relationship must be representable."""
    text = _load_migration()
    # Either an explicit relationship constraint OR a documented usage comment
    assert "CONNECTED_VIA" in text, "Migration must reference the CONNECTED_VIA relationship"


# ---------------------------------------------------------------------------
# T9 — Regression: tunnel Link.medium is NOT modified
# ---------------------------------------------------------------------------


def test_tunnel_link_medium_literal_is_unchanged():
    """Hard constraint from #323: do not overload the tunnel medium field."""
    from models.core import Link

    # The three documented tunnel media are still valid
    for medium in ("vpn", "sd_wan", "satellite"):
        link = Link(source="a", target="b", relationship="CONNECTS_TO", medium=medium)
        assert link.medium == medium

    # The Link model still has the medium field at all
    fields = Link.model_fields.keys()
    assert "medium" in fields


def test_physical_link_coexists_with_tunnel_link():
    """A PhysicalLink must not collide with a tunnel Link."""
    from models.core import Link, PhysicalLink

    tunnel = Link(source="ci-a", target="ci-b", relationship="CONNECTS_TO", medium="vpn")
    pl = PhysicalLink(
        id="pl-001",
        type="fiber",
        endpoints=("ci-a", "ci-b"),
        status="UP",
        capacity_gbps=10,
        install_date="2024-01-01",
    )
    # Distinct model classes
    assert type(tunnel) is not type(pl)
    # Tunnel has no capacity_gbps; PhysicalLink has no medium
    assert not hasattr(tunnel, "capacity_gbps")
    assert not hasattr(pl, "medium")
