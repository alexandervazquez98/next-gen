from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from services.auth_service import get_current_active_user, check_permission
from models.user import Role, RoleCreate, RoleUpdate, User, UserPermission
from database import get_db
from postgres_db import get_pg_db
from services import audit_service

# Audit context constants
ALLOWED_PERMISSIONS = {perm.value for perm in UserPermission}

AUDIT_TARGET_TYPE_ROLE = "role"
AUDIT_SOURCE_ROLES = "roles"
AUDIT_OUTCOME_SUCCESS = "SUCCESS"
AUDIT_OUTCOME_VALIDATION_FAILURE = "VALIDATION_FAILURE"

AUDIT_EVENT_ROLE_CREATE = "ROLE_CREATE"
AUDIT_EVENT_ROLE_UPDATE = "ROLE_UPDATE"
AUDIT_EVENT_ROLE_DELETE = "ROLE_DELETE"

AUDIT_REASON_MISSING_PERMISSION = "missing_permission"
AUDIT_REASON_ROLE_EXISTS = "role_already_exists"
AUDIT_REASON_ROLE_NOT_FOUND = "role_not_found"
AUDIT_REASON_ROLE_SYSTEM = "cannot_modify_system_role"
AUDIT_REASON_ROLE_IN_USE = "role_in_use"
AUDIT_REASON_INVALID_PERMISSIONS = "invalid_role_permissions"


def _normalize_and_validate_permissions(
    permissions: list[Any] | None,
) -> list[str] | None:
    """Normalize role permissions to canonical string values and validate against UserPermission."""

    if permissions is None:
        return None

    normalized: list[str] = []
    invalid_permissions: list[Any] = []

    for permission in permissions:
        if not isinstance(permission, str):
            invalid_permissions.append(permission)
            continue

        clean = permission.strip()
        if not clean:
            invalid_permissions.append(permission)
            continue

        if clean not in ALLOWED_PERMISSIONS:
            invalid_permissions.append(clean)
            continue

        if clean not in normalized:
            normalized.append(clean)

    if invalid_permissions:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid permissions",
                "invalid_permissions": invalid_permissions,
                "allowed_permissions": sorted(ALLOWED_PERMISSIONS),
            },
        )

    return normalized


router = APIRouter(
    prefix="/roles",
    tags=["Roles"],
    responses={404: {"description": "Not found"}},
)


def get_db_driver():
    return get_db()


@router.get("/", response_model=List[Role])
async def list_roles(current_user: User = Depends(get_current_active_user)):
    # Any authenticated user can list roles to pick one (or restrict to USER_MANAGE?)
    # Usually, listing available roles is common, but viewing permissions might be restricted.
    # For now, let's allow listing for anyone, or at least USER_MANAGE

    # Actually, user creation requires listing roles. So USER_MANAGE is needed anyway.
    if not check_permission(UserPermission.USER_MANAGE, current_user) and not check_permission(UserPermission.ROLE_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view roles")

    driver = get_db_driver()
    query = "MATCH (r:Role) RETURN r ORDER BY r.name"
    results, _, _ = driver.execute_query(query)

    roles = []
    for record in results:
        node = record["r"]
        data = dict(node)
        # Convert neo4j list to python list if needed, though dict does it.
        if data.get("permissions") is None:
            data["permissions"] = []
        roles.append(Role(**data))

    return roles


@router.post("/", response_model=Role)
async def create_role(
    request: Request,
    role: RoleCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    if not check_permission(UserPermission.ROLE_MANAGE, current_user):
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserPermission.ROLE_MANAGE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=role.name,
            reason=AUDIT_REASON_MISSING_PERMISSION,
            source=AUDIT_SOURCE_ROLES,
        )
        raise HTTPException(status_code=403, detail="Not authorized to create roles")

    driver = get_db_driver()

    # Check if exists
    check_query = "MATCH (r:Role {name: $name}) RETURN r"
    results, _, _ = driver.execute_query(check_query, name=role.name)
    if results:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_ROLE_CREATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=role.name,
            target_label=role.name,
            reason=AUDIT_REASON_ROLE_EXISTS,
            source=AUDIT_SOURCE_ROLES,
            context={"changed_fields": ["name"], "required_permission": UserPermission.ROLE_MANAGE.value},
        )
        raise HTTPException(status_code=400, detail="Role already exists")

    params = role.dict()
    try:
        params["permissions"] = _normalize_and_validate_permissions(role.permissions)
    except HTTPException:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_ROLE_CREATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=role.name,
            target_label=role.name,
            reason=AUDIT_REASON_INVALID_PERMISSIONS,
            source=AUDIT_SOURCE_ROLES,
            context={
                "changed_fields": ["permissions"],
                "required_permission": UserPermission.ROLE_MANAGE.value,
            },
        )
        raise

    # Default is_system to False for new roles
    create_query = """
    CREATE (r:Role {
        name: $name,
        description: $description,
        permissions: $permissions,
        is_system: false
    }) RETURN r
    """

    results, _, _ = driver.execute_query(create_query, **params)
    node = results[0]["r"]
    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_ROLE_CREATE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_ROLE,
        target_id=role.name,
        target_label=role.name,
        reason="role_created",
        source=AUDIT_SOURCE_ROLES,
        context={
            "changed_fields": ["name", "description", "permissions"],
            "required_permission": UserPermission.ROLE_MANAGE.value,
        },
    )
    return Role(**dict(node))


