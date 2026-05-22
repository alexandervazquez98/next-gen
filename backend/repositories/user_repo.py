from sqlalchemy.orm import Session
from sqlalchemy.future import select
from models.sql_models import User
from models.user import UserCreate, UserUpdate
from utils.security import get_password_hash


def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()


def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(User).offset(skip).limit(limit).all()


def create_user(db: Session, user: UserCreate):
    hashed_password = get_password_hash(user.password)
    # Convert Pydantic Enums to strings for DB storage if needed
    permissions_str = [p.value for p in user.permissions]

    db_user = User(
        username=user.username,
        hashed_password=hashed_password,
        role=user.role,
        tier=user.tier,
        permissions=permissions_str,
        allowed_locations=user.allowed_locations,
        allowed_ci_types=user.allowed_ci_types,
        phone=user.phone,
        email=user.email,
        is_active=True,
        force_password_change=False,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(db: Session, username: str, user_update: UserUpdate):
    db_user = get_user_by_username(db, username)
    if not db_user:
        return None

    if user_update.password:
        db_user.hashed_password = get_password_hash(user_update.password)
    if user_update.role:
        db_user.role = user_update.role
    if user_update.tier is not None:
        db_user.tier = user_update.tier
    if user_update.permissions is not None:
        db_user.permissions = [p.value for p in user_update.permissions]
    if user_update.allowed_locations is not None:
        db_user.allowed_locations = user_update.allowed_locations
    if user_update.allowed_ci_types is not None:
        db_user.allowed_ci_types = user_update.allowed_ci_types

    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, username: str):
    db_user = get_user_by_username(db, username)
    if db_user:
        db.delete(db_user)
        db.commit()
        return True
    return False
