#!/usr/bin/env python3
"""Local-only smoke fixture seed/cleanup harness for issue #155.

This helper intentionally mutates only the shared local Neo4j instance. It does
not read .env files, start Docker, run migrations, invoke backfill --apply, or
claim any production safety conclusion.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOCAL_NEO4J_URI = "bolt://127.0.0.1:17687"
SMOKE_MARKER = "issue155_smoke"
RUN_ID_FIELD = "issue155_smoke_run_id"
EVIDENCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVIDENCE_DIR.parents[3]
PYTHON_EXECUTABLE = sys.executable or "python3"
SMOKE_AUDIT_SCHEMA = "issue155_smoke_scoped_audit_v1"

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


def _load_audit_service(repo_root: Path = REPO_ROOT) -> Any:
    backend_path = repo_root / "backend"
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    from services import legacy_event_discriminator_audit

    return legacy_event_discriminator_audit


def classify_fixture_buckets(
    fixtures: list[dict[str, Any]], repo_root: Path = REPO_ROOT
) -> dict[str, str]:
    """Classify smoke-only fixtures by directly reusing the read-only audit service."""
    audit_service = _load_audit_service(repo_root)
    audit = audit_service.classify_legacy_event_records(fixtures)
    ambiguous_event_ids = {
        finding.record.event_id
        for finding in audit.findings
        if finding.severity.lower() == "ambiguous"
    }
    finding_event_ids = {finding.record.event_id for finding in audit.findings}
    no_touch_event_ids = finding_event_ids - ambiguous_event_ids

    bucket_by_event_id: dict[str, str] = {}
    for fixture in fixtures:
        event_id = str(fixture["id"])
        if event_id in ambiguous_event_ids:
            bucket_by_event_id[event_id] = "ambiguous_records"
        elif event_id in no_touch_event_ids:
            bucket_by_event_id[event_id] = "no_touch_records"
        else:
            bucket_by_event_id[event_id] = "safe_candidates"
    return bucket_by_event_id


def _evidence_relative_path(path: Path, evidence_dir: Path | None = None) -> str:
    """Render evidence paths without leaking absolute local worktree paths."""
    evidence_root = evidence_dir or EVIDENCE_DIR
    return path.resolve(strict=False).relative_to(evidence_root.resolve()).as_posix()


def _smoke_finding_event_id(finding: dict[str, Any]) -> str | None:
    record = finding.get("record") if isinstance(finding.get("record"), dict) else {}
    event_id = record.get("event_id")
    return str(event_id) if event_id else None


def build_smoke_scoped_audit_evidence(
    raw_audit: dict[str, Any], smoke_event_ids: set[str]
) -> dict[str, Any]:
    """Return sanitized audit evidence containing only smoke fixture findings."""
    smoke_ids = {str(event_id) for event_id in smoke_event_ids}
    smoke_findings: list[dict[str, Any]] = []

    for finding in raw_audit.get("findings", []):
        if not isinstance(finding, dict):
            continue
        event_id = _smoke_finding_event_id(finding)
        if event_id not in smoke_ids:
            continue
        smoke_findings.append(
            {
                "event_id": event_id,
                "finding_id": str(finding.get("id", "")),
                "code": finding.get("code"),
                "field": finding.get("field"),
                "severity": finding.get("severity"),
                "recommended_value": finding.get("recommended_value"),
            }
        )

    smoke_findings.sort(key=lambda item: (str(item["event_id"]), str(item["code"])))
    smoke_event_ids_with_findings = sorted(
        {str(finding["event_id"]) for finding in smoke_findings}
    )
    return {
        "schema": SMOKE_AUDIT_SCHEMA,
        "scope": "smoke fixture findings only; non-smoke finding details omitted",
        "findings": smoke_findings,
        "summary": {
            "smoke_event_ids": sorted(smoke_ids),
            "smoke_event_ids_with_findings": smoke_event_ids_with_findings,
            "smoke_findings_count": len(smoke_findings),
        },
    }


def read_json_evidence(path: str | Path, evidence_dir: Path | None = None) -> dict[str, Any]:
    """Read JSON evidence from an evidence-scoped path."""
    evidence_root = evidence_dir or EVIDENCE_DIR
    resolved = resolve_evidence_output_path(path, evidence_dir=evidence_root)
    with resolved.open(encoding="utf-8") as evidence_file:
        payload = json.load(evidence_file)
    if not isinstance(payload, dict):
        raise CliError(f"JSON evidence must be an object: {_evidence_relative_path(resolved, evidence_root)}")
    return payload


def build_validation_summary(
    fixtures: list[dict[str, Any]],
    actual_buckets: dict[str, str],
    audit_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Compare expected fixture buckets with classifier and persisted audit evidence."""
    expected_by_event_id = {
        str(fixture["id"]): str(fixture["expected_bucket"]) for fixture in fixtures
    }
    expected_finding_event_ids = sorted(
        event_id
        for event_id, expected_bucket in expected_by_event_id.items()
        if expected_bucket in {"ambiguous_records", "no_touch_records"}
    )
    audit_event_ids_with_findings = sorted(
        {
            str(finding.get("event_id"))
            for finding in audit_evidence.get("findings", [])
            if isinstance(finding, dict) and finding.get("event_id")
        }
    )
    missing_expected_finding_event_ids = sorted(
        set(expected_finding_event_ids) - set(audit_event_ids_with_findings)
    )
    safe_event_ids = sorted(
        event_id
        for event_id, expected_bucket in expected_by_event_id.items()
        if expected_bucket == "safe_candidates"
    )
    mismatches = [
        {
            "event_id": event_id,
            "expected_bucket": expected_bucket,
            "actual_bucket": actual_buckets.get(event_id, "missing"),
        }
        for event_id, expected_bucket in expected_by_event_id.items()
        if actual_buckets.get(event_id) != expected_bucket
    ]
    audit_evidence_status = (
        "inspected" if not missing_expected_finding_event_ids else "missing_expected_findings"
    )
    return {
        "valid_for_planning": not mismatches and not missing_expected_finding_event_ids,
        "classification_source": "direct classifier reuse for smoke-only fixture rows",
        "expected_buckets": expected_by_event_id,
        "actual_buckets": dict(sorted(actual_buckets.items())),
        "expected_counts": dict(sorted(Counter(expected_by_event_id.values()).items())),
        "actual_counts": dict(sorted(Counter(actual_buckets.values()).items())),
        "mismatches": mismatches,
        "audit_evidence": {
            "status": audit_evidence_status,
            "schema": audit_evidence.get("schema"),
            "expected_finding_event_ids": expected_finding_event_ids,
            "event_ids_with_findings": audit_event_ids_with_findings,
            "missing_expected_finding_event_ids": missing_expected_finding_event_ids,
        },
        "safe_fixture_validation": {
            "event_ids": safe_event_ids,
            "source": "direct classifier reuse; safe fixtures have no audit finding by design",
        },
        "recommendation_gap": {
            "status": "gap_recorded",
            "description": (
                "The existing aggregate recommendation JSON does not expose per-record "
                "smoke fixture IDs; smoke-only expected-vs-actual validation therefore parses "
                "sanitized audit JSON for ambiguous/no-touch findings and reuses the read-only "
                "classifier directly for safe fixtures, which have no finding by design."
            ),
        },
        "scope": "local shared Neo4j only; no production mutation or production-scale conclusion",
    }


