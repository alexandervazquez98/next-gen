"""Tests for category icon catalog normalization and defaults."""


from services import category_icons


def test_resolve_category_icon_prefers_stored_key():
    assert (
        category_icons.resolve_category_icon("Layer 2 switch", "router")
        == "router"
    )


def test_resolve_category_icon_accepts_slice_1_icon_keys():
    for icon_key in (
        "vpn_tunnel",
        "sd_wan_tunnel",
        "satellite_link",
        "vpn_hub",
    ):
        assert category_icons.resolve_category_icon("Custom", icon_key) == icon_key


def test_resolve_category_icon_applies_default_for_known_category():
    assert (
        category_icons.resolve_category_icon("Layer 2 switch", None)
        == "switch_l2"
    )


def test_resolve_category_icon_defaults_vpn_hub_names():
    for category_name in (
        "vpn hub",
        "vpn_hub",
        "hub vpn",
        "concentrador vpn",
        "vpn concentrator",
    ):
        assert (
            category_icons.resolve_category_icon(category_name, None)
            == "vpn_hub"
        )


def test_resolve_category_icon_defaults_to_generic_when_unknown():
    assert category_icons.resolve_category_icon("Legacy Blade", None) == "generic"


def test_invalid_icon_key_normalization_returns_none():
    assert category_icons.normalize_icon_key("  bad:key! ") is None


def test_is_valid_icon_key_accepts_generic_aliases():
    assert category_icons.is_valid_icon_key("Generic")
    assert category_icons.is_valid_icon_key("default")
