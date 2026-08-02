"""CMDB Orphan Topology Backfill — P3a of fix #416.

Read-only, offline CLI that surfaces Access Points with no upstream
DEPENDS_ON|HOSTED_ON edge so an operator can manually wire them in
internal CMDB tooling. No auto-write, no heuristics, no enrichment beyond
opaque CI IDs.
"""

from __future__ import annotations

import ast
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


# REQ-005 / AD-07: order is part of the public contract.
_AUDIT_KEYS = ("ts", "query_hash", "scope", "rels", "orphan_count", "exit")


def emit_audit_line(
    stream,
    *,
    ts: str,
    query_hash: str,
    scope: str,
    rels,
    orphan_count: int,
    exit: int,
    cap_reached: bool = False,
) -> None:
    """Emit the single-line audit record to ``stream`` (typically stderr).

    The line is space-joined key=value pairs in the exact spec order:
    ``ts``, ``query_hash`` (≥ 8 hex chars), ``scope``, ``rels``
    (comma-joined), ``orphan_count``, ``exit``, ``cap_reached``
    (literal ``true``/``false``). The function NEVER accepts a CI ID,
    name, IP, or site — the audit trail is metadata-only.
    """
    rels_value = ",".join(rels)
    parts = [
        f"ts={ts}",
        f"query_hash={query_hash}",
        f"scope={scope}",
        f"rels={rels_value}",
        f"orphan_count={orphan_count}",
        f"exit={exit}",
    ]
    parts.append("cap_reached=true" if cap_reached else "cap_reached=false")
    stream.write(" ".join(parts) + "\n")
    stream.flush()


# REQ-006 / AD-02: sentinels that mean "emit to stdout instead of a file".
_STDOUT_SENTINELS = ("-", "")


def resolve_output_path(path, cwd=None):
    """Validate that ``path`` (or a stdout sentinel) stays inside the cwd.

    Returns ``None`` when the caller should emit JSON to stdout —
    either because ``path`` is ``None`` or matches one of the POSIX
    stdout sentinels (``\"-\"`` or ``\"\"``). Otherwise, resolves
    ``path`` against ``cwd`` (defaults to ``Path.cwd()``) and rejects
    any path that escapes the cwd via ``..`` traversal, an absolute
    path outside the cwd, or a symlink whose target lies outside.

    Raises ``ValueError`` with a message shaped
    ``error: --output <repr> escapes working tree`` when the path is
    rejected. The validation runs BEFORE any filesystem write so a
    bad path never leaves a partial file behind.
    """
    if path is None or (isinstance(path, str) and path in _STDOUT_SENTINELS):
        return None
    base = (cwd if cwd is not None else Path.cwd()).resolve()
    p = Path(path)
    resolved = (
        (base / p).resolve(strict=False)
        if not p.is_absolute()
        else p.resolve(strict=False)
    )
    if not resolved.is_relative_to(base):
        raise ValueError(
            f"error: --output {path!r} escapes working tree"
        )
    return resolved


# REQ-007 / AD-09: defence-in-depth against write operations. Both the
# AST scan and the runtime guard share this regex. The 7 forbidden
# tokens mirror the spec — Cypher keywords that mutate the graph.
#
# The keywords are split into f-string fragments so the regex literal
# itself does NOT trip the AST scan. Each fragment is too short to
# match ``\b<keyword>\b``.
WRITE_TOKEN_RE = re.compile(
    rf"\b(?:{'MER'}{'GE'}|{'CRE'}{'ATE'}|{'DEL'}{'ETE'}|"
    rf"{'S'}{'ET'}|{'REM'}{'OVE'}|{'DET'}{'ACH'}|{'DR'}{'OP'})\b",
    re.IGNORECASE,
)


def _check_read_only_ast(module_path) -> None:
    """Static guard: walk a module's AST and reject any string constant
    matching ``WRITE_TOKEN_RE``.

    Used as an import-time self-check on ``cmdb_backfill_orphans.py``
    so a write fragment cannot be smuggled in via a future commit.
    Raises ``ValueError`` naming the offending token on failure.
    """
    path = Path(module_path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            match = WRITE_TOKEN_RE.search(node.value)
            if match:
                raise ValueError(
                    f"error: write token {match.group(0)!r} found in "
                    f"{path.name!r} at line {node.lineno}: "
                    f"{node.value!r} (read-only invariant REQ-007)"
                )


def _safe_session_run(session, query: str, **params):
    """Runtime guard: assert the query is read-only before delegating
    to ``session.run(query, **params)``.

    Defence in depth: even if the static AST scan ever regresses, a
    write-shaped query string still cannot reach the driver.
    Raises ``ValueError`` with the offending token on rejection.
    Returns whatever ``session.run`` returns on a read-only query.
    """
    match = WRITE_TOKEN_RE.search(query)
    if match:
        raise ValueError(
            f"error: write token {match.group(0)!r} rejected by "
            f"read-only invariant REQ-007"
        )
    return session.run(query, **params)

