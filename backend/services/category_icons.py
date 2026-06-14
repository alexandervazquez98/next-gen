import re


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
}


def normalize_icon_key(icon_key: str | None) -> str | None:
    if icon_key is None:
        return None

    normalized = re.sub(r"[^a-z0-9_]+", "", str(icon_key).strip().lower())
    if not normalized:
        return None

    alias_map = {
        "genericicon": "generic",
        "default": "generic",
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

    normalized = re.sub(r"[^a-z0-9]+", "", category_name.lower())
    default_icon = _CATEGORY_DEFAULT_ICON_BY_NAME.get(normalized)
    return default_icon
