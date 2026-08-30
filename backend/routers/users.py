from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from models.sql_models import User as PgUser
from models.user import User, UserCreate, UserPermission, UserResetRequest, UserUpdate
from postgres_db import get_pg_db
from repositories import user_repo
from repositories.user_repo import UserRepository
from services import audit_service
from services.auth_service import check_permission, get_current_active_user
from sqlalchemy.orm import Session
from utils.security import get_password_hash

# Standardized user audit constants
AUDIT_TARGET_TYPE_USER = "user"
AUDIT_SOURCE_USERS = "users"

AUDIT_OUTCOME_SUCCESS = "SUCCESS"
AUDIT_OUTCOME_VALIDATION_FAILURE = "VALIDATION_FAILURE"

AUDIT_EVENT_USER_CREATE = "USER_CREATE"
AUDIT_EVENT_USER_UPDATE = "USER_UPDATE"
AUDIT_EVENT_USER_DELETE = "USER_DELETE"
AUDIT_EVENT_USER_PASSWORD_RESET = "USER_PASSWORD_RESET"
AUDIT_EVENT_USER_DEACTIVATE = "USER_DEACTIVATE"  # PR 3 WU3 — logical deactivation
AUDIT_REASON_CREATE_SUCCESS = "user_created"
AUDIT_REASON_UPDATE_SUCCESS = "user_updated"
AUDIT_REASON_DELETE_SUCCESS = "user_deleted"
AUDIT_REASON_RESET_SUCCESS = "password_reset"
AUDIT_REASON_DEACTIVATE_SUCCESS = "user_deactivated"  # PR 3 WU3
AUDIT_REASON_ALREADY_INACTIVE = "user_already_inactive"  # PR 3 WU3
AUDIT_REASON_MISSING_PERMISSION = "missing_permission"
AUDIT_REASON_USER_EXISTS = "user_already_exists"
AUDIT_REASON_USER_NOT_FOUND = "user_not_found"
AUDIT_REASON_PASSWORD_REQUIRED = "password_required"

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    responses={404: {"description": "Not found"}},
)


# Helper to convert PG Model to Pydantic Model
def map_pg_user_to_pydantic(pg_user: PgUser) -> User:
    return User(
        username=pg_user.username,
        role=pg_user.role,
        permissions=pg_user.permissions,
        allowed_locations=pg_user.allowed_locations,
        allowed_ci_types=pg_user.allowed_ci_types,
        phone=pg_user.phone,
        email=pg_user.email,
        disabled=not pg_user.is_active,
        force_password_change=pg_user.force_password_change,
    )


@router.get("/", response_model=list[User])
async def list_users(
    current_user: User = Depends(get_current_active_user), db: Session = Depends(get_pg_db)
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to view users")

    users = user_repo.get_users(db)
    return [map_pg_user_to_pydantic(u) for u in users]


@router.post("/", response_model=User)
async def create_user(
    request: Request,
    user: UserCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserPermission.USER_MANAGE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=user.username,
            reason=AUDIT_REASON_MISSING_PERMISSION,
            source=AUDIT_SOURCE_USERS,
        )
        raise HTTPException(status_code=403, detail="Not authorized to create users")

    existing = user_repo.get_user_by_username(db, user.username)
    if existing:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_USER_CREATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=user.username,
            target_label=user.username,
            reason=AUDIT_REASON_USER_EXISTS,
            source=AUDIT_SOURCE_USERS,
            context={
                "changed_fields": ["username"],
                "required_permission": UserPermission.USER_MANAGE.value,
            },
        )
        raise HTTPException(status_code=400, detail="Username already registered")

    new_user = user_repo.create_user(db, user)
    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_USER_CREATE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_USER,
        target_id=str(new_user.username),
        target_label=str(new_user.username),
        reason=AUDIT_REASON_CREATE_SUCCESS,
        source=AUDIT_SOURCE_USERS,
        context={
            "changed_fields": ["username", "role", "tier"],
            "required_permission": UserPermission.USER_MANAGE.value,
        },
    )
    return map_pg_user_to_pydantic(new_user)


@router.put("/{username}", response_model=User)
async def update_user(
    request: Request,
    username: str,
    update_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserPermission.USER_MANAGE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            reason=AUDIT_REASON_MISSING_PERMISSION,
            source=AUDIT_SOURCE_USERS,
        )
        raise HTTPException(status_code=403, detail="Not authorized to update users")

    update_payload = update_data.dict(exclude_unset=True)
    changed_fields = [field for field in update_payload.keys() if field != "password"]

    updated_user = user_repo.update_user(db, username, update_data)
    if not updated_user:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_USER_UPDATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            target_label=username,
            reason=AUDIT_REASON_USER_NOT_FOUND,
            source=AUDIT_SOURCE_USERS,
            context={
                "changed_fields": changed_fields,
                "required_permission": UserPermission.USER_MANAGE.value,
            },
        )
        raise HTTPException(status_code=404, detail="User not found")

    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_USER_UPDATE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_USER,
        target_id=username,
        target_label=username,
        reason=AUDIT_REASON_UPDATE_SUCCESS,
        source=AUDIT_SOURCE_USERS,
        context={
            "changed_fields": changed_fields,
            "required_permission": UserPermission.USER_MANAGE.value,
        },
    )

    return map_pg_user_to_pydantic(updated_user)


