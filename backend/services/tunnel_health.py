from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from services.relationship_types import validate_ci_relationship_type

TunnelStatus = Literal["UP", "DOWN", "UNKNOWN"]
TunnelMedium = Literal["vpn", "sd_wan", "satellite"]
AuthorityState = Literal["UP", "DOWN"]
AuthorityReason = Literal["sample", "no_sample"]
IcmpReason = Literal["sample", "missing_public_ip", "no_sample", "failed"]

TUNNEL_MEDIA = frozenset({"vpn", "sd_wan", "satellite"})
LINK_ID_FIELDS = ("source", "relationship", "target", "medium")
MAX_LINK_ID_DECODED_BYTES = 512


@dataclass(frozen=True)
class LinkIdentity:
    source: str
    relationship: str
    target: str
    medium: TunnelMedium


class TunnelAuthoritySample(BaseModel):
    state: AuthorityState
    source: str | None = None
    observed_at: str | None = None


class TunnelIcmpSample(BaseModel):
    available: bool
    latency_ms: float | None = None
    error: str | None = None
    reason: IcmpReason | None = None


class AuthorityContext(BaseModel):
    state: AuthorityState | None
    source: str | None
    observed_at: str | None
    reason: AuthorityReason


class IcmpContext(BaseModel):
    available: bool
    latency_ms: float | None
    error: str | None
    reason: IcmpReason


class TunnelHealthResponse(BaseModel):
    link_id: str
    source: str
    target: str
    relationship: str
    medium: TunnelMedium
    status: TunnelStatus
    authority: AuthorityContext
    icmp: IcmpContext
    observed_at: str | None


def _canonical_payload(identity: LinkIdentity) -> dict[str, str]:
    relationship = validate_ci_relationship_type(identity.relationship)
    medium = identity.medium
    if medium not in TUNNEL_MEDIA:
        raise ValueError(f"Invalid tunnel medium: {medium}")
    return {
        "source": identity.source,
        "relationship": relationship,
        "target": identity.target,
        "medium": medium,
    }


def encode_link_id(identity: LinkIdentity) -> str:
    payload = _canonical_payload(identity)
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_LINK_ID_DECODED_BYTES:
        raise ValueError("Decoded link_id payload is too large")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_link_id(link_id: str) -> LinkIdentity:
    if not link_id or "=" in link_id:
        raise ValueError("Invalid unpadded base64url link_id")

    padded = link_id + ("=" * (-len(link_id) % 4))
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError("Invalid base64url link_id") from exc

    if len(raw) > MAX_LINK_ID_DECODED_BYTES:
        raise ValueError("Decoded link_id payload is too large")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON link_id payload") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid link_id payload")
    if tuple(payload.keys()) != LINK_ID_FIELDS:
        raise ValueError("link_id payload must use canonical fields")

    values = {field: payload[field] for field in LINK_ID_FIELDS}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ValueError("link_id payload fields must be non-empty strings")

    relationship = validate_ci_relationship_type(values["relationship"])
    medium = values["medium"]
    if medium not in TUNNEL_MEDIA:
        raise ValueError(f"Invalid tunnel medium: {medium}")

    identity = LinkIdentity(
        source=values["source"],
        relationship=relationship,
        target=values["target"],
        medium=medium,  # type: ignore[arg-type]
    )
    if encode_link_id(identity) != link_id:
        raise ValueError("link_id payload is not canonical")
    return identity


def normalize_tunnel_health(
    *,
    link_id: str,
    source: str,
    target: str,
    relationship: str,
    medium: TunnelMedium,
    authority: TunnelAuthoritySample | None,
    icmp: TunnelIcmpSample | None,
    missing_public_ip: bool = False,
    observed_at: str | None = None,
) -> TunnelHealthResponse:
    relationship = validate_ci_relationship_type(relationship)
    if medium not in TUNNEL_MEDIA:
        raise ValueError(f"Invalid tunnel medium: {medium}")

    if authority is None:
        status: TunnelStatus = "UNKNOWN"
        authority_context = AuthorityContext(
            state=None,
            source=None,
            observed_at=None,
            reason="no_sample",
        )
    else:
        status = authority.state
        authority_context = AuthorityContext(
            state=authority.state,
            source=authority.source,
            observed_at=authority.observed_at,
            reason="sample",
        )

    if missing_public_ip:
        icmp_context = IcmpContext(
            available=False,
            latency_ms=None,
            error=None,
            reason="missing_public_ip",
        )
    elif icmp is None or icmp.reason == "no_sample":
        icmp_context = IcmpContext(
            available=False,
            latency_ms=None,
            error=None,
            reason="no_sample",
        )
    elif icmp.reason == "missing_public_ip":
        icmp_context = IcmpContext(
            available=False,
            latency_ms=None,
            error=None,
            reason="missing_public_ip",
        )
    elif icmp.reason == "failed":
        icmp_context = IcmpContext(
            available=False,
            latency_ms=icmp.latency_ms,
            error=icmp.error,
            reason="failed",
        )
    elif icmp.available:
        icmp_context = IcmpContext(
            available=True,
            latency_ms=icmp.latency_ms,
            error=icmp.error,
            reason="sample",
        )
    else:
        icmp_context = IcmpContext(
            available=False,
            latency_ms=icmp.latency_ms,
            error=icmp.error,
            reason="failed",
        )

    return TunnelHealthResponse(
        link_id=link_id,
        source=source,
        target=target,
        relationship=relationship,
        medium=medium,
        status=status,
        authority=authority_context,
        icmp=icmp_context,
        observed_at=observed_at,
    )
