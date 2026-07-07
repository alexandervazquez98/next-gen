"""Centralized MQTT authorization helpers for mapping and read operations.

This module owns all permission checks introduced by the MQTT authorization slice
(PR2). Route-level code should call :func:`require_mqtt_permission` instead of
repeating permission logic.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from models.user import User, UserPermission, UserRole

# Public permission kind strings. Kept as plain strings to keep dependency
# surfaces explicit for route code and future migration of source-of-truth.
MQTT_READ_PERMISSION_KIND = "MQTT_READ"
MQTT_MAPPING_MANAGE_PERMISSION_KIND = "MQTT_MAPPING_MANAGE"

# Backward-compatibility fallback when enum extension cannot be used in the
# deployment/runtime environment. Must remain centralized in a single constant.
MQTT_PERMISSION_COMPATIBILITY_MAP: dict[str, list[str]] = {
    MQTT_READ_PERMISSION_KIND: [UserPermission.CI_VIEW.value],
    MQTT_MAPPING_MANAGE_PERMISSION_KIND: [UserPermission.CI_EDIT.value],
}

# Explicitly supported permission kinds for this helper.
_SUPPORTED_MQTT_PERMISSION_KINDS = set(MQTT_PERMISSION_COMPATIBILITY_MAP)


def _supports_explicit_mqtt_permissions() -> bool:
    """Return True when the permission enum includes native MQTT permission values."""
    return (
        isinstance(getattr(UserPermission, MQTT_READ_PERMISSION_KIND, None), UserPermission)
        and isinstance(
            getattr(UserPermission, MQTT_MAPPING_MANAGE_PERMISSION_KIND, None),
            UserPermission,
        )
    )


def _required_permissions_for_kind(kind: str) -> list[str]:
    """Return the required permission values for ``kind``.

    If native enum values are unavailable, resolves a single centralized
    compatibility fallback mapping.
    """
    if kind not in _SUPPORTED_MQTT_PERMISSION_KINDS:
        raise ValueError(f"Unknown MQTT permission kind: {kind}")

    if _supports_explicit_mqtt_permissions():
        if kind == MQTT_READ_PERMISSION_KIND:
            return [getattr(UserPermission, MQTT_READ_PERMISSION_KIND).value]
        if kind == MQTT_MAPPING_MANAGE_PERMISSION_KIND:
            return [getattr(UserPermission, MQTT_MAPPING_MANAGE_PERMISSION_KIND).value]

    return MQTT_PERMISSION_COMPATIBILITY_MAP[kind]


def _is_admin(role: str | UserRole) -> bool:
    return (
        role == UserRole.ADMIN.value
        or role == UserRole.ADMIN
        or str(role).upper() == UserRole.ADMIN.value
    )


def _user_has_permission(current_user: User, permission: str) -> bool:
    """Match permissions stored in role/user records against required values."""
    if _is_admin(current_user.role):
        return True

    user_permissions = current_user.permissions or []
    return permission in user_permissions


def require_mqtt_permission(kind: str, current_user: User) -> None:
    """Assert that ``current_user`` has the required MQTT permission for ``kind``.

    Raises:
        HTTPException: with 403 when permission is missing.
    """
    required_permissions = _required_permissions_for_kind(kind)

    if any(_user_has_permission(current_user, permission) for permission in required_permissions):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Permission denied: {kind} required",
    )