def run_audit_json_report(
    output: str | Path,
    *,
    smoke_event_ids: set[str],
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    repo_root: Path = REPO_ROOT,
    evidence_dir: Path = EVIDENCE_DIR,
) -> dict[str, Any]:
    """Run the read-only audit CLI, then persist only smoke-scoped sanitized evidence."""
    validated_neo4j_uri = validate_local_neo4j_uri(neo4j_uri)
    output_path = resolve_evidence_output_path(output, evidence_dir=evidence_dir)
    if output_path.exists():
        raise OutputTargetError(f"evidence output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sanitized_command = [
        "python3",
        "backend/scripts/audit_legacy_event_discriminators.py",
        "--report",
        "audit",
        "--format",
        "json",
        "--output",
        "<temporary-broad-audit-json>",
    ]
    with tempfile.TemporaryDirectory(prefix="issue155-smoke-audit-") as temp_dir:
        temporary_audit_path = Path(temp_dir) / "broad-audit.json"
        command = [
            PYTHON_EXECUTABLE,
            "backend/scripts/audit_legacy_event_discriminators.py",
            "--report",
            "audit",
            "--format",
            "json",
            "--output",
            str(temporary_audit_path),
        ]
        audit_env = os.environ.copy()
        audit_env.update(
            {
                "NEO4J_URI": validated_neo4j_uri,
                "NEO4J_USER": neo4j_user,
                "NEO4J_PASSWORD": neo4j_password,
            }
        )
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=audit_env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise CliError(
                "read-only audit JSON report failed: "
                f"exit={completed.returncode} stderr={completed.stderr.strip()}"
            )
        with temporary_audit_path.open(encoding="utf-8") as raw_audit_file:
            raw_audit = json.load(raw_audit_file)
        if not isinstance(raw_audit, dict):
            raise CliError("read-only audit JSON report did not produce a JSON object")
        sanitized_audit = build_smoke_scoped_audit_evidence(raw_audit, smoke_event_ids)
        write_json_exclusive(output_path, sanitized_audit, evidence_dir=evidence_dir)

    return {
        "report": "audit",
        "format": "json",
        "output": _evidence_relative_path(output_path, evidence_dir=evidence_dir),
        "output_path_kind": "evidence-relative",
        "command": sanitized_command,
        "persisted_scope": "smoke fixture findings only",
        "persisted_schema": SMOKE_AUDIT_SCHEMA,
        "smoke_findings_count": sanitized_audit["summary"]["smoke_findings_count"],
        "stdout_captured": bool(completed.stdout),
        "stderr_captured": bool(completed.stderr),
    }


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
    parser.add_argument(
        "--audit-json-output",
        default=None,
        help="Optional sanitized smoke-scoped audit JSON path for PR2 validation evidence.",
    )
    parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", LOCAL_NEO4J_URI))
    parser.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", ""))
    return parser


