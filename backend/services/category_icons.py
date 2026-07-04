import re
import unicodedata

ALLOWED_CATEGORY_ICON_KEYS = {
    "generic",
    "switch_l2",
    "switch_l3",
    "router",
    "server",
    "saas",
    "storage",
    "camera",
    "video_analytics",
    "radio_telecom",
    "trunk_link",
    "access_ci",
    "distribution_ci",
    "vpn_tunnel",
    "sd_wan_tunnel",
    "satellite_link",
    "vpn_hub",
}


_CATEGORY_DEFAULT_ICON_BY_NAME = {
    "layer2switch": "switch_l2",
    "l2switch": "switch_l2",
    "switchlayer2": "switch_l2",
    "layerswitch2": "switch_l2",
    "switch2": "switch_l2",
    "layer3switch": "switch_l3",
    "l3switch": "switch_l3",
    "switchlayer3": "switch_l3",
    "layerswitch3": "switch_l3",
    "switch3": "switch_l3",
    "router": "router",
    "server": "server",
    "saas": "saas",
    "softwareasaservice": "saas",
    "storage": "storage",
    "camera": "camera",
    "cameras": "camera",
    "videoanalytics": "video_analytics",
    "video_analytics": "video_analytics",
    "radio": "radio_telecom",
    "radiotelecom": "radio_telecom",
    "radioenlace": "radio_telecom",
    "trunk": "trunk_link",
    "trunklink": "trunk_link",
    "troncal": "trunk_link",
    "troncaldered": "trunk_link",
    "access": "access_ci",
    "accessci": "access_ci",
    "acceso": "access_ci",
    "nododeacceso": "access_ci",
    "distribution": "distribution_ci",
    "distributionci": "distribution_ci",
    "distribucion": "distribution_ci",
    "capadistribucion": "distribution_ci",
    "vpn_hub": "vpn_hub",
    "vpnhub": "vpn_hub",
    "hubvpn": "vpn_hub",
    "concentradorvpn": "vpn_hub",
    "vpnconcentrator": "vpn_hub",
}


def _normalize_lookup_token(value: str) -> str:
    return re.sub(
        r"[^a-z0-9_]+",
        "",
        unicodedata.normalize("NFD", value.lower()).encode("ascii", "ignore").decode("ascii"),
    )


def normalize_icon_key(icon_key: str | None) -> str | None:
    if icon_key is None:
        return None

    normalized = _normalize_lookup_token(str(icon_key).strip())
    if not normalized:
        return None

    alias_map = {
        "genericicon": "generic",
        "default": "generic",
        "radiotelecom": "radio_telecom",
        "trunklink": "trunk_link",
        "accessci": "access_ci",
        "distributionci": "distribution_ci",
    }
    normalized = alias_map.get(normalized, normalized)
    if normalized not in ALLOWED_CATEGORY_ICON_KEYS:
        return None

    return normalized


def is_valid_icon_key(icon_key: str | None) -> bool:
    return normalize_icon_key(icon_key) is not None


def resolve_category_icon(category_name: str | None, icon_key: str | None) -> str:
    icon = normalize_icon_key(icon_key)
    if icon:
        return icon

    default_icon = get_default_category_icon(category_name)
    if default_icon:
        return default_icon

    return "generic"


def get_default_category_icon(category_name: str | None) -> str | None:
    if not category_name:
        return None

    normalized = _normalize_lookup_token(category_name)
    default_icon = _CATEGORY_DEFAULT_ICON_BY_NAME.get(normalized)
    return default_icon
