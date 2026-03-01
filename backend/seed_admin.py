
import asyncio
from database import get_db, close_db
from models.user import UserCreate, UserRole, UserPermission
from utils.security import get_password_hash

async def seed_admin():
    print("Seeding Default Admin User...")
    driver = get_db()
    
    # Check if admin exists
    check_query = "MATCH (u:User {username: 'admin'}) RETURN u"
    results, _, _ = driver.execute_query(check_query)
    
    if results:
        print("Admin user already exists.")
    else:
        password = "admin" # Default password
        hashed = get_password_hash(password)
        
        # Grant ALL permissions
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
        print("Admin user created: admin / admin")

    close_db()

if __name__ == "__main__":
    asyncio.run(seed_admin())
