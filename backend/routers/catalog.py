from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any, Optional
from models.core import Category, HardwareModel, OwnerGroup
from models.user import User, UserPermission
from pydantic import BaseModel
import services.catalog_service as catalog_service
from services.auth_service import get_current_active_user, check_permission

router = APIRouter(
    tags=["Catalog"],
    responses={404: {"description": "Not found"}},
)

# --- Categories ---


class CategoryUpdate(BaseModel):
    name: str


@router.get("/categories", response_model=List[Dict[str, str]])
async def get_categories(current_user: User = Depends(get_current_active_user)):
    """Fetch all available CI Categories."""
    return catalog_service.get_categories()


@router.post("/categories")
async def create_category(
    category: Category,
    current_user: User = Depends(get_current_active_user),
):
    """Create a new Category."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to create categories"
        )
    return catalog_service.create_category(category)


@router.delete("/categories/{name}")
async def delete_category(
    name: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a Category."""
    if not check_permission(UserPermission.CI_DELETE, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to delete categories"
        )
    return catalog_service.delete_category(name)


@router.put("/categories/{name}")
async def update_category(
    name: str,
    update: CategoryUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """Rename a Category."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to update categories"
        )
    return catalog_service.update_category(name, update.name)


@router.get("/categories/{name}/usage")
async def get_category_usage(name: str):
    """Count CIs in a Category."""
    return catalog_service.get_category_usage(name)


# --- Hardware Models ---


class HardwareModelUpdate(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    category: Optional[str] = None
    owner: Optional[str] = None


@router.get("/hardware", response_model=List[Dict[str, Any]])
async def get_hardware_catalog(current_user: User = Depends(get_current_active_user)):
    """Fetch the Hardware Catalog."""
    return catalog_service.get_hardware_catalog()


@router.post("/hardware")
async def create_hardware_model(
    item: HardwareModel,
    current_user: User = Depends(get_current_active_user),
):
    """Create or Update a Hardware Model."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to create hardware models"
        )
    return catalog_service.create_hardware_model(item)


@router.delete("/hardware/{brand}/{model}")
async def delete_hardware_model(
    brand: str,
    model: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a Hardware Model."""
    if not check_permission(UserPermission.CI_DELETE, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to delete hardware models"
        )
    return catalog_service.delete_hardware_model(brand, model)


@router.put("/hardware/{brand}/{model}")
async def update_hardware_model(
    brand: str,
    model: str,
    update: HardwareModelUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """Update Hardware Model properties or Rename it."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to update hardware models"
        )
    # Convert Pydantic update model to core HardwareModel (partial)
    # The service expects a HardwareModel object for update fields, but let's check checking service signature
    # Service expects: update_hardware_model(brand, model, update: HardwareModel)
    # So we need to adapt HardwareModelUpdate to HardwareModel
    hw_update = HardwareModel(
        brand=update.brand
        or brand,  # Fallback to existing if not changing (but service handles logic)
        model=update.model or model,
        category=update.category,
        owner=update.owner,
    )
    return catalog_service.update_hardware_model(brand, model, hw_update)


@router.get("/hardware/{brand}/{model}/usage")
async def get_hardware_usage(brand: str, model: str):
    """Count CIs of a Hardware Model."""
    return catalog_service.get_hardware_usage(brand, model)


@router.post("/hardware/assign_metric")
async def assign_metric_to_model(
    brand: str,
    model: str,
    metric_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Link a Hardware Model to a Metric Definition."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to assign metrics")
    return catalog_service.assign_metric_to_model(brand, model, metric_id)


@router.post("/hardware/unassign_metric")
async def unassign_metric_from_model(
    brand: str,
    model: str,
    metric_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Unlink a Hardware Model from a Metric Definition."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to unassign metrics"
        )
    return catalog_service.unassign_metric_from_model(brand, model, metric_id)


# --- Owner Groups ---


class OwnerGroupUpdate(BaseModel):
    name: Optional[str] = None
    users: Optional[List[dict]] = None


@router.get("/owners", response_model=List[Dict[str, Any]])
async def get_owners(current_user: User = Depends(get_current_active_user)):
    """Fetch all Owner Groups and their Users."""
    return catalog_service.get_owners()


@router.post("/owners")
async def create_owner_group(
    group: OwnerGroup,
    current_user: User = Depends(get_current_active_user),
):
    """Create or Update an Owner Group."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to create owner groups"
        )
    return catalog_service.create_owner_group(group)


@router.delete("/owners/{name}")
async def delete_owner_group(
    name: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete an Owner Group."""
    if not check_permission(UserPermission.CI_DELETE, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to delete owner groups"
        )
    return catalog_service.delete_owner_group(name)


@router.put("/owners/{name}")
async def update_owner_group(
    name: str,
    update: OwnerGroupUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """Update an Owner Group."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to update owner groups"
        )
    # Adapt OwnerGroupUpdate to OwnerGroup for service
    group_update = OwnerGroup(name=update.name or name, users=update.users or [])
    # Service distinguishes None users from empty list, so we must be careful.
    # The service logic: 'if update.users is not None'.
    # Our Pydantic model 'OwnerGroup' has 'users' as Optional, defaulting to [].
    # But OwnerGroupUpdate has 'users' as Optional[List[dict]] = None.
    # So we can pass specific logic or just reuse OwnerGroup but knowing that users=[] is valid.
    # Let's check service again.
    # Service: if update.name ... if update.users is not None ...
    # So we need to pass an object that has .name and .users attributes matching checks.
    # We can just verify if users is passed.

    # Actually, let's just use the Pydantic model directly across boundaries if possible.
    # Or create a wrapper object.

    # Constructing a dynamic object or re-using OwnerGroup works if we trust the defaults.
    # OwnerGroup defaults users to []. If we pass [], service will replace users with empty list.
    # If update.users is None, we want to NOT update users.
    # But passing OwnerGroup(users=[]) means users is [].
    # We might need to modify service to accept None explicitly or modify how we call it.
    # Service expects 'update: OwnerGroup'.
    # If we pass OwnerGroup(name="foo", users=[]), standard default, service writes users=[].
    # But we want 'None' to mean 'No Change'.
    # Solution: The Service should probably accept OwnerGroupUpdate or **kwargs.
    # But since I already wrote the Service to take OwnerGroup and check 'if update.users is not None',
    # and OwnerGroup.users defaults to [], it will always be not None (list) unless I explicitly set it to None.
    # OwnerGroup definition: users: Optional[List[dict]] = []

    # So OwnerGroup(name="foo", users=None) is valid.
    og = OwnerGroup(name=update.name or name, users=update.users)
    return catalog_service.update_owner_group(name, og)


@router.get("/owners/{name}/usage")
async def get_owner_usage(name: str):
    """Get usage statistics for an Owner Group."""
    return catalog_service.get_owner_usage(name)


@router.post("/owners/{group_name}/users")
async def link_user_to_group(
    group_name: str,
    user: User,
    current_user: User = Depends(get_current_active_user),
):
    """Add a user to an Owner Group."""
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to link users to owner groups"
        )
    # User model has name, email, phone.
    # Service expects user_data dict.
    return catalog_service.link_user_to_group(group_name, user.dict())


@router.delete("/owners/{group_name}/users/{user_name}")
async def unlink_user_from_group(
    group_name: str,
    user_name: str,
    current_user: User = Depends(get_current_active_user),
):
    """Remove a user from an Owner Group."""
    if not check_permission(UserPermission.CI_DELETE, current_user):
        raise HTTPException(
            status_code=403, detail="Not authorized to unlink users from owner groups"
        )
    return catalog_service.unlink_user_from_group(group_name, user_name)
