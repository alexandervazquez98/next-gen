import asyncio
import os
import sys
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add backend dir to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import get_db, close_db
from postgres_db import SessionLocal
from models.sql_models import User
from models.user import UserRole, UserPermission
from utils.security import get_password_hash

async def reset_admin():
    admin_username = os.environ.get("ADMIN_DEFAULT_USERNAME", "admin")
    
    # Get password from arguments or prompt
    if len(sys.argv) > 1:
        admin_password = sys.argv[1]
    else:
        import getpass
        admin_password = getpass.getpass("Enter new admin password: ")
        confirm_password = getpass.getpass("Confirm password: ")
        if admin_password != confirm_password:
            print("Error: Passwords do not match.")
            return

    if not admin_password:
        print("Error: Password cannot be empty.")
        return

    hashed = get_password_hash(admin_password)
    all_perms = [p.value for p in UserPermission]

    # 1. Update in Postgres
    db = SessionLocal()
    try:
        admin_user_pg = db.query(User).filter(User.username == admin_username).first()
        if admin_user_pg:
            admin_user_pg.hashed_password = hashed
            admin_user_pg.is_active = True
            admin_user_pg.force_password_change = False  # Reset force change so they can login directly
            admin_user_pg.role = UserRole.ADMIN.value
            admin_user_pg.permissions = all_perms
            db.commit()
            print(f"Password for admin user '{admin_username}' successfully updated in Postgres.")
        else:
            new_admin = User(
                username=admin_username,
                hashed_password=hashed,
                role=UserRole.ADMIN.value,
                tier="T3",
                permissions=all_perms,
                allowed_locations=[],
                allowed_ci_types=[],
                is_active=True,
                force_password_change=False,
            )
            db.add(new_admin)
            db.commit()
            print(f"Admin user '{admin_username}' created in Postgres.")
    except Exception as e:
        print(f"Error updating admin in Postgres: {e}")
        db.rollback()
    finally:
        db.close()

    # 2. Update in Neo4j
    try:
        driver = get_db()
        check_query = "MATCH (u:User {username: $username}) RETURN u"
        results, _, _ = driver.execute_query(check_query, username=admin_username)

        if results:
            update_query = """
            MATCH (u:User {username: $username})
            SET u.password = $password,
                u.disabled = false,
                u.role = $role,
                u.permissions = $permissions,
                u.force_password_change = false
            RETURN u
            """
            driver.execute_query(
                update_query,
                username=admin_username,
                password=hashed,
                role=UserRole.ADMIN.value,
                permissions=all_perms,
            )
            print(f"Password for admin user '{admin_username}' successfully updated in Neo4j.")
        else:
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
                force_password_change: false
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
        print(f"Warning: Could not update admin in Neo4j: {e}")
    finally:
        try:
            close_db()
        except:
            pass

if __name__ == "__main__":
    asyncio.run(reset_admin())
