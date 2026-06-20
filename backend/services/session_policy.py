from __future__ import annotations

from dataclasses import dataclass
import os

@dataclass(frozen=True)
class SessionPolicy:
    """Normalized session policy resolved per user/account."""

    profile: str
    access_token_minutes: int
    refresh_token_days: int
    idle_timeout_minutes: int | None
    stale_rotation_grace_seconds: int
    stale_rotation_max_recoveries: int
    persistent: bool = False


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on", "enabled", "enable"}


def _parse_csv_tokens(value: str | None) -> set[str]:
    if not value:
        return set()

    tokens: set[str] = set()
    for item in value.split(","):
        token = item.strip()
        if token:
            tokens.add(token.lower())
    return tokens


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def get_stale_recovery_grace_seconds() -> int:
    return _parse_int(os.getenv("SESSION_STALE_ROTATION_GRACE_SECONDS"), default=30)


def get_stale_recovery_max_recoveries() -> int:
    return _parse_int(os.getenv("SESSION_STALE_ROTATION_MAX_RECOVERIES"), default=3)


def get_standard_session_policy() -> SessionPolicy:
    """Default non-operational policy."""
    return SessionPolicy(
        profile="standard",
        access_token_minutes=_parse_int(os.getenv("SESSION_STANDARD_ACCESS_MINUTES"), default=15),
        refresh_token_days=_parse_int(os.getenv("SESSION_STANDARD_REFRESH_DAYS"), default=7),
        idle_timeout_minutes=_parse_int(
            os.getenv("SESSION_STANDARD_IDLE_TIMEOUT_MINUTES"),
            default=15,
        ),
        stale_rotation_grace_seconds=get_stale_recovery_grace_seconds(),
        stale_rotation_max_recoveries=get_stale_recovery_max_recoveries(),
        persistent=False,
    )


def get_operational_session_policy() -> SessionPolicy:
    """Explicitly enabled operational policy."""
    return SessionPolicy(
        profile="operational",
        access_token_minutes=_parse_int(os.getenv("SESSION_OPERATIONAL_ACCESS_MINUTES"), default=15),
        # Keep long-lived (configurable) refresh for operational users.
        refresh_token_days=_parse_int(os.getenv("SESSION_OPERATIONAL_REFRESH_DAYS"), default=30),
        idle_timeout_minutes=None,
        stale_rotation_grace_seconds=get_stale_recovery_grace_seconds(),
        stale_rotation_max_recoveries=get_stale_recovery_max_recoveries(),
        persistent=True,
    )


def _normalize_user_role(user_role: str | None) -> str:
    if user_role is None:
        return ""

    # SQLAlchemy/enum values may arrive as Enum members, strings, or objects
    if hasattr(user_role, "value"):
        user_role = user_role.value

    text = str(user_role).strip()
    # Some enums stringify as "UserRole.ADMIN"; keep only logical token.
    if "." in text:
        text = text.split(".")[-1]
    return text.upper()


def _normalize_username(username: str | None) -> str:
    if username is None:
        return ""
    return str(username).strip().lower()


def get_session_policy_by_profile(profile: str) -> SessionPolicy:
    """Resolve policy from persisted profile string."""
    normalized = (profile or "").strip().lower()
    if normalized == "operational":
        return get_operational_session_policy()
    return get_standard_session_policy()


def get_session_activity_write_throttle_seconds() -> int:
    """Cross-worker throttle window for refresh-token activity writes.

    Default is 60s. The DB conditional UPDATE is the authoritative gate; this
    in-process cache is advisory only and safe to lose (per worker).
    """
    return _parse_int(
        os.getenv("SESSION_ACTIVITY_WRITE_THROTTLE_SECONDS"),
        default=60,
    )


def resolve_session_policy_for_user(user: object) -> SessionPolicy:
    """Resolve the session policy for a user row or Pydantic User payload."""
    operational_enabled = _parse_bool(os.getenv("SESSION_OPERATIONAL_ENABLED"), default=False)
    if not operational_enabled:
        return get_standard_session_policy()

    operational_roles = _parse_csv_tokens(os.getenv("SESSION_OPERATIONAL_ROLES"))
    operational_users = _parse_csv_tokens(os.getenv("SESSION_OPERATIONAL_USERS"))

    username = _normalize_username(getattr(user, "username", None) or "")
    role = _normalize_user_role(getattr(user, "role", None) or "")

    if username and username in operational_users:
        return get_operational_session_policy()

    if role and role.lower() in operational_roles:
        return get_operational_session_policy()

    return get_standard_session_policy()


def session_policy_cookie_max_age_seconds(policy: SessionPolicy) -> int:
    # Convert days to seconds for HttpOnly cookie expiry.
    return max(policy.refresh_token_days, 1) * 24 * 60 * 60


def access_token_max_age_seconds(policy: SessionPolicy) -> int:
    return max(policy.access_token_minutes, 1) * 60
