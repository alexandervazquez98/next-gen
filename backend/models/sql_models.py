from sqlalchemy import Column, Integer, String, Boolean, ARRAY
from postgres_db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email = Column(String, index=True, nullable=True)
    phone = Column(String, nullable=True)
    role = Column(String, default="VIEWER")
    is_active = Column(Boolean, default=True)
    force_password_change = Column(Boolean, default=False)

    tier = Column(String, default="T1")

    # RBAC & ACLs stored as Arrays of Strings
    permissions = Column(ARRAY(String), default=[])
    allowed_locations = Column(ARRAY(String), default=[])
    allowed_ci_types = Column(ARRAY(String), nullable=True)
