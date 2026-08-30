"""Centralized MQTT authorization and mapping helpers."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, status
from models.mqtt import MqttMappingCreateRequest, MqttMappingThresholds, MqttMappingUpdateRequest
from models.user import User, UserPermission, UserRole
from repositories.mqtt_mapping_repo import (
    MappingConflictError,
    MappingNotFoundError,
    MqttMappingRepo,
    get_mqtt_mapping_repo,
)
from services import audit_service
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MQTT_READ_PERMISSION_KIND = "MQTT_READ"
MQTT_MAPPING_MANAGE_PERMISSION_KIND = "MQTT_MAPPING_MANAGE"

# ── Audit contract (issue #386) ─────────────────────────────────────────────
# Outcomes are uppercase to satisfy the `AuditOutcome` literal in routers/audit.py.
AUDIT_SOURCE_MQTT_MAPPING = "mqtt_mapping"
AUDIT_TARGET_TYPE_MQTT_MAPPING = "mqtt_mapping"

AUDIT_EVENT_MAPPING_CREATE = "MQTT_MAPPING_CREATE"
AUDIT_EVENT_MAPPING_UPDATE = "MQTT_MAPPING_UPDATE"
AUDIT_EVENT_MAPPING_APPROVE = "MQTT_MAPPING_APPROVE"
AUDIT_EVENT_MAPPING_REVOKE = "MQTT_MAPPING_REVOKE"
AUDIT_EVENT_MAPPING_THRESHOLD_UPDATE = "MQTT_MAPPING_THRESHOLD_UPDATE"

AUDIT_OUTCOME_SUCCESS = "SUCCESS"
AUDIT_OUTCOME_VALIDATION_FAILURE = "VALIDATION_FAILURE"
AUDIT_OUTCOME_DENIED = "DENIED"

AUDIT_REASON_DENIED = "mapping_permission_denied"
AUDIT_REASON_VALIDATION_FAILURE = "mapping_validation_failed"

MAPPING_STATE_DRAFT = "DRAFT"
MAPPING_STATE_APPROVED = "APPROVED"
MAPPING_STATE_REVOKED = "REVOKED"
MAPPING_INITIAL_VERSION = 1

_MAPPING_IDENTIFIER_KEYS = (
    "source_device_id",
    "source_metric_id",
    "target_ci_id",
    "target_metric_def_id",
)
_THRESHOLD_FIELDS = ("critical", "operator", "warning")

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


def _has_mqtt_permission(kind: str, current_user: User) -> bool:
    """Return True when ``current_user`` satisfies any permission required for ``kind``."""
    required_permissions = _required_permissions_for_kind(kind)

    return any(_user_has_permission(current_user, permission) for permission in required_permissions)


def require_mqtt_permission(kind: str, current_user: User) -> None:
    """Assert that ``current_user`` has the required MQTT permission for ``kind``."""
    if _has_mqtt_permission(kind, current_user):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Permission denied: {kind} required",
    )


def _mapping_audit_context(
    *,
    mapping_id: str | None,
    previous_state: str | None = None,
    next_state: str | None = None,
    identifiers: dict[str, Any] | None = None,
    version: int | None = None,
    changed_fields: list[str] | None = None,
    required_permission: str | None = None,
) -> dict[str, Any]:
    """Build allow-listed mapping audit context: identifiers and lifecycle state only.

    Never accepts topics, payload bodies or credentials; `sanitize_context` is the
    second line of defence in `audit_service`.
    """
    context: dict[str, Any] = {
        "mapping_id": mapping_id,
        "previous_state": previous_state,
        "next_state": next_state,
    }

    source = identifiers or {}
    for key in _MAPPING_IDENTIFIER_KEYS:
        value = source.get(key)
        if value is not None:
            context[key] = value

    if version is not None:
        context["version"] = version
    if changed_fields is not None:
        context["changed_fields"] = changed_fields
    if required_permission is not None:
        context["required_permission"] = required_permission

    return context


def _emit_mapping_audit(
    *,
    db: Session | None,
    request: Request | None,
    actor: User,
    event_type: str,
    outcome: str,
    mapping_id: str | None,
    reason: str,
    context: dict[str, Any],
) -> None:
    """Persist one mapping lifecycle audit row without ever breaking the mutation."""
    if db is None:
        return

    try:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=actor,
            event_type=event_type,
            outcome=outcome,
            target_type=AUDIT_TARGET_TYPE_MQTT_MAPPING,
            target_id=mapping_id,
            target_label=mapping_id,
            reason=reason,
            source=AUDIT_SOURCE_MQTT_MAPPING,
            context=context,
        )
    except Exception as exc:
        logger.warning("Failed to record MQTT mapping audit event %s: %s", event_type, exc)


def _enforce_manage_with_audit(
    *,
    current_user: User,
    db: Session | None,
    request: Request | None,
    mapping_id: str | None,
    event_type: str,
    identifiers: dict[str, Any] | None = None,
) -> None:
    """Audit a denied lifecycle attempt with its own event type, then raise 403.

    `audit_service.record_denied` is deliberately bypassed: it hardcodes
    `event_type="ACCESS_DENIED"`, which would break `target_id` filtering across
    the success/validation/denial rows of a single mapping.
    """
    if _has_mqtt_permission(MQTT_MAPPING_MANAGE_PERMISSION_KIND, current_user):
        return

    _emit_mapping_audit(
        db=db,
        request=request,
        actor=current_user,
        event_type=event_type,
        outcome=AUDIT_OUTCOME_DENIED,
        mapping_id=mapping_id,
        reason=AUDIT_REASON_DENIED,
        context=_mapping_audit_context(
            mapping_id=mapping_id,
            identifiers=identifiers,
            required_permission=MQTT_MAPPING_MANAGE_PERMISSION_KIND,
        ),
    )
    require_mqtt_permission(MQTT_MAPPING_MANAGE_PERMISSION_KIND, current_user)


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

    def create_mapping(
        self,
        payload: MqttMappingCreateRequest,
        current_user: User,
        *,
        db: Session | None = None,
        request: Request | None = None,
    ) -> dict:
        mapping_id = str(uuid4())
        identifiers = {
            "source_device_id": payload.source_device_id,
            "source_metric_id": payload.source_metric_id,
            "target_ci_id": payload.target_ci_id,
            "target_metric_def_id": payload.target_metric_def_id,
        }
        _enforce_manage_with_audit(
            current_user=current_user,
            db=db,
            request=request,
            mapping_id=mapping_id,
            event_type=AUDIT_EVENT_MAPPING_CREATE,
            identifiers=identifiers,
        )
        warning, critical, operator = self._threshold_values(payload.thresholds)
        try:
            return self._repo.create_draft(
                mapping_id=mapping_id,
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
        *,
        db: Session | None = None,
        request: Request | None = None,
    ) -> dict:
        _enforce_manage_with_audit(
            current_user=current_user,
            db=db,
            request=request,
            mapping_id=mapping_id,
            event_type=AUDIT_EVENT_MAPPING_UPDATE,
        )
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

    def approve_mapping(
        self,
        mapping_id: str,
        current_user: User,
        *,
        db: Session | None = None,
        request: Request | None = None,
    ) -> dict:
        _enforce_manage_with_audit(
            current_user=current_user,
            db=db,
            request=request,
            mapping_id=mapping_id,
            event_type=AUDIT_EVENT_MAPPING_APPROVE,
        )
        try:
            return self._repo.approve(mapping_id=mapping_id, approved_by=self._actor(current_user))
        except Exception as exc:
            self._raise_http_error(exc)
            raise

    def revoke_mapping(
        self,
        mapping_id: str,
        current_user: User,
        *,
        db: Session | None = None,
        request: Request | None = None,
    ) -> dict:
        _enforce_manage_with_audit(
            current_user=current_user,
            db=db,
            request=request,
            mapping_id=mapping_id,
            event_type=AUDIT_EVENT_MAPPING_REVOKE,
        )
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
        *,
        db: Session | None = None,
        request: Request | None = None,
    ) -> dict:
        _enforce_manage_with_audit(
            current_user=current_user,
            db=db,
            request=request,
            mapping_id=mapping_id,
            event_type=AUDIT_EVENT_MAPPING_THRESHOLD_UPDATE,
        )
        mapping = self._repo.get_mapping(mapping_id)
        if mapping is None:
            raise HTTPException(status_code=404, detail=f"Mapping not found: {mapping_id}")
        if mapping.get("status") != MAPPING_STATE_APPROVED:
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
