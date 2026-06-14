"""Tests for category icon catalog normalization and defaults."""


from services import category_icons


def test_resolve_category_icon_prefers_stored_key():
    assert (
        category_icons.resolve_category_icon("Layer 2 switch", "router")
        == "router"
    )


def test_resolve_category_icon_applies_default_for_known_category():
    assert (
        category_icons.resolve_category_icon("Layer 2 switch", None)
        == "switch_l2"
    )


def test_resolve_category_icon_defaults_to_generic_when_unknown():
    assert category_icons.resolve_category_icon("Legacy Blade", None) == "generic"


def test_invalid_icon_key_normalization_returns_none():
    assert category_icons.normalize_icon_key("  bad:key! ") is None


def test_is_valid_icon_key_accepts_generic_aliases():
    assert category_icons.is_valid_icon_key("Generic")
    assert category_icons.is_valid_icon_key("default")
