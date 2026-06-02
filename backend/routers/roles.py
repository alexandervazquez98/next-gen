
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from services.auth_service import get_current_active_user, check_permission
from models.user import Role, RoleCreate, RoleUpdate, User, UserPermission
from database import get_db


ALLOWED_PERMISSIONS = {perm.value for perm in UserPermission}


def _normalize_and_validate_permissions(permissions: list[Any] | None) -> list[str] | None:
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
async def create_role(role: RoleCreate, current_user: User = Depends(get_current_active_user)):
    if not check_permission(UserPermission.ROLE_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to create roles")
    
    driver = get_db_driver()
    
    # Check if exists
    check_query = "MATCH (r:Role {name: $name}) RETURN r"
    results, _, _ = driver.execute_query(check_query, name=role.name)
    if results:
        raise HTTPException(status_code=400, detail="Role already exists")
    
    # Default is_system to False for new roles
    create_query = """
    CREATE (r:Role {
        name: $name, 
        description: $description, 
        permissions: $permissions,
        is_system: false 
    }) RETURN r
    """

    params = role.dict()
    params["permissions"] = _normalize_and_validate_permissions(role.permissions)

    results, _, _ = driver.execute_query(create_query, **params)
    node = results[0]["r"]
    return Role(**dict(node))

@router.put("/{name}", response_model=Role)
async def update_role(name: str, role_update: RoleUpdate, current_user: User = Depends(get_current_active_user)):
    if not check_permission(UserPermission.ROLE_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update roles")
        
    driver = get_db_driver()
    
    # Check existence and system status
    check_query = "MATCH (r:Role {name: $name}) RETURN r"
    results, _, _ = driver.execute_query(check_query, name=name)
    if not results:
        raise HTTPException(status_code=404, detail="Role not found")
        
    node = results[0]["r"]
    if node.get("is_system", False):
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
        params["permissions"] = _normalize_and_validate_permissions(role_update.permissions)
    else:
        params["permissions"] = None

    results, _, _ = driver.execute_query(update_query, **params)
    return Role(**dict(results[0]["r"]))

@router.delete("/{name}")
async def delete_role(name: str, current_user: User = Depends(get_current_active_user)):
    if not check_permission(UserPermission.ROLE_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete roles")
        
    driver = get_db_driver()
    
    # Check existence
    check_query = "MATCH (r:Role {name: $name}) RETURN r"
    results, _, _ = driver.execute_query(check_query, name=name)
    if not results:
         raise HTTPException(status_code=404, detail="Role not found")

    node = results[0]["r"]
    if node.get("is_system", False):
         raise HTTPException(status_code=400, detail="Cannot delete system roles")
         
    # Allow delete only if NO USERS are using it?
    # Recommended check.
    usage_query = "MATCH (u:User {role: $name}) RETURN count(u) as count"
    u_res, _, _ = driver.execute_query(usage_query, name=name)
    if u_res[0]["count"] > 0:
        raise HTTPException(status_code=400, detail="Cannot delete role assigned to users")
        
    driver.execute_query("MATCH (r:Role {name: $name}) DELETE r", name=name)
    return {"status": "success", "message": f"Role {name} deleted"}
