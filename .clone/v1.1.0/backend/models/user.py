from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"
    CUSTOM = "CUSTOM"


class UserPermission(str, Enum):
    # Event Management
    EVENT_VIEW = "EVENT_VIEW"
    EVENT_ACK = "EVENT_ACK"
    EVENT_CLOSE = "EVENT_CLOSE"
    EVENT_FORCED_CLOSE = "EVENT_FORCED_CLOSE"

    # CI Management
    CI_VIEW = "CI_VIEW"
    CI_EDIT = "CI_EDIT"
    CI_DELETE = "CI_DELETE"

    # Diagnostics
    RUN_DIAGNOSTICS = "RUN_DIAGNOSTICS"

    # System
    USER_MANAGE = "USER_MANAGE"
    ROLE_MANAGE = "ROLE_MANAGE"

    # Visualization
    METRICS_VIEW = "METRICS_VIEW"


class Role(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[UserPermission] = []
    is_system: bool = False  # If True, cannot be deleted (e.g. ADMIN)


class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[UserPermission] = []


class RoleUpdate(BaseModel):
    description: Optional[str] = None
    permissions: Optional[List[UserPermission]] = None


class UserBase(BaseModel):
    username: str
    role: str = "VIEWER"  # Changed from Enum to str to support custom role names
    permissions: List[UserPermission] = []
    allowed_locations: List[str] = []  # List of Location Names
    allowed_ci_types: Optional[List[str]] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    tier: Literal["T1", "T2", "T3"] = "T1"


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    tier: Optional[Literal["T1", "T2", "T3"]] = None
    permissions: Optional[List[UserPermission]] = None
    allowed_locations: Optional[List[str]] = None
    allowed_ci_types: Optional[List[str]] = None


class User(UserBase):
    disabled: Optional[bool] = False
    force_password_change: Optional[bool] = False


class UserInDB(User):
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


class UserResetRequest(BaseModel):
    new_password: str
