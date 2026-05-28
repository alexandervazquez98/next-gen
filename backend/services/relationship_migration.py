"""Audit and migrate legacy CI relationship types."""
from __future__ import annotations

from typing import Any

from .relationship_types import LEGACY_RELATIONSHIP_TYPE_MAP, validate_ci_relationship_type, validate_legacy_relationship_type


def audit_relationship_type_counts(session) -> dict[str, int]:
    rows = session.run("""
        MATCH ()-[r]->()
        RETURN type(r) AS type, count(r) AS count
        ORDER BY type
    """)
    return {row["type"]: row["count"] for row in rows}


def _estimate_after_counts(before: dict[str, int], mappings: list[dict[str, Any]]) -> dict[str, int]:
    after = dict(before)
    for entry in mappings:
        legacy_count = int(entry["legacy_count"])
        target_count = int(after.get(entry["to"], 0))
        after[entry["from"]] = max(0, int(after.get(entry["from"], 0)) - legacy_count)
        after[entry["to"]] = target_count + int(entry["planned_creates"])
    return after


def migrate_relationship_types(session, mapping: dict[str, str] | None = None, *, apply: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {"mode": "apply" if apply else "dry-run", "before": audit_relationship_type_counts(session), "mappings": []}
    for legacy_raw, target_raw in (mapping or LEGACY_RELATIONSHIP_TYPE_MAP).items():
        legacy = validate_legacy_relationship_type(legacy_raw)
        target = validate_ci_relationship_type(target_raw)
        if legacy == target:
            raise ValueError("Legacy and target relationship types must differ")

        plan = session.run(f"""
            MATCH (a)-[old_rel:{legacy}]->(b)
            OPTIONAL MATCH (a)-[replacement:{target}]->(b)
            RETURN count(old_rel) AS legacy_count,
                   count(replacement) AS duplicate_count,
                   count(old_rel) - count(replacement) AS create_count
        """).single() or {}
        entry = {
            "from": legacy,
            "to": target,
            "legacy_count": plan.get("legacy_count", 0),
            "planned_creates": plan.get("create_count", 0),
            "skipped_duplicates": plan.get("duplicate_count", 0),
            "deleted_legacy": 0,
        }
        if apply and entry["legacy_count"]:
            applied = session.run(f"""
                MATCH (a)-[old_rel:{legacy}]->(b)
                OPTIONAL MATCH (a)-[existing:{target}]->(b)
                WITH a, b, old_rel, existing, properties(old_rel) AS props
                FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                    CREATE (a)-[new_rel:{target}]->(b)
                    SET new_rel = props
                )
                WITH a, b, old_rel
                MATCH (a)-[replacement:{target}]->(b)
                DELETE old_rel
                RETURN count(old_rel) AS deleted_count
            """).single() or {}
            entry["deleted_legacy"] = applied.get("deleted_count", 0)
        report["mappings"].append(entry)
    if apply:
        report["after"] = audit_relationship_type_counts(session)
    else:
        report["after"] = dict(report["before"])
        report["after_if_applied"] = _estimate_after_counts(report["before"], report["mappings"])
    return report
