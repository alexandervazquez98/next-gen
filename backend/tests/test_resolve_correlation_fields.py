"""Unit tests for the `resolve_correlation_fields` resolver (REQ-CORR-1/2/3).

The resolver wraps `repositories.topology_repo.find_open_parent_event` and
returns the dict used by Path A / Path C / CLI write paths to populate
`correlation_type`, `propagated_from`, and `root_cause_ci_id`.

Design contract:
    resolve_correlation_fields(
        ci_id: str,
        severity: str,
        *,
        can_propagate: bool = True,
        cache: dict | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> dict

Returns {correlation_type, propagated_from, root_cause_ci_id}.

Fail-safe: if the parent lookup raises, returns ROOT with the event's own CI
so collectors never block on topology hiccups.

These tests are RED — they fail because the resolver is not yet defined.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def _import_resolver():
    """Import the resolver without importing the whole event_service module.

    The resolver lives in services.event_service. We import the module and
    return the symbol under test.
    """
    from services.event_service import resolve_correlation_fields

    return resolve_correlation_fields


def _parent_event(event_id="evt-parent-001", parent_ci="ci-parent-001", root="ci-parent-001", ctype="ROOT"):
    return {
        "parent_event_id": event_id,
        "parent_ci_id": parent_ci,
        "root_cause_ci_id": root,
        "correlation_type": ctype,
    }


class TestResolveCorrelationFieldsImport:
    """The resolver must be importable from services.event_service."""

    def test_resolver_is_exported(self):
        resolve_correlation_fields = _import_resolver()
        assert callable(resolve_correlation_fields)


class TestResolveCorrelationFieldsNoParent:
    """When no parent has an open event, return ROOT with own CI."""

    def test_no_parent_returns_root_with_own_ci(self):
        resolve_correlation_fields = _import_resolver()
        with patch(
            "repositories.topology_repo.find_open_parent_event", return_value=None
        ):
            result = resolve_correlation_fields("ci-child-001", "CRITICAL")
        assert result == {
            "correlation_type": "ROOT",
            "propagated_from": None,
            "root_cause_ci_id": "ci-child-001",
        }


class TestResolveCorrelationFieldsWithParent:
    """When a parent has an open event, return PROPAGATED."""

    def test_one_hop_parent_returns_propagated(self):
        resolve_correlation_fields = _import_resolver()
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=_parent_event(),
        ):
            result = resolve_correlation_fields("ci-child-001", "CRITICAL")
        assert result == {
            "correlation_type": "PROPAGATED",
            "propagated_from": "evt-parent-001",
            "root_cause_ci_id": "ci-parent-001",
        }

    def test_propagated_parent_inherits_root_cause(self):
        """If parent itself is PROPAGATED, child inherits the original root."""
        resolve_correlation_fields = _import_resolver()
        parent = _parent_event(
            event_id="evt-mid-001",
            parent_ci="ci-mid-001",
            root="ci-original-root-001",
            ctype="PROPAGATED",
        )
        with patch(
            "repositories.topology_repo.find_open_parent_event", return_value=parent
        ):
            result = resolve_correlation_fields("ci-leaf-001", "WARNING")
        assert result["correlation_type"] == "PROPAGATED"
        assert result["propagated_from"] == "evt-mid-001"
        assert result["root_cause_ci_id"] == "ci-original-root-001"


class TestResolveCorrelationFieldsFailSafe:
    """When the parent lookup raises, return ROOT (never propagate the error)."""

    def test_find_open_parent_event_raises_returns_root(self):
        resolve_correlation_fields = _import_resolver()
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            side_effect=RuntimeError("neo4j unavailable"),
        ):
            result = resolve_correlation_fields("ci-child-001", "CRITICAL")
        assert result == {
            "correlation_type": "ROOT",
            "propagated_from": None,
            "root_cause_ci_id": "ci-child-001",
        }

    def test_find_open_parent_event_generic_exception_returns_root(self):
        resolve_correlation_fields = _import_resolver()
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            side_effect=Exception("unexpected"),
        ):
            result = resolve_correlation_fields("ci-x", "WARNING")
        assert result["correlation_type"] == "ROOT"
        assert result["root_cause_ci_id"] == "ci-x"
        assert result["propagated_from"] is None


class TestResolveCorrelationFieldsCanPropagate:
    """`can_propagate=False` must short-circuit to ROOT regardless of parent."""

    def test_can_propagate_false_with_open_parent_returns_root(self):
        resolve_correlation_fields = _import_resolver()
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=_parent_event(),
        ) as mock_lookup:
            result = resolve_correlation_fields(
                "ci-child-001", "CRITICAL", can_propagate=False
            )
        # We may still consult the lookup for diagnostics, but the contract is
        # the returned dict. The resolver must never mark the event PROPAGATED
        # when propagation is disabled.
        assert result == {
            "correlation_type": "ROOT",
            "propagated_from": None,
            "root_cause_ci_id": "ci-child-001",
        }
        # Parent lookup is skipped entirely when can_propagate=False to save a Cypher call.
        mock_lookup.assert_not_called()

    def test_can_propagate_true_with_no_parent_returns_root(self):
        resolve_correlation_fields = _import_resolver()
        with patch(
            "repositories.topology_repo.find_open_parent_event", return_value=None
        ):
            result = resolve_correlation_fields("ci-x", "WARNING", can_propagate=True)
        assert result["correlation_type"] == "ROOT"
        assert result["root_cause_ci_id"] == "ci-x"

    def test_default_can_propagate_is_true(self):
        """Backward compatibility: the kwarg default is True."""
        resolve_correlation_fields = _import_resolver()
        with patch(
            "repositories.topology_repo.find_open_parent_event",
            return_value=_parent_event(),
        ):
            result = resolve_correlation_fields("ci-child-001", "CRITICAL")
        assert result["correlation_type"] == "PROPAGATED"


class TestResolveCorrelationFieldsMaxDepth:
    """REQ-CORR-8: max_depth=3 is the project default."""

    def test_default_max_depth_is_three(self):
        resolve_correlation_fields = _import_resolver()
        captured = {}

        def _fake_lookup(ci_id, max_depth=3):
            captured["max_depth"] = max_depth
            return None

        with patch(
            "repositories.topology_repo.find_open_parent_event", side_effect=_fake_lookup
        ):
            resolve_correlation_fields("ci-x", "WARNING")
        assert captured["max_depth"] == 3
