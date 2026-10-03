"""Service layer for :PhysicalLink CRUD — feat-444-physical-link-styling (slice 2).

Slice 2/4 of the fiber-optic / physical-link visualization chain (#444). The
metadata model + migration shipped in slice 1 (#323); this module layers
validation + permission gates + delegation on top of the repo so the router
stays a thin HTTP wrapper.

Layered guards (mirroring ``services.cmdb_proposal_service``):
1. Permission (HTTP 403): CI_EDIT for write paths; CI_VIEW for read paths
   only when the caller is authenticated. Admin bypasses both.
2. Validation (HTTP 400): unknown PhysicalLinkType, unknown PhysicalLinkStatus,
   endpoints that don't reference existing :CI nodes.

Read paths accept ``current_user: User | None = None`` so unauthenticated
graph consumers (Geo View, anonymous preview) can poll the endpoint without
401-ing. The tunnel-link router (``backend/routers/links.py``) follows the
same precedent.

The Pydantic schemas in ``backend/schemas/physical_link.py`` already reject
unknown Literal values at the wire boundary; the explicit frozenset checks
here are defence in depth — if the schema is ever relaxed, the service still
rejects bad input before hitting Neo4j.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from models.user import User, UserPermission, UserRole

# ── canonical allow-lists (defence in depth) ───────────────────────────────────

ALLOWED_TYPES: frozenset[str] = frozenset({"fiber", "copper", "microwave", "wireless_ptp"})
ALLOWED_STATUSES: frozenset[str] = frozenset({"UP", "DOWN", "UNKNOWN", "PLANNED"})


# ── helpers ──────────────────────────────────────────────────────────────────


def _get_repo():
    """Lazy repo accessor — kept module-level so tests can monkeypatch it."""
    from repositories.physical_link_repo import get_physical_link_repo

    return get_physical_link_repo()


def _has_user_permission(permission: UserPermission, user: User) -> bool:
    """Check UserPermission membership; Admin bypasses."""
    if user.role == UserRole.ADMIN.value or user.role == "ADMIN":
        return True
    return permission.value in (user.permissions or [])


def _ci_id_exists(ci_id: str | None) -> bool:
    """Return True if a :CI node with this id exists.

    Reused from cmdb_proposal_service: avoids dragging the full node-service
    surface area into a slice that only needs a yes/no check.
    """
    if not ci_id:
        return False
    try:
        from database import get_db

        driver = get_db()
        with driver.session() as session:
            result = session.run(
                "MATCH (n:CI {id: $id}) RETURN n.id AS id LIMIT 1",
                id=ci_id,
            )
            return result.single() is not None
    except Exception:
        # Conservative: treat inability to confirm presence as absent.
        return False


# ── public API ───────────────────────────────────────────────────────────────


def create_physical_link(
    *,
    payload: dict[str, Any],
    current_user: User,
) -> dict[str, Any]:
    """Create a new :PhysicalLink.

    Permission gate -> Literal validation -> endpoint existence check ->
    repo.create().

    Raises:
        HTTPException(403): missing CI_EDIT and not Admin.
        HTTPException(400): unknown type / status, unknown endpoint.
    """
    if not _has_user_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: CI_EDIT required to create a PhysicalLink",
        )

    link_type = payload.get("type")
    if link_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "unknown_type",
                "type": link_type,
                "allowed": sorted(ALLOWED_TYPES),
            },
        )

    status = payload.get("status", "UNKNOWN")
    if status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "unknown_status",
                "status": status,
                "allowed": sorted(ALLOWED_STATUSES),
            },
        )

    raw_endpoints = payload.get("endpoints")
    if not isinstance(raw_endpoints, (list, tuple)) or len(raw_endpoints) != 2:
        raise HTTPException(
            status_code=400,
            detail={"reason": "endpoints_must_be_a_2_tuple", "value": raw_endpoints},
        )
    endpoint_a, endpoint_b = raw_endpoints
    if endpoint_a == endpoint_b:
        raise HTTPException(
            status_code=400,
            detail={"reason": "endpoints_must_differ", "endpoint": endpoint_a},
        )
    for endpoint in (endpoint_a, endpoint_b):
        if not _ci_id_exists(endpoint):
            raise HTTPException(
                status_code=400,
                detail={"reason": "unknown_endpoint", "endpoint": endpoint},
            )

    repo = _get_repo()
    return repo.create(
        link_id=payload["id"],
        link_type=link_type,
        endpoints=(endpoint_a, endpoint_b),
        status=status,
        capacity_gbps=payload.get("capacity_gbps"),
        install_date=payload.get("install_date"),
    )


def get_physical_link(link_id: str) -> dict[str, Any] | None:
    """Fetch one PhysicalLink by id; returns None when missing."""
    return _get_repo().get_by_id(link_id)


def list_physical_links(
    *,
    ci_id: str | None = None,
    link_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User | None = None,
) -> list[dict[str, Any]]:
    """List PhysicalLink rows with optional filters.

    When ``current_user`` is provided, enforces ``CI_VIEW`` for non-admins.
    When omitted (anonymous poll), reads are public — mirrors tunnel links.
    """
    if current_user is not None and not _has_user_permission(UserPermission.CI_VIEW, current_user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: CI_VIEW required to list PhysicalLinks",
        )
    return _get_repo().list(
        ci_id=ci_id,
        link_type=link_type,
        status=status,
        limit=limit,
        offset=offset,
    )


def update_physical_link_status(
    *,
    link_id: str,
    status: str,
    current_user: User,
) -> dict[str, Any]:
    """Update the status of an existing PhysicalLink.

    Raises:
        HTTPException(403): missing CI_EDIT and not Admin.
        HTTPException(400): unknown status literal.
        HTTPException(404): id not found.
    """
    if not _has_user_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403,
            detail="missing_permission: CI_EDIT required to update a PhysicalLink",
        )

    if status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "unknown_status",
                "status": status,
                "allowed": sorted(ALLOWED_STATUSES),
            },
        )

    row = _get_repo().update_status(link_id, status)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "physical_link_not_found", "id": link_id},
        )
    return row
