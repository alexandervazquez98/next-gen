"""Shared relationship type definitions for CI correlation APIs."""
from __future__ import annotations

from collections.abc import Iterable
import re

SUPPORTED_CI_RELATIONSHIP_TYPES = frozenset({
    "CONNECTS_TO",
    "DEPENDS_ON",
    "HOSTED_ON",
    "MANAGES",
    "USES",
    "PROVIDES",
})

SYSTEM_RELATIONSHIP_TYPES = frozenset({"HAS_METRIC"})
READ_ONLY_GRAPH_RELATIONSHIP_TYPES = frozenset({"RUNS_ON"})
LISTABLE_RELATIONSHIP_TYPES = (
    SUPPORTED_CI_RELATIONSHIP_TYPES | SYSTEM_RELATIONSHIP_TYPES | READ_ONLY_GRAPH_RELATIONSHIP_TYPES
)

LEGACY_RELATIONSHIP_TYPE_MAP = {"CONNECTED_TO": "CONNECTS_TO"}
_SAFE_RELATIONSHIP_TYPE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def normalize_relationship_type(relationship: str) -> str:
    return relationship.upper().replace(" ", "_")


def validate_legacy_relationship_type(relationship: str) -> str:
    clean = normalize_relationship_type(relationship)
    if clean in SUPPORTED_CI_RELATIONSHIP_TYPES or not _SAFE_RELATIONSHIP_TYPE.fullmatch(clean):
        raise ValueError(f"Invalid legacy relationship type: {relationship}")
    return clean


def validate_ci_relationship_type(relationship: str) -> str:
    clean = normalize_relationship_type(relationship)
    if clean not in SUPPORTED_CI_RELATIONSHIP_TYPES:
        raise ValueError(f"Invalid relationship type: {relationship}")
    return clean


def cypher_relationship_union(relationship_types: Iterable[str]) -> str:
    """Build a Cypher relationship union after validating known safe type names."""
    allowed = LISTABLE_RELATIONSHIP_TYPES | SUPPORTED_CI_RELATIONSHIP_TYPES
    clean_types = []
    for rel_type in relationship_types:
        clean = normalize_relationship_type(rel_type)
        if clean not in allowed:
            raise ValueError(f"Invalid relationship type for Cypher union: {rel_type}")
        clean_types.append(clean)
    return "|".join(sorted(set(clean_types)))
