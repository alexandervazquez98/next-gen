import logging
import re
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from models.user import User
from pydantic import BaseModel, ConfigDict, Field, field_validator
from repositories import topology_repo
from services.auth_service import get_current_active_user
from services.tunnel_health import TunnelHealthResponse, decode_link_id

router = APIRouter(
    prefix="/tunnels",
    tags=["Tunnels"],
    responses={404: {"description": "Not found"}},
)

logger = logging.getLogger(__name__)

TelemetryErrorKind = Literal["bad_request", "not_found", "server", "timeout", "auth", "network"]
LatencyBucket = Literal["lt_250", "lt_1000", "lt_5000", "gte_5000"]

_FORBIDDEN_TELEMETRY_KEYS = {
    "link_id",
    "link_ids",
    "source",
    "target",
    "endpoint",
    "endpoints",
    "url",
    "urls",
    "path",
    "public_ip",
    "public_ips",
    "links",
    "per_link",
    "per_link_details",
}
_IP_LIKE_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TELEMETRY_RATE_LIMIT = 5
_TELEMETRY_RATE_WINDOW_SECONDS = 60
_TELEMETRY_MAX_SCHEDULED_PER_WINDOW = 120
_TELEMETRY_MAX_SKIPPED_OR_SUPPRESSED_PER_WINDOW = 10_000
_TELEMETRY_MAX_PER_WINDOW_COUNT = 120
_telemetry_rate_windows: dict[str, list[float]] = {}
_telemetry_aggregate_stats = {
    "accepted": 0,
    "scheduled": 0,
    "skipped_over_cap": 0,
    "suppressed_cooldown": 0,
    "success": 0,
    "failure_by_kind": {kind: 0 for kind in TelemetryErrorKind.__args__},
    "latency_bucket": {bucket: 0 for bucket in LatencyBucket.__args__},
    "kill_switch_enabled": False,
}


class TunnelHealthTelemetryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_seconds: Literal[60]
    scheduled: int = Field(ge=0, le=_TELEMETRY_MAX_SCHEDULED_PER_WINDOW)
    skipped_over_cap: int = Field(ge=0, le=_TELEMETRY_MAX_SKIPPED_OR_SUPPRESSED_PER_WINDOW)
    suppressed_cooldown: int = Field(ge=0, le=_TELEMETRY_MAX_SKIPPED_OR_SUPPRESSED_PER_WINDOW)
    success: int = Field(ge=0, le=_TELEMETRY_MAX_SCHEDULED_PER_WINDOW)
    failure_by_kind: dict[TelemetryErrorKind, int] = Field(default_factory=dict)
    latency_bucket: dict[LatencyBucket, int] = Field(default_factory=dict)
    kill_switch_enabled: bool

    @field_validator("failure_by_kind", "latency_bucket")
    @classmethod
    def validate_nested_counts(cls, value: dict[str, int]) -> dict[str, int]:
        for count in value.values():
            if count < 0 or count > _TELEMETRY_MAX_PER_WINDOW_COUNT:
                raise ValueError("Telemetry nested counts must be within the per-window bounds")
        return value


def get_tunnel_health_telemetry_stats() -> dict[str, Any]:
    return {
        "accepted": _telemetry_aggregate_stats["accepted"],
        "scheduled": _telemetry_aggregate_stats["scheduled"],
        "skipped_over_cap": _telemetry_aggregate_stats["skipped_over_cap"],
        "suppressed_cooldown": _telemetry_aggregate_stats["suppressed_cooldown"],
        "success": _telemetry_aggregate_stats["success"],
        "failure_by_kind": dict(_telemetry_aggregate_stats["failure_by_kind"]),
        "latency_bucket": dict(_telemetry_aggregate_stats["latency_bucket"]),
        "kill_switch_enabled": _telemetry_aggregate_stats["kill_switch_enabled"],
    }


def _record_tunnel_health_telemetry(payload: TunnelHealthTelemetryPayload) -> None:
    _telemetry_aggregate_stats["accepted"] += 1
    _telemetry_aggregate_stats["scheduled"] += payload.scheduled
    _telemetry_aggregate_stats["skipped_over_cap"] += payload.skipped_over_cap
    _telemetry_aggregate_stats["suppressed_cooldown"] += payload.suppressed_cooldown
    _telemetry_aggregate_stats["success"] += payload.success
    _telemetry_aggregate_stats["kill_switch_enabled"] = payload.kill_switch_enabled
    for kind, count in payload.failure_by_kind.items():
        _telemetry_aggregate_stats["failure_by_kind"][kind] += count
    for bucket, count in payload.latency_bucket.items():
        _telemetry_aggregate_stats["latency_bucket"][bucket] += count
    logger.info(
        "Accepted tunnel health telemetry aggregate",
        extra={
            "tunnel_health_telemetry": {
                "scheduled": payload.scheduled,
                "skipped_over_cap": payload.skipped_over_cap,
                "suppressed_cooldown": payload.suppressed_cooldown,
                "success": payload.success,
                "failure_by_kind": dict(payload.failure_by_kind),
                "latency_bucket": dict(payload.latency_bucket),
                "kill_switch_enabled": payload.kill_switch_enabled,
            }
        },
    )


def _contains_sensitive_telemetry(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            if key_text in _FORBIDDEN_TELEMETRY_KEYS or _IP_LIKE_RE.search(key_text):
                return True
            if _contains_sensitive_telemetry(nested):
                return True
        return False
    if isinstance(value, list):
        return True
    if isinstance(value, str):
        lowered = value.lower()
        return "/tunnels/" in lowered or _IP_LIKE_RE.search(value) is not None
    return False


def _enforce_telemetry_rate_limit(username: str) -> None:
    now = time.monotonic()
    window = [
        timestamp
        for timestamp in _telemetry_rate_windows.get(username, [])
        if now - timestamp < _TELEMETRY_RATE_WINDOW_SECONDS
    ]
    if len(window) >= _TELEMETRY_RATE_LIMIT:
        _telemetry_rate_windows[username] = window
        raise HTTPException(status_code=429, detail="Tunnel health telemetry rate limit exceeded")
    window.append(now)
    _telemetry_rate_windows[username] = window


@router.get("/{link_id}/health", response_model=TunnelHealthResponse)
async def get_tunnel_health(
    link_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    try:
        identity = decode_link_id(link_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tunnel link id") from exc

    is_admin = current_user.role == "ADMIN"
    allowed_locations = current_user.allowed_locations
    health = topology_repo.get_tunnel_health_link(
        identity,
        allowed_locations=allowed_locations,
        is_admin=is_admin,
    )
    if health is None:
        raise HTTPException(status_code=404, detail="Tunnel link not found")
    return health


@router.post("/health/telemetry", status_code=202)
async def post_tunnel_health_telemetry(
    request: Request,
    payload: TunnelHealthTelemetryPayload,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    raw_body = await request.json()
    if _contains_sensitive_telemetry(raw_body):
        raise HTTPException(status_code=422, detail="Telemetry payload must be aggregate-only and redacted")

    _enforce_telemetry_rate_limit(current_user.username)
    _record_tunnel_health_telemetry(payload)
    return {"accepted": True}
