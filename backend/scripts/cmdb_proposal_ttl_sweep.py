#!/usr/bin/env python3
"""CMDB proposal TTL sweep script — feat-cmdb-ai-handoff (T-1.6 / REQ-CMAP-016).

Auto-revokes stale DRAFT proposals older than ``CMDB_PROPOSAL_RETENTION_DAYS``
days (default 30). Emits one ``CI_PROPOSAL_REVOKE`` audit row per swept
proposal with ``actor_role='SYSTEM'`` and ``revoke_reason='ttl_expired'``.

Idempotent — already-revoked rows produce 0 audit rows.

Usage:
    python -m scripts.cmdb_proposal_ttl_sweep [--retention-days N]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)


# Module-level seam so tests can monkeypatch without reaching into main().
SessionLocal: Any = None


def _get_repo():
    """Default repo factory; tests monkeypatch this."""
    from repositories.cmdb_proposal_repo import get_cmdb_proposal_repo

    return get_cmdb_proposal_repo()


def _resolve_retention_days(argv: list[str]) -> int:
    """Honor --retention-days CLI flag, then CMDB_PROPOSAL_RETENTION_DAYS env, default 30."""
    parser = argparse.ArgumentParser(description="CMDB proposal TTL sweep")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="Days a DRAFT can stay open before auto-revoke (default: env or 30)",
    )
    args = parser.parse_args(argv)
    if args.retention_days is not None:
        return args.retention_days
    env_value = os.getenv("CMDB_PROPOSAL_RETENTION_DAYS")
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            logger.warning("Invalid CMDB_PROPOSAL_RETENTION_DAYS=%r, using default 30", env_value)
    return 30


def _emit_audit(
    *, db: Any, proposal_id: str, proposed_by: str | None, manifest_json: str | None
) -> None:
    """Emit one CI_PROPOSAL_REVOKE row with actor_role=SYSTEM, revoke_reason=ttl_expired."""
    from services.audit_service import record_critical_change

    record_critical_change(
        db=db,
        request=None,
        actor=None,
        event_type="CI_PROPOSAL_REVOKE",
        outcome="SUCCESS",
        target_type="ci_proposal",
        target_id=proposal_id,
        target_label=proposal_id,
        reason="proposal_ttl_revoked",
        source="cmdb_proposals",
        context={
            "proposal_id": proposal_id,
            "proposed_by": proposed_by,
            "actor_role": "SYSTEM",
            "previous_state": "DRAFT",
            "next_state": "REVOKED",
            "version": 0,  # actual version lives on the row post-sweep
            "revoke_reason": "ttl_expired",
            "applied_manifest_summary": _safe_manifest_summary(manifest_json),
            "manifest_diff": None,
        },
    )


def _safe_manifest_summary(manifest_json: str | None) -> dict | None:
    if not manifest_json:
        return None
    try:
        manifest = json.loads(manifest_json)
    except (TypeError, ValueError):
        return None
    from services.audit_service import redact_manifest_secrets

    return redact_manifest_secrets(manifest)


def _list_swept_records(repo: Any, retention_days: int) -> list[dict]:
    """Run the sweep and return the list of revoked proposal rows.

    Calls ``ttl_sweep`` first to perform the transition, then re-queries the
    newly-revoked nodes by status='REVOKED' + reviewed_by='SYSTEM' so we can
    emit one audit row per swept proposal.
    """
    sweep_count = repo.ttl_sweep(retention_days=retention_days)
    if not sweep_count:
        return []
    return repo.list(
        status="REVOKED",
        page=1,
        page_size=max(sweep_count * 2, 50),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the sweep. Returns 0 on success."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if argv is None:
        argv = sys.argv[1:]

    retention_days = _resolve_retention_days(argv)
    logger.info("CMDB proposal TTL sweep starting (retention_days=%s)", retention_days)

    repo = _get_repo()

    # Collect the swept records by re-listing. We need to know which rows were
    # transitioned this run; the simplest implementation is to run ttl_sweep
    # inside a transaction or re-query by reviewed_by='SYSTEM' + reviewed_at >= now.
    # For simplicity here, ttl_sweep returns the count and we re-list the most
    # recently-revoked SYSTEM-attributed rows.
    swept_count = repo.ttl_sweep(retention_days)
    if swept_count == 0:
        logger.info("No stale DRAFT proposals to revoke.")
        return 0

    # Re-list the recently-swept rows so we can emit one audit row per.
    recent_records = repo.list(status="REVOKED", page=1, page_size=max(swept_count, 50))
    # Filter to rows reviewed_by=SYSTEM with revoke_reason=ttl_expired (just swept).
    swept_rows = [
        r
        for r in recent_records
        if r.get("reviewed_by") == "SYSTEM" and r.get("revoke_reason") == "ttl_expired"
    ]

    # Lazily resolve SessionLocal on first run so test-time monkeypatching
    # applies uniformly across the script.
    if SessionLocal is None:
        from postgres_db import SessionLocal as _DefaultSessionLocal

        session_local = _DefaultSessionLocal
    else:
        session_local = SessionLocal

    db = session_local()
    try:
        for row in swept_rows[:swept_count]:
            _emit_audit(
                db=db,
                proposal_id=row["id"],
                proposed_by=row.get("proposed_by"),
                manifest_json=row.get("manifest_json"),
            )
        logger.info("Revoked %s stale DRAFT proposals.", swept_count)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
