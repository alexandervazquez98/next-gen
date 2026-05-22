import asyncio
import os
import secrets
from database import get_db, close_db
from postgres_db import SessionLocal
from models.sql_models import User
from models.user import UserCreate, UserRole, UserPermission
from utils.security import get_password_hash


async def seed_admin():
    # Read admin credentials from environment
    admin_username = os.environ.get("ADMIN_DEFAULT_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_DEFAULT_PASSWORD")

    if not admin_password:
        admin_password = secrets.token_urlsafe(24)
        print(f"[SEED_ADMIN] No ADMIN_DEFAULT_PASSWORD env var set — generated random password:")
        print(f"[SEED_ADMIN] username: {admin_username}")
        print(f"[SEED_ADMIN] password: {admin_password}")
        print("[SEED_ADMIN] Save this password! It will not be shown again.")
    else:
        print(f"[SEED_ADMIN] Using credentials from environment for admin user.")

    # 1. Seed in Postgres (Primary Auth Store)
    db = SessionLocal()
    try:
        admin_user_pg = db.query(User).filter(User.username == admin_username).first()
        if admin_user_pg:
            print(f"Admin user '{admin_username}' already exists in Postgres.")
        else:
            hashed = get_password_hash(admin_password)
            all_perms = [p.value for p in UserPermission]

            new_admin = User(
                username=admin_username,
                hashed_password=hashed,
                role=UserRole.ADMIN.value,
                tier="T3",
                permissions=all_perms,
                allowed_locations=[],
                allowed_ci_types=[],
                is_active=True,
                force_password_change=True,  # Force change on first login
            )
            db.add(new_admin)
            db.commit()
            print(
                f"Admin user '{admin_username}' created in Postgres (force_password_change=True)"
            )
    finally:
        db.close()

    # 2. Seed in Neo4j (Graph Store)
    try:
        driver = get_db()
        check_query = "MATCH (u:User {username: $username}) RETURN u"
        results, _, _ = driver.execute_query(check_query, username=admin_username)

        if results:
            print(f"Admin user '{admin_username}' already exists in Neo4j.")
        else:
            password = admin_password
            hashed = get_password_hash(password)
            all_perms = [p.value for p in UserPermission]

            create_query = """
            CREATE (u:User {
                username: $username,
                password: $password,
                role: $role,
                tier: 'T3',
                permissions: $permissions,
                allowed_locations: [],
                allowed_ci_types: [],
                disabled: false,
                force_password_change: true
            }) RETURN u
            """

            driver.execute_query(
                create_query,
                username=admin_username,
                password=hashed,
                role=UserRole.ADMIN.value,
                permissions=all_perms,
            )
            print(f"Admin user '{admin_username}' created in Neo4j.")
    except Exception as e:
        print(
            f"Warning: Could not seed admin in Neo4j (might not be ready or needed): {e}"
        )
    finally:
        try:
            close_db()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(seed_admin())