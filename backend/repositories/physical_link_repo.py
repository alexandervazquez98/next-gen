"""Repository for the :PhysicalLink label — feat-444-physical-link-styling (slice 2).

Slice 2/4 of the fiber-optic / physical-link visualization chain (#444). The
metadata model and migration shipped in slice 1 (#323); this module layers the
CRUD boundary on top of the same ``:PhysicalLink`` label so the legend /
preview pipeline can read and mutate physical link data end-to-end.

Mirrors the optimistic-version precedent at
``backend/repositories/cmdb_proposal_repo.py`` — every Cypher statement is
parameterized via ``$params`` so user-supplied data can never be interpolated
into the query string. Endpoints are stored as a 2-tuple on the Python side
to match the backend ``PhysicalLink`` Pydantic model and are projected back
out as a 2-list (JSON wire compatibility for the frontend DTO).
"""

from __future__ import annotations

from typing import Any

from database import get_db

# Field set returned to callers. Keeps the projection explicit so the wire
# shape stays stable even when the underlying node gains optional fields.
_RETURN_FIELDS: tuple[str, ...] = (
    "id",
    "type",
    "endpoints",
    "status",
    "capacity_gbps",
    "install_date",
)


class PhysicalLinkNotFoundError(RuntimeError):
    """Raised when a physical link id is unknown."""


class PhysicalLinkRepo:
    """Persist and query ``:PhysicalLink`` nodes."""

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
        """Shape a Neo4j row into the wire-format dict the API expects.

        - ``endpoints`` is projected from the tuple we stored into a 2-list so
          the JSON response matches the frontend ``PhysicalLink.endpoints:
          [string, string]`` DTO byte-for-byte.
        - Only known fields are forwarded; everything else is dropped.
        """
        if row is None:
            return None

        # The dict-style access is the same on MockNeo4jRecord and on the
        # live neo4j.Record — both implement ``__getitem__`` / ``.get``.
        def _get(key: str) -> Any:
            try:
                if hasattr(row, "get"):
                    return row.get(key)
                return row[key]
            except Exception:
                return None

        out: dict[str, Any] = {}
        for field in _RETURN_FIELDS:
            out[field] = _get(field)

        # Normalise endpoints tuple -> list for the wire (JSON has no tuple).
        endpoints = out.get("endpoints")
        if endpoints is None:
            out["endpoints"] = []
        elif isinstance(endpoints, (list, tuple)):
            out["endpoints"] = list(endpoints)
        else:
            # Defensive: any other shape is coerced into a 2-list when possible.
            try:
                out["endpoints"] = list(endpoints)
            except Exception:
                out["endpoints"] = []

        return out

    # ── create ──────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        link_id: str,
        link_type: str,
        endpoints: tuple[str, str],
        status: str = "UNKNOWN",
        capacity_gbps: float | None = None,
        install_date: str | None = None,
    ) -> dict[str, Any]:
        """Persist a new ``:PhysicalLink`` and return the wire-format row.

        Endpoints are stored as a 2-tuple on the node (``pl.endpoints = [a, b]``
        — Neo4j accepts a Python list and reads it back identically). The
        response projects them as a list to match the frontend DTO.
        """
        endpoint_a, endpoint_b = endpoints

        query = """
        CREATE (pl:PhysicalLink)
        SET
            pl.id = $link_id,
            pl.type = $link_type,
            pl.endpoints = [$endpoint_a, $endpoint_b],
            pl.status = $status,
            pl.capacity_gbps = $capacity_gbps,
            pl.install_date = $install_date
        RETURN
            pl.id AS id,
            pl.type AS type,
            pl.endpoints AS endpoints,
            pl.status AS status,
            pl.capacity_gbps AS capacity_gbps,
            pl.install_date AS install_date
        """
        params = {
            "link_id": link_id,
            "link_type": link_type,
            "endpoint_a": endpoint_a,
            "endpoint_b": endpoint_b,
            "status": status,
            "capacity_gbps": capacity_gbps,
            "install_date": install_date,
        }
        result = self._run(query, **params)
        row = result.single() if hasattr(result, "single") else result
        record = self._record(row)
        if record is None:
            raise RuntimeError("Failed to create PhysicalLink")
        return record

    # ── get_by_id ───────────────────────────────────────────────────────────

    def get_by_id(self, link_id: str) -> dict[str, Any] | None:
        query = """
        MATCH (pl:PhysicalLink)
        WHERE pl.id = $link_id
        RETURN
            pl.id AS id,
            pl.type AS type,
            pl.endpoints AS endpoints,
            pl.status AS status,
            pl.capacity_gbps AS capacity_gbps,
            pl.install_date AS install_date
        """
        result = self._run(query, link_id=link_id)
        row = result.single() if hasattr(result, "single") else result
        return self._record(row)

    # ── list ────────────────────────────────────────────────────────────────

    def list(
        self,
        *,
        ci_id: str | None = None,
        link_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List PhysicalLink rows with optional ``ci_id`` / ``type`` / ``status`` filters.

        The ``ci_id`` filter is a flat match against either endpoint of the
        stored ``endpoints`` list — see feat-444 spec note. Slice 3 (#439)
        will replace this with a graph traversal via ``CONNECTED_VIA``.
        """
        params: dict[str, Any] = {
            "ci_id": ci_id,
            "link_type": link_type,
            "status": status,
            "limit": max(1, limit),
            "offset": max(0, offset),
        }
        query = """
        MATCH (pl:PhysicalLink)
        WHERE
            ($ci_id IS NULL OR $ci_id IN pl.endpoints)
            AND ($link_type IS NULL OR pl.type = $link_type)
            AND ($status IS NULL OR pl.status = $status)
        RETURN
            pl.id AS id,
            pl.type AS type,
            pl.endpoints AS endpoints,
            pl.status AS status,
            pl.capacity_gbps AS capacity_gbps,
            pl.install_date AS install_date
        ORDER BY pl.id
        SKIP $offset LIMIT $limit
        """
        result = self._run(query, **params)
        if hasattr(result, "data"):
            rows = result.data()
        elif hasattr(result, "__iter__"):
            rows = list(result)
        else:
            rows = []
        return [r for r in (self._record(row) for row in rows) if r is not None]

    # ── update_status ───────────────────────────────────────────────────────

    def update_status(self, link_id: str, status: str) -> dict[str, Any] | None:
        """Set the ``status`` field on the matching PhysicalLink row.

        Returns the refreshed row, or ``None`` when the id is unknown so the
        service layer can map that to HTTP 404.
        """
        query = """
        MATCH (pl:PhysicalLink)
        WHERE pl.id = $link_id
        SET pl.status = $status
        RETURN
            pl.id AS id,
            pl.type AS type,
            pl.endpoints AS endpoints,
            pl.status AS status,
            pl.capacity_gbps AS capacity_gbps,
            pl.install_date AS install_date
        """
        params = {"link_id": link_id, "status": status}
        result = self._run(query, **params)
        row = result.single() if hasattr(result, "single") else result
        return self._record(row)


# Singleton helper (matches the cmdb_proposal_repo / mqtt_mapping_repo pattern).
_physical_link_repo: PhysicalLinkRepo | None = None


def get_physical_link_repo(driver: Any | None = None) -> PhysicalLinkRepo:
    global _physical_link_repo
    if _physical_link_repo is None:
        _physical_link_repo = PhysicalLinkRepo(driver=driver)
    return _physical_link_repo