@router.put("/{name}", response_model=Role)
async def update_role(
    request: Request,
    name: str,
    role_update: RoleUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    if not check_permission(UserPermission.ROLE_MANAGE, current_user):
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserPermission.ROLE_MANAGE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=name,
            reason=AUDIT_REASON_MISSING_PERMISSION,
            source=AUDIT_SOURCE_ROLES,
        )
        raise HTTPException(status_code=403, detail="Not authorized to update roles")

    driver = get_db_driver()

    # Check existence and system status
    check_query = "MATCH (r:Role {name: $name}) RETURN r"
    results, _, _ = driver.execute_query(check_query, name=name)
    if not results:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_ROLE_UPDATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=name,
            target_label=name,
            reason=AUDIT_REASON_ROLE_NOT_FOUND,
            source=AUDIT_SOURCE_ROLES,
            context={"changed_fields": ["name"], "required_permission": UserPermission.ROLE_MANAGE.value},
        )
        raise HTTPException(status_code=404, detail="Role not found")

    node = results[0]["r"]
    if node.get("is_system", False):
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_ROLE_UPDATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=name,
            target_label=name,
            reason=AUDIT_REASON_ROLE_SYSTEM,
            source=AUDIT_SOURCE_ROLES,
            context={"required_permission": UserPermission.ROLE_MANAGE.value},
        )
        raise HTTPException(status_code=400, detail="Cannot modify system roles")

    # Update
    update_query = """
    MATCH (r:Role {name: $name})
    SET r.description = COALESCE($description, r.description),
        r.permissions = COALESCE($permissions, r.permissions)
    RETURN r
    """

    params = {"name": name, "description": role_update.description}
    if role_update.permissions is not None:
        try:
            params["permissions"] = _normalize_and_validate_permissions(role_update.permissions)
        except HTTPException:
            audit_service.record_critical_change(
                db=db,
                request=request,
                actor=current_user,
                event_type=AUDIT_EVENT_ROLE_UPDATE,
                outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
                target_type=AUDIT_TARGET_TYPE_ROLE,
                target_id=name,
                target_label=name,
                reason=AUDIT_REASON_INVALID_PERMISSIONS,
                source=AUDIT_SOURCE_ROLES,
                context={
                    "changed_fields": ["permissions"],
                    "required_permission": UserPermission.ROLE_MANAGE.value,
                },
            )
            raise
    else:
        params["permissions"] = None

    results, _, _ = driver.execute_query(update_query, **params)
    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_ROLE_UPDATE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_ROLE,
        target_id=name,
        target_label=name,
        reason="role_updated",
        source=AUDIT_SOURCE_ROLES,
        context={
            "changed_fields": [field for field in ["description", "permissions"] if role_update.__dict__.get(field) is not None],
            "required_permission": UserPermission.ROLE_MANAGE.value,
        },
    )
    return Role(**dict(results[0]["r"]))


@router.delete("/{name}")
async def delete_role(
    request: Request,
    name: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    if not check_permission(UserPermission.ROLE_MANAGE, current_user):
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserPermission.ROLE_MANAGE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=name,
            reason=AUDIT_REASON_MISSING_PERMISSION,
            source=AUDIT_SOURCE_ROLES,
        )
        raise HTTPException(status_code=403, detail="Not authorized to delete roles")

    driver = get_db_driver()

    # Check existence
    check_query = "MATCH (r:Role {name: $name}) RETURN r"
    results, _, _ = driver.execute_query(check_query, name=name)
    if not results:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_ROLE_DELETE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=name,
            target_label=name,
            reason=AUDIT_REASON_ROLE_NOT_FOUND,
            source=AUDIT_SOURCE_ROLES,
            context={"required_permission": UserPermission.ROLE_MANAGE.value},
        )
        raise HTTPException(status_code=404, detail="Role not found")

    node = results[0]["r"]
    if node.get("is_system", False):
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_ROLE_DELETE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=name,
            target_label=name,
            reason=AUDIT_REASON_ROLE_SYSTEM,
            source=AUDIT_SOURCE_ROLES,
            context={"required_permission": UserPermission.ROLE_MANAGE.value},
        )
        raise HTTPException(status_code=400, detail="Cannot delete system roles")

    # Allow delete only if NO USERS are using it?
    # Recommended check.
    usage_query = "MATCH (u:User {role: $name}) RETURN count(u) as count"
    u_res, _, _ = driver.execute_query(usage_query, name=name)
    if u_res[0]["count"] > 0:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_ROLE_DELETE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_ROLE,
            target_id=name,
            target_label=name,
            reason=AUDIT_REASON_ROLE_IN_USE,
            source=AUDIT_SOURCE_ROLES,
            context={"required_permission": UserPermission.ROLE_MANAGE.value},
        )
        raise HTTPException(status_code=400, detail="Cannot delete role assigned to users")

    driver.execute_query("MATCH (r:Role {name: $name}) DELETE r", name=name)
    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_ROLE_DELETE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_ROLE,
        target_id=name,
        target_label=name,
        reason="role_deleted",
        source=AUDIT_SOURCE_ROLES,
        context={"required_permission": UserPermission.ROLE_MANAGE.value},
    )
    return {"status": "success", "message": f"Role {name} deleted"}