def run_seed_cleanup(
    driver: Any,
    run_id: str,
    *,
    audit_json_output: str | Path | None = None,
    neo4j_uri: str = LOCAL_NEO4J_URI,
    neo4j_user: str = "neo4j",
    neo4j_password: str = "",
    repo_root: Path = REPO_ROOT,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the seed/cleanup flow with optional PR2 read-only validation evidence."""
    evidence_root = evidence_dir or EVIDENCE_DIR
    fixtures = build_fixture_plan(run_id)
    seeded_count = 0
    cleanup: dict[str, Any] | None = None
    audit_json_report: dict[str, Any] | None = None
    validation_summary: dict[str, Any] | None = None
    primary_error: BaseException | None = None
    try:
        seeded_count = seed_fixtures(driver, fixtures)
        if audit_json_output:
            smoke_event_ids = {str(fixture["id"]) for fixture in fixtures}
            audit_json_report = run_audit_json_report(
                audit_json_output,
                smoke_event_ids=smoke_event_ids,
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_password=neo4j_password,
                repo_root=repo_root,
                evidence_dir=evidence_root,
            )
            audit_evidence = read_json_evidence(audit_json_output, evidence_dir=evidence_root)
            validation_summary = build_validation_summary(
                fixtures,
                classify_fixture_buckets(fixtures, repo_root=repo_root),
                audit_evidence,
            )
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            cleanup = cleanup_fixtures(driver, run_id)
        except BaseException as cleanup_exc:
            if primary_error is not None:
                raise RuntimeError(
                    f"cleanup failed after prior error {primary_error!r}: {cleanup_exc}"
                ) from cleanup_exc
            raise

    if not cleanup["cleanup_verified"]:
        message = f"cleanup verification failed for run id {run_id}: {cleanup}"
        if primary_error is not None:
            raise RuntimeError(
                f"{message}; prior error was {primary_error!r}"
            ) from primary_error
        raise RuntimeError(message)
    if primary_error is not None:
        raise primary_error
    return {
        "run_id": run_id,
        "seeded_count": seeded_count,
        "fixture_plan": fixtures,
        "audit_json_report": audit_json_report,
        "validation_summary": validation_summary,
        "cleanup": cleanup,
        "status": (
            "validation_complete_cleanup_verified"
            if validation_summary and validation_summary["valid_for_planning"]
            else "cleanup_verified"
        ),
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
            payload = run_seed_cleanup(
                driver,
                run_id,
                audit_json_output=args.audit_json_output,
                neo4j_uri=uri,
                neo4j_user=args.neo4j_user,
                neo4j_password=args.neo4j_password,
            )
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
