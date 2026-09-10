"""Opaque pagination cursor for LOD endpoints (REQ-5).

Wire format: ``base64url(json({v:1, cluster_id, filters_hash, revision,
principal_hash, nonce}))``

The cursor binds pagination state to a (cluster_id, filters, revision,
principal) tuple so that:

- A revision change yields ``StaleCursorError`` (HTTP 409 ``stale_cursor``).
- A principal permission change yields ``PermissionChangedError``
  (HTTP 400 ``stale_cursor`` / ``permission_changed``).
- Any other parse failure yields ``InvalidCursorError``
  (HTTP 400 ``invalid_cursor``).

Pure module. No IO. No Pydantic.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CURSOR_VERSION = 1
HASH_PREFIX_LEN = 16  # 16 hex chars = 64 bits


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvalidCursorError(ValueError):
    """The cursor is malformed (bad base64, missing fields, wrong version)."""

    def as_error_body(self) -> dict[str, str]:
        return {"error": "invalid_cursor"}


class StaleCursorError(ValueError):
    """The cursor is bound to a revision that no longer matches."""

    def __init__(self, stale_revision: str, current_revision: str) -> None:
        super().__init__(
            f"stale_cursor: stale={stale_revision!r}, current={current_revision!r}"
        )
        self.stale_revision = stale_revision
        self.current_revision = current_revision

    def as_error_body(self) -> dict[str, str]:
        return {
            "error": "stale_cursor",
            "current_revision": self.current_revision,
        }


class PermissionChangedError(ValueError):
    """The cursor is bound to a principal whose permissions have changed."""

    def as_error_body(self) -> dict[str, str]:
        return {"error": "stale_cursor", "reason": "permission_changed"}


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecodedCursor:
    cluster_id: str
    filters: dict
    filters_hash: str
    revision: str
    principal_hash: str
    nonce: str
    version: int


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------


def canonical_json(filters: dict) -> str:
    """Canonical JSON serialization for filter hashing.

    Sorts keys recursively so that two dicts with the same content but
    different insertion order produce identical hashes.
    """
    return json.dumps(filters, sort_keys=True, separators=(",", ":"), default=str)


def derive_filters_hash(filters: dict) -> str:
    """Return the 16-hex-char SHA-256 prefix of canonical_json(filters)."""
    payload = canonical_json(filters).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:HASH_PREFIX_LEN]


def derive_principal_hash(permissions: set | list | frozenset) -> str:
    """Return the 16-hex-char SHA-256 prefix of a sorted permission set.

    Accepts any iterable of strings. The set is sorted (lexicographically)
    before hashing so ``{"A", "B"}`` and ``{"B", "A"}`` hash identically.
    """
    sorted_perms = sorted(str(p) for p in permissions)
    payload = "|".join(sorted_perms).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:HASH_PREFIX_LEN]


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------


def encode_cursor(
    cluster_id: str,
    filters: dict,
    revision,  # Revision
    principal_hash: str,
    *,
    nonce: str | None = None,
) -> str:
    """Encode pagination state into an opaque cursor string.

    ``revision`` is a :class:`contracts.revision.Revision` instance.
    ``principal_hash`` is the 16-hex-char SHA-256 prefix of the caller's
    sorted permission set (``derive_principal_hash`` can compute it).
    """
    payload = {
        "v": CURSOR_VERSION,
        "cluster_id": cluster_id,
        "filters_hash": derive_filters_hash(filters),
        "revision": str(revision.value),
        "principal_hash": principal_hash,
        "nonce": nonce if nonce is not None else secrets.token_urlsafe(8),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(
    encoded: str,
    *,
    current_revision=None,  # Revision | None
    current_principal_hash: str | None = None,
) -> DecodedCursor:
    """Decode an opaque cursor string into a :class:`DecodedCursor`.

    Errors:
    - :class:`InvalidCursorError` for any parse / format / version problem.
    - :class:`StaleCursorError` when the cursor's revision differs from
      ``current_revision``.
    - :class:`PermissionChangedError` when the cursor's ``principal_hash``
      differs from ``current_principal_hash``.
    """
    if not isinstance(encoded, str) or encoded == "":
        raise InvalidCursorError("cursor must be a non-empty string")

    # Restore base64 padding.
    padding = "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(encoded + padding)
    except (ValueError, TypeError, base64.binascii.Error) as exc:
        raise InvalidCursorError(f"cursor is not valid base64url: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCursorError(f"cursor payload is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise InvalidCursorError("cursor payload must be a JSON object")

    version = payload.get("v")
    if version != CURSOR_VERSION:
        raise InvalidCursorError(f"unsupported cursor version: {version!r}")

    required = ("cluster_id", "filters_hash", "revision", "principal_hash")
    missing = [k for k in required if k not in payload]
    if missing:
        raise InvalidCursorError(f"cursor missing keys: {missing}")

    cluster_id = payload["cluster_id"]
    filters_hash = payload["filters_hash"]
    revision_value = payload["revision"]
    principal_hash = payload["principal_hash"]

    # Revision drift -> 409 stale_cursor with current_revision.
    if current_revision is not None:
        if str(current_revision.value) != revision_value:
            raise StaleCursorError(
                stale_revision=revision_value,
                current_revision=str(current_revision.value),
            )

    # Principal drift -> 400 stale_cursor / permission_changed.
    if current_principal_hash is not None:
        if current_principal_hash != principal_hash:
            raise PermissionChangedError(
                "cursor principal_hash does not match current principal"
            )

    return DecodedCursor(
        cluster_id=cluster_id,
        filters={},  # filter values are NOT serialized in the cursor — only the hash
        filters_hash=filters_hash,
        revision=revision_value,
        principal_hash=principal_hash,
        nonce=payload.get("nonce", ""),
        version=version,
    )
