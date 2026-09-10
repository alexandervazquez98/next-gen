"""Opaque revision token for cache invalidation (REQ-6).

The actual derivation algorithm (``Revision.derive(snapshot)``) is pinned here
but the production impl belongs to #391 — the slice that introduces the
backend aggregation queries needed to compute a visibility-scoped hash.

For tests and fixtures, callers use the ``Revision("test-revision-0001")``
constructor directly. This lets the spec coverage gate run against a
deterministic revision without depending on #391 internals.

Invariants pinned in this slice:

- ``Revision.derive(snapshot) = "rev-" + sha256(snapshot).hexdigest()[:16]``
  (docstring only — impl in #391)
- Two ``Revision`` instances are equal iff their ``.value`` strings match.
- The token is opaque to clients; React Query uses it as a cache key.

No IO. No Pydantic.
"""

from __future__ import annotations

import hashlib


class Revision:
    """Opaque, deterministic, visibility-scoped revision token (REQ-6).

    Equality is by ``.value``. The token is opaque to clients; callers treat
    it as a black-box string for caching purposes only.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or value == "":
            raise ValueError("Revision value must be a non-empty string")
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Revision({self._value!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Revision):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    @staticmethod
    def derive(snapshot: bytes) -> "Revision":
        """Derive a Revision from a snapshot payload.

        Algorithm (pinned in this slice; impl belongs to #391):

            ``"rev-" + sha256(snapshot).hexdigest()[:16]``

        For the contract slice, callers should NOT depend on this method's
        output — the real derivation will move to #391 alongside the
        aggregation queries that produce ``snapshot``. This stub exists so
        the spec coverage gate can reference the algorithm without depending
        on #391 internals.
        """
        digest = hashlib.sha256(snapshot).hexdigest()[:16]
        return Revision(f"rev-{digest}")
