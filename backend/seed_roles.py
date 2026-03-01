
import asyncio
from database import get_db, close_db
from models.user import UserPermission

async def seed_roles():
    print("Seeding Default System Roles...")
    driver = get_db()
    
    # Define roles
    roles = {
        "ADMIN": {
            "description": "Full System Administrator",
            "permissions": [p.value for p in UserPermission], # ALL
            "is_system": True
        },
        "OPERATOR": {
            "description": "Operational Staff",
            "permissions": [
                UserPermission.EVENT_VIEW.value,
                UserPermission.EVENT_ACK.value,
                UserPermission.EVENT_CLOSE.value,
                UserPermission.CI_VIEW.value,
                UserPermission.CI_EDIT.value,
                UserPermission.RUN_DIAGNOSTICS.value,
                UserPermission.METRICS_VIEW.value
            ],
            "is_system": True
        },
        "VIEWER": {
            "description": "Read-Only Access",
            "permissions": [
                UserPermission.EVENT_VIEW.value,
                UserPermission.CI_VIEW.value
            ],
            "is_system": True
        }
    }
    
    with driver.session() as session:
        for name, data in roles.items():
            # Check if exists
            res = session.run("MATCH (r:Role {name: $name}) RETURN r", name=name)
            if not res.single():
                print(f"Creating role: {name}")
                session.run("""
                    CREATE (r:Role {
                        name: $name,
                        description: $desc,
                        permissions: $perms,
                        is_system: $sys
                    })
                """, name=name, desc=data["description"], perms=data["permissions"], sys=data["is_system"])
            else:
                # Optional: Update permissions if system role definition changed?
                # Probably safer to not overwrite existing customizations if system allowed it?
                # But system roles are usually fixed.
                # Let's update permissions just in case we add new features (like ROLE_MANAGE).
                print(f"Updating system role: {name}")
                session.run("""
                    MATCH (r:Role {name: $name})
                    SET r.permissions = $perms, r.is_system = true
                """, name=name, perms=data["permissions"])
                
    print("Roles Seeded.")
    close_db()

if __name__ == "__main__":
    asyncio.run(seed_roles())
