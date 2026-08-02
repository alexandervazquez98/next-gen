"""CMDB Orphan Topology Backfill — P3a of fix #416.

Read-only, offline CLI that surfaces Access Points with no upstream
DEPENDS_ON|HOSTED_ON edge so an operator can manually wire them in
internal CMDB tooling. No auto-write, no heuristics, no enrichment beyond
opaque CI IDs.
"""

from __future__ import annotations

# AD-01: scope is restricted to APs in this slice.
ALLOWED_SCOPES = frozenset({"ap"})

# AD-08: relationship-type allowlist. CONNECTS_TO is intentionally excluded
# per correlation-topology-guide.md (no parentage semantics).
ALLOWED_RELATIONSHIP_TYPES = frozenset(
    {"DEPENDS_ON", "HOSTED_ON", "MANAGES", "RUNS_ON"}
)

# REQ-002 default upstream edges.
DEFAULT_RELATIONSHIP_TYPES = ("DEPENDS_ON", "HOSTED_ON")


def validate_scope(scope: str) -> None:
    """Validate --scope.

    Returns None on success. Raises ``ValueError`` with the exact
    ``error: invalid --scope <value>; allowed: ap`` shape on any value
    not in ``ALLOWED_SCOPES``.
    """
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"error: invalid --scope {scope}; allowed: ap")
    return None


def validate_relationship_types(types) -> list:
    """Validate --relationship-types against the allowlist.

    ``None`` or an empty list returns the default upstream edges. Inputs
    are deduped while preserving first-seen order. Any value outside
    ``ALLOWED_RELATIONSHIP_TYPES`` (raw Cypher fragments included) raises
    ``ValueError`` before any Neo4j session is opened.
    """
    if not types:
        return list(DEFAULT_RELATIONSHIP_TYPES)
    seen: dict = {}
    for value in types:
        if value in ALLOWED_RELATIONSHIP_TYPES:
            seen[value] = True
            continue
        raise ValueError(
            f"error: invalid --relationship-types {value!r}; "
            f"allowed: {sorted(ALLOWED_RELATIONSHIP_TYPES)}"
        )
    return list(seen.keys())
