import pytest

from services.relationship_types import (
    LISTABLE_RELATIONSHIP_TYPES,
    SUPPORTED_CI_RELATIONSHIP_TYPES,
    cypher_relationship_union,
    validate_ci_relationship_type,
)


def test_supported_ci_relationship_types_include_homologated_types():
    assert {"CONNECTS_TO", "DEPENDS_ON", "HOSTED_ON"}.issubset(SUPPORTED_CI_RELATIONSHIP_TYPES)
    assert "CONNECTED_TO" not in SUPPORTED_CI_RELATIONSHIP_TYPES


def test_validate_ci_relationship_type_rejects_legacy_connected_to():
    with pytest.raises(ValueError):
        validate_ci_relationship_type("CONNECTED_TO")


def test_validate_ci_relationship_type_accepts_normalized_supported_type():
    assert validate_ci_relationship_type("connects to") == "CONNECTS_TO"


def test_listable_relationship_union_includes_created_supported_types():
    rel_union = cypher_relationship_union(LISTABLE_RELATIONSHIP_TYPES)

    assert "CONNECTS_TO" in rel_union
    assert "DEPENDS_ON" in rel_union
    assert "HOSTED_ON" in rel_union
    assert "CONNECTED_TO" not in rel_union
