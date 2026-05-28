"""Dry-run/apply migration for legacy CI relationship types."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

CONFIRMATION_PHRASE = "MIGRATE RELATIONSHIP TYPES"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
get_db = importlib.import_module("database").get_db
migration_module = importlib.import_module("services.relationship_migration")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy Neo4j relationship types")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan changes without mutation (default)")
    mode.add_argument("--apply", action="store_true", help="Apply the migration")
    parser.add_argument(
        "--yes",
        action="store_true",
        help=f"Required with --apply to skip interactive confirmation. Dry-run first and type '{CONFIRMATION_PHRASE}' if not using --yes.",
    )
    args = parser.parse_args()
    if args.apply and not args.yes:
        print("WARNING: --apply will mutate Neo4j relationships.", file=sys.stderr)
        print("Run --dry-run first and keep a DB backup/snapshot before applying.", file=sys.stderr)
        confirmation = input(f"Type '{CONFIRMATION_PHRASE}' to continue: ")
        if confirmation != CONFIRMATION_PHRASE:
            print("Migration cancelled.", file=sys.stderr)
            return 2
    with get_db().session() as session:
        report = migration_module.migrate_relationship_types(
            session,
            migration_module.LEGACY_RELATIONSHIP_TYPE_MAP,
            apply=args.apply,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