@router.delete("/{username}")
async def delete_user(
    request: Request,
    username: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserPermission.USER_MANAGE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            reason=AUDIT_REASON_MISSING_PERMISSION,
            source=AUDIT_SOURCE_USERS,
        )
        raise HTTPException(status_code=403, detail="Not authorized to delete users")

    success = user_repo.delete_user(db, username)
    if not success:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_USER_DELETE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            target_label=username,
            reason=AUDIT_REASON_USER_NOT_FOUND,
            source=AUDIT_SOURCE_USERS,
            context={"required_permission": UserPermission.USER_MANAGE.value},
        )
        raise HTTPException(status_code=404, detail="User not found")

    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_USER_DELETE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_USER,
        target_id=username,
        target_label=username,
        reason=AUDIT_REASON_DELETE_SUCCESS,
        source=AUDIT_SOURCE_USERS,
        context={"required_permission": UserPermission.USER_MANAGE.value},
    )

    return {"status": "success", "message": f"User {username} deleted"}


@router.post("/{username}/reset")
async def reset_password(
    request: Request,
    username: str,
    reset_data: UserResetRequest | None = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_pg_db),
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserPermission.USER_MANAGE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            reason=AUDIT_REASON_MISSING_PERMISSION,
            source=AUDIT_SOURCE_USERS,
        )
        raise HTTPException(status_code=403, detail="Not authorized to reset passwords")

    if not reset_data or not reset_data.new_password:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_USER_PASSWORD_RESET,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            target_label=username,
            reason=AUDIT_REASON_PASSWORD_REQUIRED,
            source=AUDIT_SOURCE_USERS,
            context={"required_permission": UserPermission.USER_MANAGE.value},
        )
        raise HTTPException(status_code=400, detail="New password required")

    # Reuse update logic
    update_payload = UserUpdate(password=reset_data.new_password)

    db_user = user_repo.get_user_by_username(db, username)
    if not db_user:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_USER_PASSWORD_RESET,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            target_label=username,
            reason=AUDIT_REASON_USER_NOT_FOUND,
            source=AUDIT_SOURCE_USERS,
            context={"required_permission": UserPermission.USER_MANAGE.value},
        )
        raise HTTPException(status_code=404, detail="User not found")

    db_user.hashed_password = get_password_hash(reset_data.new_password)
    db_user.force_password_change = True
    db.commit()

    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_USER_PASSWORD_RESET,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_USER,
        target_id=username,
        target_label=username,
        reason=AUDIT_REASON_RESET_SUCCESS,
        source=AUDIT_SOURCE_USERS,
        context={"required_permission": UserPermission.USER_MANAGE.value},
    )

    return {"status": "success", "message": f"Password reset for {username}."}


# ---------------------------------------------------------------------------
# PR 3 — WU3: logical user deactivation. POST (not DELETE) to keep the
# logical intent explicit. Historical ticket snapshots stay valid; the user
# row is preserved with ``is_active=False``.
# Permission gate: ``USER_MANAGE``. Returns 204 on success, 404 if the user
# does not exist, 409 if already inactive.
# ---------------------------------------------------------------------------


@router.post("/{username}/deactivate", status_code=204)
async def deactivate_user(
    request: Request,
    username: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[Session, Depends(get_pg_db)],
):
    if not check_permission(UserPermission.USER_MANAGE, current_user):
        audit_service.record_denied(
            db=db,
            request=request,
            actor=current_user,
            required_permission=UserPermission.USER_MANAGE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            reason=AUDIT_REASON_MISSING_PERMISSION,
            source=AUDIT_SOURCE_USERS,
        )
        raise HTTPException(status_code=403, detail="Not authorized to deactivate users")

    db_user = UserRepository.get_by_username(db, username)
    if not db_user:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_USER_DEACTIVATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            target_label=username,
            reason=AUDIT_REASON_USER_NOT_FOUND,
            source=AUDIT_SOURCE_USERS,
            context={"required_permission": UserPermission.USER_MANAGE.value},
        )
        raise HTTPException(status_code=404, detail="User not found")

    if db_user.is_active is False:
        audit_service.record_critical_change(
            db=db,
            request=request,
            actor=current_user,
            event_type=AUDIT_EVENT_USER_DEACTIVATE,
            outcome=AUDIT_OUTCOME_VALIDATION_FAILURE,
            target_type=AUDIT_TARGET_TYPE_USER,
            target_id=username,
            target_label=username,
            reason=AUDIT_REASON_ALREADY_INACTIVE,
            source=AUDIT_SOURCE_USERS,
            context={"required_permission": UserPermission.USER_MANAGE.value},
        )
        raise HTTPException(status_code=409, detail="user_already_inactive")

    UserRepository.deactivate(db, username, actor=current_user.username)

    audit_service.record_critical_change(
        db=db,
        request=request,
        actor=current_user,
        event_type=AUDIT_EVENT_USER_DEACTIVATE,
        outcome=AUDIT_OUTCOME_SUCCESS,
        target_type=AUDIT_TARGET_TYPE_USER,
        target_id=username,
        target_label=username,
        reason=AUDIT_REASON_DEACTIVATE_SUCCESS,
        source=AUDIT_SOURCE_USERS,
        context={"required_permission": UserPermission.USER_MANAGE.value},
    )

    return None
