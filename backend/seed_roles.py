import asyncio

from database import close_db, get_db
from models.user import AIPermission, UserPermission

SYSTEM_ROLE_PERMISSION_UPGRADES = {
    "ADMIN": [
        UserPermission.MQTT_READ.value,
        UserPermission.MQTT_MAPPING_MANAGE.value,
    ],
    "OPERATOR": [
        UserPermission.MQTT_READ.value,
        UserPermission.MQTT_MAPPING_MANAGE.value,
    ],
}


async def seed_roles():
    print("Seeding Default System Roles...")
    driver = get_db()

    # Define roles
    roles = {
        "ADMIN": {
            "description": "Full System Administrator",
            "permissions": [p.value for p in UserPermission],  # ALL
            "is_system": True,
        },
        "OPERATOR": {
            "description": "Operational Staff",
            "permissions": [
                UserPermission.EVENT_VIEW.value,
                UserPermission.EVENT_ACK.value,
                UserPermission.EVENT_CLOSE.value,
                UserPermission.EVENT_FORCED_CLOSE.value,
                UserPermission.CI_VIEW.value,
                UserPermission.CI_EDIT.value,
                UserPermission.RUN_DIAGNOSTICS.value,
                UserPermission.METRICS_VIEW.value,
                UserPermission.MQTT_READ.value,
                UserPermission.MQTT_MAPPING_MANAGE.value,
            ],
            "is_system": True,
        },
        "VIEWER": {
            "description": "Read-Only Access",
            "permissions": [
                UserPermission.EVENT_VIEW.value,
                UserPermission.CI_VIEW.value,
            ],
            "is_system": True,
        },
        "AI_DIAGNOSTIC": {
            "description": "AI agent for initial triage and investigation",
            "permissions": [
                AIPermission.AI_VIEW_ALL.value,
                AIPermission.AI_RUN_DIAGNOSTIC.value,
                AIPermission.AI_EVENT_ACK.value,
                AIPermission.AI_EVENT_COMMENT.value,
                AIPermission.AI_CI_UPDATE_METADATA.value,
                AIPermission.AI_DICTIONARY_PREVIEW.value,
            ],
            "is_system": True,
        },
        "AI_OPERATOR": {
            "description": "AI agent for full incident lifecycle management",
            "permissions": [
                AIPermission.AI_VIEW_ALL.value,
                AIPermission.AI_RUN_DIAGNOSTIC.value,
                AIPermission.AI_EVENT_ACK.value,
                AIPermission.AI_EVENT_COMMENT.value,
                AIPermission.AI_EVENT_CLOSE.value,
                AIPermission.AI_CI_UPDATE_METADATA.value,
                AIPermission.AI_DICTIONARY_PREVIEW.value,
            ],
            "is_system": True,
        },
    }

    with driver.session() as session:
        for name, data in roles.items():
            # Check if exists
            res = session.run("MATCH (r:Role {name: $name}) RETURN r", name=name)
            existing = res.single()
            if not existing:
                print(f"Creating role: {name}")
                session.run(
                    """
                    CREATE (r:Role {
                        name: $name,
                        description: $desc,
                        permissions: $perms,
                        is_system: $sys
                    })
                    """,
                    name=name,
                    desc=data["description"],
                    perms=data["permissions"],
                    sys=data["is_system"],
                )
            else:
                # System roles are protected from destructive overwrite once created.
                # They may still receive additive permission upgrades required by the
                # current seed definition so existing deployments pick up new grants.
                # If is_system is None (key absent or null), treat as non-system and allow update.
                existing_role = existing.get("r", {})
                existing_is_system = existing_role.get("is_system")
                if existing_is_system is True:
                    current_permissions = list(existing_role.get("permissions") or [])
                    permitted_upgrades = SYSTEM_ROLE_PERMISSION_UPGRADES.get(name, [])
                    missing_permissions = [
                        permission
                        for permission in permitted_upgrades
                        if permission in data["permissions"]
                        and permission not in current_permissions
                    ]

                    if missing_permissions:
                        print(f"Upgrading system role {name} with explicit permissions")
                        session.run(
                            """
                            MATCH (r:Role {name: $name})
                            SET r.permissions = $perms
                            """,
                            name=name,
                            perms=current_permissions + missing_permissions,
                        )
                    else:
                        print(f"Skipping system role {name} — already up to date")
                else:
                    print(f"Updating non-system role: {name}")
                    session.run(
                        """
                        MATCH (r:Role {name: $name})
                        SET r.permissions = $perms, r.is_system = false
                        """,
                        name=name,
                        perms=data["permissions"],
                    )

    print("Roles Seeded.")
    close_db()


if __name__ == "__main__":
    asyncio.run(seed_roles())
