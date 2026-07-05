#!/usr/bin/env python3
"""Local-only smoke fixture seed/cleanup harness for issue #155.

This helper intentionally mutates only the shared local Neo4j instance. It does
not read .env files, start Docker, run migrations, invoke backfill --apply, or
claim any production safety conclusion.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOCAL_NEO4J_URI = "bolt://127.0.0.1:17687"
SMOKE_MARKER = "issue155_smoke"
RUN_ID_FIELD = "issue155_smoke_run_id"
EVIDENCE_DIR = Path(__file__).resolve().parent

SEED_QUERY = """
UNWIND $fixtures AS fixture
CREATE (e:Event)
SET e = fixture
RETURN count(e) AS seeded_count
""".strip()

CLEANUP_QUERY = """
MATCH (e:Event {issue155_smoke:true, issue155_smoke_run_id:$run_id})
WITH collect(e) AS events, count(e) AS deleted_count
FOREACH (event IN events | DETACH DELETE event)
RETURN deleted_count
""".strip()

POST_CLEANUP_QUERY = """
MATCH (e:Event {issue155_smoke:true, issue155_smoke_run_id:$run_id})
RETURN count(e)=0 AS cleanup_verified, count(e) AS remaining_count
""".strip()


class UnsafeTargetError(RuntimeError):
    """Raised when the requested Neo4j target is not the shared local instance."""


class OutputTargetError(RuntimeError):
    """Raised when an evidence output path is outside the allowed directory."""


class CliError(RuntimeError):
    """Raised for expected local runtime failures that should not print tracebacks."""


def generate_run_id(now: datetime | None = None) -> str:
    """Generate a unique, marker-friendly run id."""
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"issue155-smoke-{timestamp}-{uuid.uuid4().hex[:8]}"


def validate_local_neo4j_uri(uri: str) -> str:
    """Allow only the approved shared local Neo4j endpoint."""
    parsed = urlparse(uri)
    if parsed.scheme not in {"bolt", "neo4j"}:
        raise UnsafeTargetError("Smoke fixtures may target only shared local Neo4j.")
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 17687:
        raise UnsafeTargetError(
            "Smoke fixtures may target only shared local Neo4j at 127.0.0.1:17687."
        )
    return uri


def build_fixture_plan(run_id: str) -> list[dict[str, Any]]:
    """Build marker-scoped Event fixtures covering safe, ambiguous, and no-touch buckets."""
    created_at = datetime.now(timezone.utc).isoformat()
    base = {
        SMOKE_MARKER: True,
        RUN_ID_FIELD: run_id,
        "status": "ACTIVE",
        "severity": "warning",
        "created_at": created_at,
        "last_seen": created_at,
    }
    return [
        {
            **base,
            "id": f"{run_id}-safe",
            "ci_id": f"{run_id}-ci-safe",
            "metric_id": "availability.safe",
            "metric_name": "Availability Safe Fixture",
            "message": "SNMP availability event with complete discriminator fields.",
            "event_type": "AVAILABILITY",
            "failure_family": "COLLECTION",
            "source_protocol": "SNMP",
            "availability_source": "snmp",
            "expected_bucket": "safe_candidates",
        },
        {
            **base,
            "id": f"{run_id}-ambiguous",
            "ci_id": f"{run_id}-ci-ambiguous",
            "metric_id": "availability.ping.timeout",
            "metric_name": "PING Timeout Fixture",
            "message": "PING availability timeout; host down boundary needs reviewer decision.",
            "event_type": None,
            "failure_family": None,
            "source_protocol": None,
            "availability_source": None,
            "expected_bucket": "ambiguous_records",
        },
        {
            **base,
            "id": f"{run_id}-no-touch",
            "ci_id": f"{run_id}-ci-no-touch",
            "metric_id": "threshold.partial",
            "metric_name": "Threshold Partial Fixture",
            "message": "Threshold signal with one missing discriminator and no ambiguity hint.",
            "event_type": "THRESHOLD",
            "failure_family": None,
            "source_protocol": "SNMP",
            "availability_source": "snmp",
            "expected_bucket": "no_touch_records",
        },
    ]


def _single_value(summary: Any, key: str) -> Any:
    record = summary.single(strict=True)
    return record[key]


def _write_transaction(session: Any, callback: Any) -> Any:
    """Use Neo4j managed write transactions when the installed driver supports them."""
    if hasattr(session, "execute_write"):
        return session.execute_write(callback)
    if hasattr(session, "write_transaction"):
        return session.write_transaction(callback)
    return callback(session)


def seed_fixtures(driver: Any, fixtures: list[dict[str, Any]]) -> int:
    """Create marker-scoped Event nodes in the shared local database only."""

    def seed(tx: Any) -> int:
        return int(_single_value(tx.run(SEED_QUERY, fixtures=fixtures), "seeded_count"))

    with driver.session() as session:
        return _write_transaction(session, seed)


def cleanup_fixtures(driver: Any, run_id: str) -> dict[str, Any]:
    """Delete only marker/run-id scoped fixtures and verify zero remain."""

    def cleanup(tx: Any) -> tuple[int, Any]:
        deleted = int(_single_value(tx.run(CLEANUP_QUERY, run_id=run_id), "deleted_count"))
        verification_record = tx.run(POST_CLEANUP_QUERY, run_id=run_id).single(strict=True)
        return deleted, verification_record

    with driver.session() as session:
        deleted_count, verification = _write_transaction(session, cleanup)
    return {
        "deleted_count": deleted_count,
        "cleanup_verified": bool(verification["cleanup_verified"]),
        "remaining_count": int(verification["remaining_count"]),
        "query": POST_CLEANUP_QUERY,
    }


def _load_driver(uri: str, user: str, password: str) -> Any:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover - depends on local environment.
        raise CliError("neo4j package is required to run the live smoke fixture harness") from exc
    return GraphDatabase.driver(uri, auth=(user, password))


def resolve_evidence_output_path(output: str | Path, evidence_dir: Path = EVIDENCE_DIR) -> Path:
    """Resolve an output path that must remain under this change's evidence directory."""
    evidence_root = evidence_dir.resolve()
    requested = Path(output)
    candidate = requested if requested.is_absolute() else evidence_root / requested
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(evidence_root):
        raise OutputTargetError("--output must resolve under this change's evidence directory")
    return resolved


