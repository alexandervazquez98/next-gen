"""Value objects and codecs for the CMDB LOD endpoints (REQ-1..9).

Modules:
- cluster_id: cluster identifier codec (axis:key)
- cursor: opaque pagination cursor bound to (cluster_id, filters, revision, principal)
- revision: opaque, deterministic revision token (stub; derive() impl in #391)
- aggregate_policy: minimum_count / safe_geo_precision tiering
- projection: DetailProjectionPolicy Protocol (interface only — no impl)

No IO. No Pydantic dependencies in this package. Pydantic DTOs live in
``backend/schemas/graph.py``.
"""
