"""Centralized MQTT authorization and mapping helpers."""

from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status
from models.mqtt import MqttMappingCreateRequest, MqttMappingThresholds, MqttMappingUpdateRequest
from models.user import User, UserPermission, UserRole
from repositories.mqtt_mapping_repo import (
    MappingConflictError,
    MappingNotFoundError,
    MqttMappingRepo,
    get_mqtt_mapping_repo,
)

MQTT_READ_PERMISSION_KIND = "MQTT_READ"
MQTT_MAPPING_MANAGE_PERMISSION_KIND = "MQTT_MAPPING_MANAGE"

MQTT_PERMISSION_COMPATIBILITY_MAP: dict[str, list[str]] = {
    MQTT_READ_PERMISSION_KIND: [UserPermission.CI_VIEW.value],
    MQTT_MAPPING_MANAGE_PERMISSION_KIND: [UserPermission.CI_EDIT.value],
}

_SUPPORTED_MQTT_PERMISSION_KINDS = set(MQTT_PERMISSION_COMPATIBILITY_MAP)


def _supports_explicit_mqtt_permissions() -> bool:
    """Return True when the permission enum includes native MQTT permission values."""
    return isinstance(
        getattr(UserPermission, MQTT_READ_PERMISSION_KIND, None), UserPermission
    ) and isinstance(
        getattr(UserPermission, MQTT_MAPPING_MANAGE_PERMISSION_KIND, None),
        UserPermission,
    )


def _required_permissions_for_kind(kind: str) -> list[str]:
    """Return the required permission values for ``kind``."""
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
    """Assert that ``current_user`` has the required MQTT permission for ``kind``."""
    required_permissions = _required_permissions_for_kind(kind)

    if any(_user_has_permission(current_user, permission) for permission in required_permissions):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Permission denied: {kind} required",
    )


class MqttMappingService:
    """Application service for MQTT mapping lifecycle and thresholds."""

    def __init__(self, repo: MqttMappingRepo | None = None):
        self._repo = repo if repo is not None else get_mqtt_mapping_repo()

    @staticmethod
    def _actor(current_user: User) -> str:
        return current_user.username

    @staticmethod
    def _raise_http_error(exc: Exception) -> None:
        if isinstance(exc, MappingNotFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(exc, MappingConflictError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise exc

    @staticmethod
    def _threshold_values(
        thresholds: MqttMappingThresholds | None,
    ) -> tuple[float | None, float | None, str | None]:
        if thresholds is None:
            return None, None, None
        return thresholds.warning, thresholds.critical, thresholds.operator

    def list_mappings(self, current_user: User, status_filter: str | None = None) -> list[dict]:
        require_mqtt_permission(MQTT_READ_PERMISSION_KIND, current_user)
        return self._repo.list_mappings(status=status_filter)

    def create_mapping(self, payload: MqttMappingCreateRequest, current_user: User) -> dict:
        require_mqtt_permission(MQTT_MAPPING_MANAGE_PERMISSION_KIND, current_user)
        warning, critical, operator = self._threshold_values(payload.thresholds)
        try:
            return self._repo.create_draft(
                mapping_id=str(uuid4()),
                source_device_id=payload.source_device_id,
                source_metric_id=payload.source_metric_id,
                source_metric_name=payload.source_metric_name,
                target_ci_id=payload.target_ci_id,
                target_metric_def_id=payload.target_metric_def_id,
                created_by=self._actor(current_user),
                warning=warning,
                critical=critical,
                operator=operator,
            )
        except Exception as exc:
            self._raise_http_error(exc)
            raise

    def update_mapping(
        self,
        mapping_id: str,
        payload: MqttMappingUpdateRequest,
        current_user: User,
    ) -> dict:
        require_mqtt_permission(MQTT_MAPPING_MANAGE_PERMISSION_KIND, current_user)
        if payload.thresholds is None:
            current = self._repo.get_mapping(mapping_id)
            if current is None:
                raise HTTPException(status_code=404, detail=f"Mapping not found: {mapping_id}")
            warning = current.get("warning")
            critical = current.get("critical")
            operator = current.get("operator")
        else:
            warning, critical, operator = self._threshold_values(payload.thresholds)
        try:
            return self._repo.update_draft(
                mapping_id=mapping_id,
                source_metric_name=payload.source_metric_name,
                target_ci_id=payload.target_ci_id,
                target_metric_def_id=payload.target_metric_def_id,
                warning=warning,
                critical=critical,
                operator=operator,
            )
        except Exception as exc:
            self._raise_http_error(exc)
            raise

    def approve_mapping(self, mapping_id: str, current_user: User) -> dict:
        require_mqtt_permission(MQTT_MAPPING_MANAGE_PERMISSION_KIND, current_user)
        try:
            return self._repo.approve(mapping_id=mapping_id, approved_by=self._actor(current_user))
        except Exception as exc:
            self._raise_http_error(exc)
            raise

    def revoke_mapping(self, mapping_id: str, current_user: User) -> dict:
        require_mqtt_permission(MQTT_MAPPING_MANAGE_PERMISSION_KIND, current_user)
        try:
            return self._repo.revoke(mapping_id=mapping_id, revoked_by=self._actor(current_user))
        except Exception as exc:
            self._raise_http_error(exc)
            raise

    def get_thresholds(self, mapping_id: str, current_user: User) -> dict:
        require_mqtt_permission(MQTT_READ_PERMISSION_KIND, current_user)
        mappings = [
            mapping for mapping in self._repo.list_mappings() if mapping.get("id") == mapping_id
        ]
        if not mappings:
            raise HTTPException(status_code=404, detail=f"Mapping not found: {mapping_id}")
        mapping = mappings[0]
        return {
            "operator": mapping.get("operator"),
            "warning": mapping.get("warning"),
            "critical": mapping.get("critical"),
        }

    def update_thresholds(
        self,
        mapping_id: str,
        thresholds: MqttMappingThresholds,
        current_user: User,
    ) -> dict:
        require_mqtt_permission(MQTT_MAPPING_MANAGE_PERMISSION_KIND, current_user)
        mapping = self._repo.get_mapping(mapping_id)
        if mapping is None:
            raise HTTPException(status_code=404, detail=f"Mapping not found: {mapping_id}")
        if mapping.get("status") != "APPROVED":
            raise HTTPException(
                status_code=409,
                detail="Thresholds can only be updated for APPROVED mappings",
            )
        try:
            return self._repo.update_thresholds(
                mapping_id=mapping_id,
                warning=thresholds.warning,
                critical=thresholds.critical,
                operator=thresholds.operator,
            )
        except Exception as exc:
            self._raise_http_error(exc)
            raise


_mapping_service: MqttMappingService | None = None


def get_mqtt_mapping_service() -> MqttMappingService:
    global _mapping_service
    if _mapping_service is None:
        _mapping_service = MqttMappingService()
    return _mapping_service
