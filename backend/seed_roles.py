import asyncio
import logging

from database import close_db, get_db
from models.user import AIPermission, UserPermission
from postgres_db import SessionLocal  # feat-489 Phase 3: PG backfill session factory

logger = logging.getLogger(__name__)

SYSTEM_ROLE_PERMISSION_UPGRADES = {
    "ADMIN": [
        UserPermission.MQTT_READ.value,
        UserPermission.MQTT_MAPPING_MANAGE.value,
        UserPermission.CI_APPROVE_PROPOSAL.value,
        # feat-489 Slice 1B: admins can drive the bulk CSV importer
        # (POST /api/cmdb/proposals/bulk-import).
        UserPermission.CI_BULK_IMPORT.value,
    ],
    "OPERATOR": [
        UserPermission.MQTT_READ.value,
        UserPermission.MQTT_MAPPING_MANAGE.value,
        UserPermission.ITSM_VIEW.value,
        UserPermission.ITSM_EDIT.value,
        # feat-cmdb-ai-handoff: OPERATOR can approve/revoke AI-submitted proposals.
        UserPermission.CI_APPROVE_PROPOSAL.value,
        # feat-489 Slice 1B: operators can drive the bulk CSV importer too
        # (same review surface, distinct audit profile).
        UserPermission.CI_BULK_IMPORT.value,
    ],
}


# feat-cmdb-ai-handoff — AI roles only gain AI_PROPOSE_CI; never CI_APPROVE_PROPOSAL.
AI_ROLE_PERMISSION_UPGRADES = {
    "AI_DIAGNOSTIC": [AIPermission.AI_PROPOSE_CI.value],
    "AI_OPERATOR": [AIPermission.AI_PROPOSE_CI.value],
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
                UserPermission.ITSM_VIEW.value,
                UserPermission.ITSM_EDIT.value,
                UserPermission.CI_APPROVE_PROPOSAL.value,
                # feat-489 Slice 1B: bulk CSV importer.
                UserPermission.CI_BULK_IMPORT.value,
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
                AIPermission.AI_PROPOSE_CI.value,
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
                AIPermission.AI_PROPOSE_CI.value,
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
                    permitted_upgrades = list(SYSTEM_ROLE_PERMISSION_UPGRADES.get(name, []))
                    # feat-cmdb-ai-handoff: AI roles get AI-only upgrade grants.
                    if name in AI_ROLE_PERMISSION_UPGRADES:
                        permitted_upgrades.extend(AI_ROLE_PERMISSION_UPGRADES[name])
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


async def backfill_user_permissions_from_roles() -> None:
    """feat-489 Phase 3: propagate each Role's permissions into every
    User row that holds that role. ``fill-missing`` semantics — the
    user's existing permissions are preserved, and any role permission
    that is missing on the user is added. Per-user revocations are NOT
    overridden (the role is the floor, not the ceiling).

    Mirrors the precedent set by ``SYSTEM_ROLE_PERMISSION_UPGRADES``:
    re-running on every boot guarantees that OPERATORs created before
    ``CI_APPROVE_PROPOSAL`` existed pick it up automatically, without
    an admin having to manually edit ``User.permissions``.

    Both stores are kept in parity:

    * **Postgres** (``users.permissions``) — primary auth store; this
      is what ``auth_service.check_permission`` reads. Idempotent fill
      via a single UPDATE that unions role perms onto existing user
      perms.
    * **Neo4j** (``:User.permissions``) — graph store used by some
      read paths (e.g. ``User`` nodes traversed from CI topology).
      Idempotent fill via MATCH/SET with a Cypher list-comprehension.

    The backfill is a no-op on roles that have no users, on users with
    a role that has no matching ``:Role`` row, and on users whose
    permissions already cover the role's permission set. Errors are
    logged but do not block startup — if the backfill fails, the role
    upgrade that ``seed_roles`` already committed still applies to
    future users created with that role.
    """
    print("Backfilling User.permissions from Role.permissions...")

    # ── Postgres backfill ────────────────────────────────────────────────────
    # Note: in this architecture, Roles live in Neo4j (:Role nodes), while
    # Users live in both Postgres (primary auth) and Neo4j. We query the
    # canonical role definitions from Neo4j first, then update Postgres users.
    try:
        from sqlalchemy import text

        # 1. Fetch current role permissions from Neo4j
        role_perms_map: dict[str, list[str]] = {}
        try:
            driver = get_db()
            with driver.session() as neo_session:
                res = neo_session.run("MATCH (r:Role) RETURN r.name AS name, r.permissions AS perms")
                for rec in res:
                    if rec["name"] and rec["perms"]:
                        role_perms_map[rec["name"]] = list(rec["perms"])
        except Exception:
            logger.warning("Could not read roles from Neo4j for Postgres backfill")

        if role_perms_map:
            db = SessionLocal()
            try:
                for role_name, role_perms in role_perms_map.items():
                    rows = db.execute(
                        text(
                            """
                            UPDATE users
                            SET permissions = (
                                SELECT ARRAY(
                                    SELECT DISTINCT unnest(coalesce(permissions, '{}') || :role_perms)
                                )
                            )
                            WHERE role = :role_name
                            RETURNING username, role, permissions
                            """
                        ),
                        {"role_name": role_name, "role_perms": role_perms},
                    ).fetchall()
                    for username, r_name, perms in rows:
                        print(f"  PG: user '{username}' ({r_name}) → {len(perms)} permissions")
                db.commit()
            finally:
                db.close()
    except Exception:
        # Non-fatal: log and continue. The role upgrade itself is already
        # committed; this is a best-effort backfill for users created
        # before the new permissions existed.
        import traceback

        print("  PG backfill skipped:")
        traceback.print_exc()

    # ── Neo4j backfill ───────────────────────────────────────────────────────
    try:
        driver = get_db()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (u:User), (r:Role {name: u.role})
                WITH u, r,
                     [p IN r.permissions WHERE NOT p IN coalesce(u.permissions, [])] AS missing
                WHERE size(missing) > 0
                SET u.permissions = coalesce(u.permissions, []) + missing
                RETURN u.username AS username, u.role AS role, missing AS added
                """
            )
            counts = {"users_updated": 0, "perms_added": 0}
            for record in result:
                added = record["added"] or []
                counts["users_updated"] += 1
                counts["perms_added"] += len(added)
                print(
                    f"  NEO4J: user '{record['username']}' ({record['role']}) "
                    f"+{len(added)} perm(s): {added}"
                )
            if counts["users_updated"] == 0:
                print("  NEO4J: no users needed backfill (all up to date)")
            else:
                print(
                    f"  NEO4J: {counts['users_updated']} user(s) updated, "
                    f"{counts['perms_added']} permission(s) added"
                )
        close_db()
    except Exception:
        import traceback

        print("  NEO4J backfill skipped:")
        traceback.print_exc()

    print("User.permissions backfill complete.")


if __name__ == "__main__":
    asyncio.run(seed_roles())
