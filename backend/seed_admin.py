import asyncio
from database import get_db, close_db
from postgres_db import SessionLocal
from models.sql_models import User
from models.user import UserCreate, UserRole, UserPermission
from utils.security import get_password_hash

async def seed_admin():
    print("Seeding Default Admin User...")
    
    # 1. Seed in Postgres (Primary Auth Store)
    db = SessionLocal()
    try:
        admin_user_pg = db.query(User).filter(User.username == 'admin').first()
        if admin_user_pg:
            print("Admin user already exists in Postgres.")
        else:
            password = "admin" # Default password
            hashed = get_password_hash(password)
            all_perms = [p.value for p in UserPermission]
            
            new_admin = User(
                username='admin',
                hashed_password=hashed,
                role=UserRole.ADMIN.value,
                permissions=all_perms,
                allowed_locations=[],
                allowed_ci_types=[],
                is_active=True,
                force_password_change=True  # Force change on first login
            )
            db.add(new_admin)
            db.commit()
            print("Admin user created in Postgres: admin / admin (Force password change: True)")
    finally:
        db.close()

    # 2. Seed in Neo4j (Graph Store)
    try:
        driver = get_db()
        check_query = "MATCH (u:User {username: 'admin'}) RETURN u"
        results, _, _ = driver.execute_query(check_query)
        
        if results:
            print("Admin user already exists in Neo4j.")
        else:
            password = "admin" # Default password
            hashed = get_password_hash(password)
            all_perms = [p.value for p in UserPermission]
            
            create_query = """
            CREATE (u:User {
                username: 'admin',
                password: $password,
                role: $role,
                permissions: $permissions,
                allowed_locations: [],
                allowed_ci_types: [],
                disabled: false,
                force_password_change: true
            }) RETURN u
            """
            
            driver.execute_query(
                create_query, 
                password=hashed, 
                role=UserRole.ADMIN.value,
                permissions=all_perms
            )
            print("Admin user created in Neo4j: admin / admin")
    except Exception as e:
        print(f"Warning: Could not seed admin in Neo4j (might not be ready or needed): {e}")
    finally:
        try:
            close_db()
        except:
            pass

if __name__ == "__main__":
    asyncio.run(seed_admin())
