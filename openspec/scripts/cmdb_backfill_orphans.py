"""CMDB Orphan Topology Backfill — P3a of fix #416.

Read-only, offline CLI that surfaces Access Points with no upstream
DEPENDS_ON|HOSTED_ON edge so an operator can manually wire them in
internal CMDB tooling. No auto-write, no heuristics, no enrichment beyond
opaque CI IDs.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# AD-01: scope is restricted to APs in this slice.
ALLOWED_SCOPES = frozenset({"ap"})

# AD-08: relationship-type allowlist. CONNECTS_TO is intentionally excluded
# per correlation-topology-guide.md (no parentage semantics).
ALLOWED_RELATIONSHIP_TYPES = frozenset(
    {"DEPENDS_ON", "HOSTED_ON", "MANAGES", "RUNS_ON"}
)

# REQ-002 default upstream edges.
DEFAULT_RELATIONSHIP_TYPES = ("DEPENDS_ON", "HOSTED_ON")

# AD-03: opaque CI-ID shape: synthetic placeholder or UUID.
SYNTHETIC_ID_RE = re.compile(r"^ci-test-ap-orphan-\d{3,}$")
_UUID_SHAPE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_scope(scope: str) -> None:
    """Validate --scope.

    Returns None on success. Raises ``ValueError`` with the exact
    ``error: invalid --scope <value>; allowed: ap`` shape on any value
    not in ``ALLOWED_SCOPES``.
    """
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"error: invalid --scope {scope}; allowed: ap")


def validate_relationship_types(types) -> list:
    """Validate --relationship-types against the allowlist.

    ``None`` or an empty list returns the default upstream edges. Inputs
    are deduped while preserving first-seen order. Any value outside
    ``ALLOWED_RELATIONSHIP_TYPES`` (raw Cypher fragments included) raises
    ``ValueError`` before any Neo4j session is opened.
    """
    if not types:
        return list(DEFAULT_RELATIONSHIP_TYPES)
    seen: dict = {}
    for value in types:
        if value in ALLOWED_RELATIONSHIP_TYPES:
            seen[value] = True
            continue
        raise ValueError(
            f"error: invalid --relationship-types {value!r}; "
            f"allowed: {sorted(ALLOWED_RELATIONSHIP_TYPES)}"
        )
    return list(seen.keys())


def _validate_ci_id(value) -> str:
    """Strict validator for a single opaque CI ID.

    Accepts synthetic placeholders (``ci-test-ap-orphan-NNN``) and any
    UUID-shaped string. UUIDs are returned lowercase as the canonical
    form. Real-shape strings (customer names, IPv4 addresses, sites,
    malformed suffixes) raise ``ValueError``.
    """
    if not isinstance(value, str):
        raise ValueError(f"ci id must be a string: {value!r}")
    if SYNTHETIC_ID_RE.match(value):
        return value
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(
            f"ci id must match synthetic pattern or UUID shape: {value!r}"
        ) from exc


def _is_opaque_ci_id(value) -> bool:
    """Loose check used by ``build_output_payload`` to filter Neo4j rows.

    Anything that is not a string OR not synthetic/UUID-shaped is
    considered non-opaque and silently dropped from the output envelope.
    """
    return isinstance(value, str) and bool(
        SYNTHETIC_ID_RE.match(value) or _UUID_SHAPE_RE.match(value)
    )


def _now_iso8601_utc() -> str:
    """Return ISO 8601 UTC timestamp with trailing ``Z``."""
    return (
        datetime.now(timezone.utc)  # noqa: UP017
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def build_output_payload(
    *,
    scope: str,
    rels,
    ci_ids,
    as_of=None,
) -> dict:
    """Construct the strict JSON output envelope (REQ-003 / REQ-004).

    The returned dict has EXACTLY these top-level keys, in this
    structural shape:

    - ``as_of``: ISO 8601 UTC timestamp with trailing ``Z``.
    - ``scope``: the validated scope string.
    - ``relationship_types``: list of validated relationship-type
      strings in their original order.
    - ``orphan_count``: integer equal to ``len(ci_ids)``.
    - ``ci_ids``: list of opaque CI IDs in first-seen order, with
      non-opaque values stripped.

    ``as_of`` defaults to the current UTC time when not provided.
    """
    timestamp = as_of if as_of is not None else _now_iso8601_utc()
    opaque = [value for value in ci_ids if _is_opaque_ci_id(value)]
    deduped = list(dict.fromkeys(opaque))
    return {
        "as_of": timestamp,
        "scope": scope,
        "relationship_types": list(rels),
        "orphan_count": len(deduped),
        "ci_ids": deduped,
    }


def write_output(payload: dict, output_path) -> None:
    """Serialize ``payload`` to JSON and route to file or stdout.

    When ``output_path`` is ``None``, JSON is written to stdout.
    Otherwise, JSON is written to ``output_path`` via an atomic
    ``.tmp`` + ``replace`` so partial files never appear. Always
    returns ``None``; raises ``OSError`` for filesystem failures.
    """
    rendered = json.dumps(payload, indent=2) + "\n"
    if output_path is None:
        sys.stdout.write(rendered)
        sys.stdout.flush()
        return
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(target.name + ".tmp")
    tmp_path.write_text(rendered, encoding="utf-8")
    tmp_path.replace(target)

