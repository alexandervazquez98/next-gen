"""Seed default CMDB :Category nodes on backend boot.

Issue #489 pre-flight — without at least one Category node, every CMDB
proposal returns ``422 unknown_category`` and the AI chat cannot bootstrap
the HITL workflow. This script is idempotent (MERGE on name) and safe to
re-run on every boot.

Default category set is intentionally small and covers the inventory types
the operators typically onboard via SNMP discovery or AI chat. Operators
can still add more categories at runtime via ``POST /api/categories`` —
this seed only fills the obvious gaps so the workflow is usable on a
fresh stack.

Reference: ``backend/services/catalog_service.py::create_category`` uses
the same MERGE pattern; this script mirrors it but is invoked from
``main.py`` startup so the seed is automatic.
"""
import asyncio

from database import close_db, get_db
from services.category_icons import (
    get_default_category_icon,
    resolve_category_icon,
)

# Default category set seeded on every fresh boot.
# Names are operator-facing — do not localize here, the API returns them
# verbatim and ProposalsCmdbPage renders them as-is.
DEFAULT_CATEGORIES: list[str] = [
    "Router",
    "Switch",
    "Server",
    "Sensor",
    "Firewall",
    "Other",
]


async def seed_categories() -> None:
    """MERGE every entry in DEFAULT_CATEGORIES as a :Category node.

    Idempotent: re-running on a stack that already has these categories
    is a no-op (icon_key is preserved unless missing). Prints a short
    summary per category for boot logs.
    """
    print("Seeding default CMDB Categories...")
    driver = get_db()

    created = 0
    updated = 0
    skipped = 0

    with driver.session() as session:
        for name in DEFAULT_CATEGORIES:
            default_icon = get_default_category_icon(name)
            resolved_icon = resolve_category_icon(name, None)

            # Check existence first so we can print a clear create vs
            # update vs skip line. The MERGE itself handles all three.
            existing = session.run(
                "MATCH (c:Category {name: $name}) RETURN c.icon_key AS icon_key",
                name=name,
            ).single()

            if existing is None:
                session.run(
                    """
                    MERGE (c:Category {name: $name})
                    ON CREATE SET c.icon_key = $icon_key,
                                  c.is_system = true,
                                  c.description = $description
                    """,
                    name=name,
                    icon_key=resolved_icon,
                    description=f"Auto-seeded default category: {name}",
                )
                created += 1
                print(
                    f"  + Created Category '{name}' "
                    f"(icon_key={resolved_icon}, default_icon={default_icon})"
                )
            else:
                existing_icon = existing.get("icon_key")
                if existing_icon is None:
                    # Backfill missing icon_key with the resolved default.
                    # Even when there is no canonical mapping for the name
                    # (e.g. "Switch" / "Sensor"), resolve_category_icon falls
                    # back to "generic", which is still better than NULL.
                    session.run(
                        """
                        MATCH (c:Category {name: $name})
                            WHERE c.icon_key IS NULL
                        SET c.icon_key = $icon_key
                        """,
                        name=name,
                        icon_key=resolved_icon,
                    )
                    updated += 1
                    print(
                        f"  ~ Updated Category '{name}' "
                        f"(icon_key backfilled to '{resolved_icon}')"
                    )
                else:
                    skipped += 1
                    print(f"  . Skipped Category '{name}' (already present)")

    print(
        f"Categories seeded: {created} created, "
        f"{updated} updated, {skipped} already present."
    )
    close_db()


if __name__ == "__main__":
    asyncio.run(seed_categories())
