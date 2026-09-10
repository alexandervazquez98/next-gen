"""DetailProjectionPolicy protocol (REQ-2, REQ-9) — interface only.

The interface pinned here is satisfied by the ``/graph/full`` projection
helper, which already implements the existing redacted-fields policy. The
concrete implementation reuses that helper and belongs to #391; this slice
defines only the shape and the contract tests.

Invariants:

- ``show_sensitive_metadata`` default is ALWAYS ``False``.
- ``True`` requires BOTH ``graph:aggregate_breakdown:read`` permission AND
  the caller explicitly requested sensitive fields (e.g. ``?sensitive=include``).
- The endpoint MUST NEVER default to ``True``.
- ``sensitive_source`` is one of
  ``{never, principal_scope, principal_with_permission}``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from contracts.aggregate_policy import PERMISSION_REQUIRED

# Re-export so the projection module is the single import for sensitive
# metadata gating.
PERMISSION_REQUIRED_FOR_SENSITIVE = PERMISSION_REQUIRED


class SensitiveSource(StrEnum):
    """Origin of any sensitive metadata returned on a detail node."""

    NEVER = "never"
    PRINCIPAL_SCOPE = "principal_scope"
    PRINCIPAL_WITH_PERMISSION = "principal_with_permission"


@runtime_checkable
class DetailProjectionPolicy(Protocol):
    """Protocol contract for detail-node projection.

    The concrete implementation lives in #391 and MUST satisfy:

    - ``apply_to_node`` returns a redacted node copy. ``principal`` is the
      authenticated user (may be ``None`` for unauthenticated callers).
    - ``show_sensitive_metadata`` returns ``True`` ONLY when BOTH the
      caller has ``graph:aggregate_breakdown:read`` AND ``requested=True``.
      Otherwise it MUST return ``False``.
    - ``sensitive_source`` returns the ``SensitiveSource`` enum member that
      describes why a (potential) sensitive field is or is not present.
    """

    def apply_to_node(self, node: Any, principal: Any) -> Any: ...

    def show_sensitive_metadata(self, principal: Any, requested: bool) -> bool: ...

    def sensitive_source(self, principal: Any, allowed: bool) -> SensitiveSource: ...
