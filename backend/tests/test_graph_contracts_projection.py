"""DetailProjectionPolicy Protocol tests (#390).

Split out of test_graph_contracts.py so each contract module ships with
its own focused test file (work-unit commits).
"""
from __future__ import annotations

import pytest

class TestDetailProjectionPolicyProtocol:
    """REQ-2 / REQ-9 — DetailProjectionPolicy interface contract (no impl).

    The policy interface is pinned here. The actual implementation reuses
    the existing ``/graph/full`` projection helper and lives in #391.

    Invariants:

    - ``show_sensitive_metadata`` default is ALWAYS ``False``.
    - ``True`` requires BOTH the ``graph:aggregate_breakdown:read``
      permission AND the caller explicitly requested sensitive fields
      (``?sensitive=include``).
    - The endpoint MUST NEVER default to ``True``.
    - ``sensitive_source`` is one of
      ``{never, principal_scope, principal_with_permission}``.
    """

    def test_default_show_sensitive_metadata_is_false(self):
        """A bare principal with no permission requested must NOT see sensitive."""
        from contracts.projection import (
            PERMISSION_REQUIRED_FOR_SENSITIVE,
            DetailProjectionPolicy,
            SensitiveSource,
        )

        # A no-op policy stub used only to exercise the protocol contract.
        class _Stub(DetailProjectionPolicy):
            def apply_to_node(self, node, principal):
                return node

            def show_sensitive_metadata(self, principal, requested):
                return False

            def sensitive_source(self, principal, allowed):
                return SensitiveSource.NEVER

        p = _Stub()
        assert p.show_sensitive_metadata(principal=None, requested=False) is False
        assert p.show_sensitive_metadata(principal=None, requested=True) is False

    def test_sensitive_source_never_when_request_denied(self):
        from contracts.projection import DetailProjectionPolicy, SensitiveSource

        class _Stub(DetailProjectionPolicy):
            def apply_to_node(self, node, principal):
                return node

            def show_sensitive_metadata(self, principal, requested):
                return False

            def sensitive_source(self, principal, allowed):
                return SensitiveSource.NEVER

        assert _Stub().sensitive_source(principal=None, allowed=False) == SensitiveSource.NEVER

    def test_sensitive_source_principal_scope_when_no_permission(self):
        """Caller is allowed to see the source cluster scope, but lacks the
        aggregate-breakdown permission. sensitive_source reflects the broader
        scope (visible_to_caller), but ``show_sensitive_metadata`` is False.
        """
        from contracts.projection import DetailProjectionPolicy, SensitiveSource

        class _Stub(DetailProjectionPolicy):
            def apply_to_node(self, node, principal):
                return node

            def show_sensitive_metadata(self, principal, requested):
                return False

            def sensitive_source(self, principal, allowed):
                # Caller scope is allowed, but lacks the breakdown permission.
                return (
                    SensitiveSource.PRINCIPAL_SCOPE
                    if allowed and not principal_has_breakdown(principal)
                    else SensitiveSource.NEVER
                )

        def principal_has_breakdown(p) -> bool:
            return False

        assert _Stub().sensitive_source(principal=None, allowed=True) == SensitiveSource.PRINCIPAL_SCOPE

    def test_sensitive_source_principal_with_permission_when_allowed(self):
        from contracts.projection import DetailProjectionPolicy, SensitiveSource

        class _Stub(DetailProjectionPolicy):
            def apply_to_node(self, node, principal):
                return node

            def show_sensitive_metadata(self, principal, requested):
                return bool(getattr(principal, "_breakdown", False)) and bool(requested)

            def sensitive_source(self, principal, allowed):
                if allowed and getattr(principal, "_breakdown", False):
                    return SensitiveSource.PRINCIPAL_WITH_PERMISSION
                if allowed:
                    return SensitiveSource.PRINCIPAL_SCOPE
                return SensitiveSource.NEVER

        class _P:
            _breakdown = True

        assert (
            _Stub().sensitive_source(principal=_P(), allowed=True)
            == SensitiveSource.PRINCIPAL_WITH_PERMISSION
        )

    def test_protocol_constant_permission_required(self):
        from contracts.projection import PERMISSION_REQUIRED_FOR_SENSITIVE

        # The sensitive-fields gate permission MUST be the same string used
        # by AggregatePolicy (REQ-9).
        from contracts.aggregate_policy import PERMISSION_REQUIRED

        assert PERMISSION_REQUIRED_FOR_SENSITIVE == PERMISSION_REQUIRED

    def test_protocol_is_runtime_checkable(self):
        """DetailProjectionPolicy can be used with isinstance() against a stub."""
        from contracts.projection import DetailProjectionPolicy, SensitiveSource

        class _Stub:
            def apply_to_node(self, node, principal):
                return node

            def show_sensitive_metadata(self, principal, requested):
                return False

            def sensitive_source(self, principal, allowed):
                return SensitiveSource.NEVER

        assert isinstance(_Stub(), DetailProjectionPolicy)

