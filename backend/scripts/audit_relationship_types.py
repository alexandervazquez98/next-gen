"""Print Neo4j relationship type counts without mutating data."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
get_db = importlib.import_module("database").get_db
audit_relationship_type_counts = importlib.import_module("services.relationship_migration").audit_relationship_type_counts


def main() -> int:
    with get_db().session() as session:
        print(json.dumps(audit_relationship_type_counts(session), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