def write_json_exclusive(
    path: Path, payload: dict[str, Any], evidence_dir: Path = EVIDENCE_DIR
) -> None:
    """Write JSON evidence without overwriting existing files."""
    resolved = resolve_evidence_output_path(path, evidence_dir=evidence_dir)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        with resolved.open("x", encoding="utf-8") as output_file:
            output_file.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise OutputTargetError(f"evidence output already exists: {resolved}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed and clean issue #155 local smoke fixtures.")
    parser.add_argument("--run-id", default=None, help="Optional unique run id for repeatable cleanup.")
    parser.add_argument("--output", default=None, help="Optional JSON manifest path for seed/cleanup evidence.")
    parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", LOCAL_NEO4J_URI))
    parser.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", ""))
    return parser


def run_seed_cleanup(driver: Any, run_id: str) -> dict[str, Any]:
    """Run the PR1 seed/cleanup flow with failure-safe cleanup."""
    fixtures = build_fixture_plan(run_id)
    seeded_count = 0
    cleanup: dict[str, Any] | None = None
    try:
        seeded_count = seed_fixtures(driver, fixtures)
    finally:
        cleanup = cleanup_fixtures(driver, run_id)

    if not cleanup["cleanup_verified"]:
        raise RuntimeError(f"cleanup verification failed for run id {run_id}: {cleanup}")
    return {
        "run_id": run_id,
        "seeded_count": seeded_count,
        "fixture_plan": fixtures,
        "cleanup": cleanup,
        "status": "cleanup_verified",
        "scope": "local shared Neo4j only; no production mutation",
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_id = args.run_id or generate_run_id()
    uri = validate_local_neo4j_uri(args.neo4j_uri)
    output_path = resolve_evidence_output_path(args.output) if args.output else None
    if output_path and output_path.exists():
        raise OutputTargetError(f"evidence output already exists: {output_path}")
    if not args.neo4j_password:
        raise CliError("NEO4J_PASSWORD must be exported; this helper does not read .env files.")

    try:
        driver = _load_driver(uri, args.neo4j_user, args.neo4j_password)
    except Exception as exc:
        if isinstance(exc, CliError):
            raise
        raise CliError(f"could not create Neo4j driver for local smoke fixtures: {exc}") from exc

    try:
        try:
            payload = run_seed_cleanup(driver, run_id)
        except Exception as exc:
            raise CliError(f"local smoke fixture run failed: {exc}") from exc
    finally:
        driver.close()

    if output_path:
        write_json_exclusive(output_path, payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (UnsafeTargetError, OutputTargetError, CliError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
