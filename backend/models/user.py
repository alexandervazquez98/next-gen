from enum import Enum
from typing import Literal

from pydantic import BaseModel


class UserRole(str, Enum):  # noqa: UP042
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"
    CUSTOM = "CUSTOM"


class AIPermission(str, Enum):  # noqa: UP042
    """Permissions exclusive to AI agents."""

    AI_RUN_DIAGNOSTIC = "AI_RUN_DIAGNOSTIC"
    AI_VIEW_ALL = "AI_VIEW_ALL"
    AI_EVENT_ACK = "AI_EVENT_ACK"
    AI_EVENT_COMMENT = "AI_EVENT_COMMENT"
    AI_CI_UPDATE_METADATA = "AI_CI_UPDATE_METADATA"
    AI_EVENT_CLOSE = "AI_EVENT_CLOSE"
    AI_DICTIONARY_PREVIEW = "AI_DICTIONARY_PREVIEW"


class UserPermission(str, Enum):  # noqa: UP042
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
    AUDIT_VIEW = "AUDIT_VIEW"

    # Visualization
    METRICS_VIEW = "METRICS_VIEW"

    # MQTT integration
    MQTT_READ = "MQTT_READ"
    MQTT_MAPPING_MANAGE = "MQTT_MAPPING_MANAGE"


class Role(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str] = []  # Store as strings; UserPermission or AIPermission string values
    is_system: bool = False  # If True, cannot be deleted (e.g. ADMIN)


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str] = []  # Store as strings


class RoleUpdate(BaseModel):
    description: str | None = None
    permissions: list[str] | None = None


class UserBase(BaseModel):
    username: str
    role: str = UserRole.VIEWER.value
    permissions: list[str] = []  # Store as strings; validated at service layer
    allowed_locations: list[str] = []  # List of Location Names
    allowed_ci_types: list[str] | None = None
    phone: str | None = None
    email: str | None = None
    tier: Literal["T1", "T2", "T3"] = "T1"


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    password: str | None = None
    role: str | None = None
    tier: Literal["T1", "T2", "T3"] | None = None
    permissions: list[str] | None = None
    allowed_locations: list[str] | None = None
    allowed_ci_types: list[str] | None = None


class User(UserBase):
    disabled: bool | None = False
    force_password_change: bool | None = False


class CurrentUserSessionPolicy(BaseModel):
    profile: str
    idle_timeout_minutes: int | None = None
    persistent: bool = False


class UserInDB(User):
    password: str
    session_id: str | None = None
    session_policy: CurrentUserSessionPolicy | None = None


class CurrentUser(User):
    session_id: str | None = None
    session_policy: CurrentUserSessionPolicy | None = None


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


class UserResetRequest(BaseModel):
    new_password: str


