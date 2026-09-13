"""Repository for the :CIProposal label — feat-cmdb-ai-handoff.

Mirrors the optimistic-version precedent at
``backend/repositories/mqtt_mapping_repo.py`` (``create_draft``/``approve``) but
parameterizes every Cypher statement via ``$params`` so user-supplied data can
never be interpolated into the query string.

State machine:
    DRAFT (version=1) -> APPROVED (version=2) | REVOKED (version>=2)

Approve / revoke use ``MATCH (p:CIProposal {id: $id, version: $v}) …`` so
the first writer wins and concurrent writers get ``CmdbProposalVersionConflictError``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database import get_db

# Lifecycle constants kept as plain strings for DB neutrality.
CI_PROPOSAL_STATUS_DRAFT = "DRAFT"
CI_PROPOSAL_STATUS_APPROVED = "APPROVED"
CI_PROPOSAL_STATUS_REVOKED = "REVOKED"


class CmdbProposalNotFoundError(RuntimeError):
    """Raised when a proposal id is unknown."""


class CmdbProposalVersionConflictError(RuntimeError):
    """Raised when optimistic-version check fails."""


# Fields returned to callers — mirrors ``MqttMappingRepo._record`` shape.
_RETURN_FIELDS: tuple[str, ...] = (
    "id",
    "manifest_json",
    "applied_manifest_json",
    "status",
    "version",
    "proposed_by",
    "proposed_role",
    "reviewed_by",
    "reviewed_at",
    "created_at",
    "updated_at",
    "resulted_ci_id",
    "revoke_reason",
    "proposed_category",
    "ci_id",
)


class CmdbProposalRepo:
    """Persist and query ``:CIProposal`` nodes."""

    def __init__(self, driver: Any | None = None):
        self._driver = driver if driver is not None else get_db()

    # ── helpers ────────────────────────────────────────────────────────────

    def _session(self):
        return self._driver.session() if hasattr(self._driver, "session") else self._driver

    def _run(self, query: str, **params: Any) -> Any:
        """Centralized runner — every query goes through here for traceability."""
        session = self._session()
        if hasattr(session, "run"):
            return session.run(query, **params)
        # Direct callable (test mock) — fall through.
        return session(query, **params) if callable(session) else session.run(query, **params)

    @staticmethod
    def _record(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        if isinstance(row, dict):
            return {key: row.get(key) for key in _RETURN_FIELDS if key in row}
        try:
            return {key: row[key] for key in _RETURN_FIELDS if row[key] is not None or key in row}
        except Exception:
            try:
                return {key: row.get(key) for key in _RETURN_FIELDS}
            except Exception:
                return None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    # ── create_draft ───────────────────────────────────────────────────────

    def create_draft(
        self,
        proposal_id: str,
        manifest_json: str,
        proposed_by: str,
        proposed_role: str,
        proposed_category: str | None = None,
        ci_id: str | None = None,
        applied_manifest_json: str | None = None,
    ) -> dict[str, Any]:
        now = self._now_iso()
        query = """
        CREATE (p:CIProposal)
        SET
            p.id = $proposal_id,
            p.manifest_json = $manifest_json,
            p.applied_manifest_json = $applied_manifest_json,
            p.status = $draft_status,
            p.version = 1,
            p.proposed_by = $proposed_by,
            p.proposed_role = $proposed_role,
            p.reviewed_by = NULL,
            p.reviewed_at = NULL,
            p.created_at = datetime($created_at),
            p.updated_at = datetime($updated_at),
            p.resulted_ci_id = NULL,
            p.revoke_reason = NULL,
            p.proposed_category = $proposed_category,
            p.ci_id = $ci_id
        RETURN
            p.id AS id,
            p.manifest_json AS manifest_json,
            p.applied_manifest_json AS applied_manifest_json,
            p.status AS status,
            p.version AS version,
            p.proposed_by AS proposed_by,
            p.proposed_role AS proposed_role,
            p.reviewed_by AS reviewed_by,
            p.reviewed_at AS reviewed_at,
            p.created_at AS created_at,
            p.updated_at AS updated_at,
            p.resulted_ci_id AS resulted_ci_id,
            p.revoke_reason AS revoke_reason,
            p.proposed_category AS proposed_category,
            p.ci_id AS ci_id
        """
        params = {
            "proposal_id": proposal_id,
            "manifest_json": manifest_json,
            "applied_manifest_json": applied_manifest_json,
            "draft_status": CI_PROPOSAL_STATUS_DRAFT,
            "proposed_by": proposed_by,
            "proposed_role": proposed_role,
            "created_at": now,
            "updated_at": now,
            "proposed_category": proposed_category,
            "ci_id": ci_id,
        }
        result = self._run(query, **params)
        row = result.single() if hasattr(result, "single") else result
        record = self._record(row)
        if record is None:
            raise RuntimeError("Failed to create CIProposal draft")
        return record

    # ── get / list ─────────────────────────────────────────────────────────

    def get(self, proposal_id: str) -> dict[str, Any] | None:
        query = """
        MATCH (p:CIProposal) WHERE p.id = $proposal_id
        RETURN
            p.id AS id,
            p.manifest_json AS manifest_json,
            p.applied_manifest_json AS applied_manifest_json,
            p.status AS status,
            p.version AS version,
            p.proposed_by AS proposed_by,
            p.proposed_role AS proposed_role,
            p.reviewed_by AS reviewed_by,
            p.reviewed_at AS reviewed_at,
            p.created_at AS created_at,
            p.updated_at AS updated_at,
            p.resulted_ci_id AS resulted_ci_id,
            p.revoke_reason AS revoke_reason,
            p.proposed_category AS proposed_category,
            p.ci_id AS ci_id
        """
        result = self._run(query, proposal_id=proposal_id)
        row = result.single() if hasattr(result, "single") else result
        return self._record(row)

    def list(
        self,
        status: str | None = None,
        category: str | None = None,
        proposed_by: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "status": status,
            "category": category,
            "proposed_by": proposed_by,
            "created_from": created_from,
            "created_to": created_to,
            "skip": max(0, (page - 1) * page_size),
            "limit": max(1, page_size),
        }
        query = """
        MATCH (p:CIProposal)
        WHERE
            ($status IS NULL OR p.status = $status)
            AND ($category IS NULL OR p.proposed_category = $category)
            AND ($proposed_by IS NULL OR p.proposed_by = $proposed_by)
            AND ($created_from IS NULL OR p.created_at >= datetime($created_from))
            AND ($created_to IS NULL OR p.created_at <= datetime($created_to))
        RETURN
            p.id AS id,
            p.manifest_json AS manifest_json,
            p.applied_manifest_json AS applied_manifest_json,
            p.status AS status,
            p.version AS version,
            p.proposed_by AS proposed_by,
            p.proposed_role AS proposed_role,
            p.reviewed_by AS reviewed_by,
            p.reviewed_at AS reviewed_at,
            p.created_at AS created_at,
            p.updated_at AS updated_at,
            p.resulted_ci_id AS resulted_ci_id,
            p.revoke_reason AS revoke_reason,
            p.proposed_category AS proposed_category,
            p.ci_id AS ci_id
        ORDER BY p.created_at DESC, p.id
        SKIP $skip LIMIT $limit
        """
        result = self._run(query, **params)
        if hasattr(result, "data"):
            rows = result.data()
        elif hasattr(result, "__iter__"):
            rows = list(result)
        else:
            rows = []
        return [r for r in (self._record(row) for row in rows) if r is not None]

    # ── approve / revoke ───────────────────────────────────────────────────

    def approve(
        self,
        proposal_id: str,
        expected_version: int,
        reviewer_by: str,
        applied_manifest_json: str,
        resulted_ci_id: str,
    ) -> dict[str, Any]:
        now = self._now_iso()
        query = """
        MATCH (p:CIProposal {id: $proposal_id, version: $expected_version})
        WHERE p.status = $draft_status
        SET
            p.status = $approved_status,
            p.version = $expected_version + 1,
            p.reviewed_by = $reviewer_by,
            p.reviewed_at = datetime($reviewed_at),
            p.updated_at = datetime($updated_at),
            p.applied_manifest_json = $applied_manifest_json,
            p.resulted_ci_id = $resulted_ci_id
        RETURN
            p.id AS id,
            p.manifest_json AS manifest_json,
            p.applied_manifest_json AS applied_manifest_json,
            p.status AS status,
            p.version AS version,
            p.proposed_by AS proposed_by,
            p.proposed_role AS proposed_role,
            p.reviewed_by AS reviewed_by,
            p.reviewed_at AS reviewed_at,
            p.created_at AS created_at,
            p.updated_at AS updated_at,
            p.resulted_ci_id AS resulted_ci_id,
            p.revoke_reason AS revoke_reason,
            p.proposed_category AS proposed_category,
            p.ci_id AS ci_id
        """
        params = {
            "proposal_id": proposal_id,
            "expected_version": expected_version,
            "draft_status": CI_PROPOSAL_STATUS_DRAFT,
            "approved_status": CI_PROPOSAL_STATUS_APPROVED,
            "reviewer_by": reviewer_by,
            "reviewed_at": now,
            "updated_at": now,
            "applied_manifest_json": applied_manifest_json,
            "resulted_ci_id": resulted_ci_id,
        }
        result = self._run(query, **params)
        row = result.single() if hasattr(result, "single") else result
        record = self._record(row)
        if record is None:
            raise CmdbProposalVersionConflictError(
                f"approve race: proposal {proposal_id} not in DRAFT v={expected_version}"
            )
        return record

    def revoke(
        self,
        proposal_id: str,
        expected_version: int,
        reviewer_by: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        now = self._now_iso()
        query = """
        MATCH (p:CIProposal {id: $proposal_id, version: $expected_version})
        WHERE p.status IN [$draft_status, $approved_status]
        SET
            p.status = $revoked_status,
            p.version = $expected_version + 1,
            p.reviewed_by = $reviewer_by,
            p.reviewed_at = datetime($reviewed_at),
            p.updated_at = datetime($updated_at),
            p.revoke_reason = $reason
        RETURN
            p.id AS id,
            p.manifest_json AS manifest_json,
            p.applied_manifest_json AS applied_manifest_json,
            p.status AS status,
            p.version AS version,
            p.proposed_by AS proposed_by,
            p.proposed_role AS proposed_role,
            p.reviewed_by AS reviewed_by,
            p.reviewed_at AS reviewed_at,
            p.created_at AS created_at,
            p.updated_at AS updated_at,
            p.resulted_ci_id AS resulted_ci_id,
            p.revoke_reason AS revoke_reason,
            p.proposed_category AS proposed_category,
            p.ci_id AS ci_id
        """
        params = {
            "proposal_id": proposal_id,
            "expected_version": expected_version,
            "draft_status": CI_PROPOSAL_STATUS_DRAFT,
            "approved_status": CI_PROPOSAL_STATUS_APPROVED,
            "revoked_status": CI_PROPOSAL_STATUS_REVOKED,
            "reviewer_by": reviewer_by,
            "reviewed_at": now,
            "updated_at": now,
            "reason": reason,
        }
        result = self._run(query, **params)
        row = result.single() if hasattr(result, "single") else result
        record = self._record(row)
        if record is None:
            raise CmdbProposalVersionConflictError(
                f"revoke race: proposal {proposal_id} not in DRAFT/APPROVED v={expected_version}"
            )
        return record

    # ── ttl_sweep ──────────────────────────────────────────────────────────

    def ttl_sweep(self, retention_days: int = 30) -> int:
        """Revoke stale DRAFT proposals older than ``retention_days``.

        Returns the number of proposals transitioned. Idempotent — re-running
        a sweep on already-revoked rows matches 0 rows.
        """
        now = self._now_iso()
        query = """
        MATCH (p:CIProposal)
        WHERE p.status = $draft_status
          AND p.created_at < datetime() - duration({days: $retention_days})
        SET
            p.status = $revoked_status,
            p.version = coalesce(p.version, 1) + 1,
            p.reviewed_by = $system_reviewer,
            p.reviewed_at = datetime($now),
            p.updated_at = datetime($now),
            p.revoke_reason = $reason
        RETURN count(p) AS count
        """
        params = {
            "draft_status": CI_PROPOSAL_STATUS_DRAFT,
            "revoked_status": CI_PROPOSAL_STATUS_REVOKED,
            "retention_days": retention_days,
            "system_reviewer": "SYSTEM",
            "now": now,
            "reason": "ttl_expired",
        }
        result = self._run(query, **params)
        if hasattr(result, "single"):
            row = result.single()
        elif hasattr(result, "__iter__"):
            row = next(iter(result), None)
        else:
            row = result
        if row is None:
            return 0
        try:
            return int(row.get("count", 0) if hasattr(row, "get") else row["count"])
        except Exception:
            return 0


# Singleton helper (matches mqtt_mapping_repo pattern).
_cmdb_proposal_repo: CmdbProposalRepo | None = None


def get_cmdb_proposal_repo(driver: Any | None = None) -> CmdbProposalRepo:
    global _cmdb_proposal_repo
    if _cmdb_proposal_repo is None:
        _cmdb_proposal_repo = CmdbProposalRepo(driver=driver)
    return _cmdb_proposal_repo
