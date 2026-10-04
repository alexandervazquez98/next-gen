"""Locked correlation-propagation contract for issue #539.

This module is the single source of truth for the four propagation decisions
locked in issue #539 and recorded in
``docs/correlation-topology-guide.md`` (the "Locked propagation decisions"
section). The chained implementation PRs (PR2 / PR3 / PR4) import from this
module; the parametrized tests in
``backend/tests/test_correlation_propagation_contract.py`` assert the constants
match the values recorded in the doc.

The contract is intentionally implementation-agnostic: it has no I/O, no
Neo4j session, no FastAPI dependency. It is a data module that PR2/3/4 can
import from anywhere without pulling in heavy runtime dependencies.

To change one of the four locked decisions:

1. Update ``docs/correlation-topology-guide.md`` (the "Locked propagation
   decisions" section).
2. Update the corresponding constant in this module.
3. Update the corresponding assertion in
   ``backend/tests/test_correlation_propagation_contract.py``.
4. File a follow-up decision record explaining the change.
"""
from __future__ import annotations

from typing import Final, Literal

# ---------------------------------------------------------------------------
# Locked values (decision 1 of 4)
# ---------------------------------------------------------------------------

#: Decision 1: how a PhysicalLink with status = UNKNOWN participates in
#: event propagation.
#:
#: - ``"degrade_severity_and_propagate"`` (locked): the link propagates, but
#:   the propagated event is emitted at ``WARNING`` severity instead of the
#:   parent's severity. Visibility for the operator, lower signal floor.
#: - ``"block"``: the link does not propagate, treated like DOWN.
#: - ``"propagate"``: the link propagates at the parent's severity.
PHYSICAL_LINK_UNKNOWN_PROPAGATION: Final = "degrade_severity_and_propagate"
UnknownPropagationPolicy = Literal[
    "degrade_severity_and_propagate",
    "block",
    "propagate",
]

# ---------------------------------------------------------------------------
# Locked values (decision 2 of 4)
# ---------------------------------------------------------------------------

#: Decision 2: how the correlation traversal handles PhysicalLink.status
#: freshness.
#:
#: - ``"re_query_per_correlation"`` (locked): the traversal re-reads each
#:   ``:CONNECTED_VIA`` PhysicalLink's ``status`` at query time within the
#:   same Cypher statement. No cache, no TTL.
#: - ``"cache_with_ttl"``: LRU/TTL cache (TTL TBD; revert path if PR2
#:   benchmark exceeds the 50 ms target).
#: - ``"stale_value"``: use the value as stored, no re-read.
#: - ``"patch_only"``: status is static between PATCHes.
PHYSICAL_LINK_STATUS_FRESHNESS: Final = "re_query_per_correlation"
StatusFreshnessPolicy = Literal[
    "re_query_per_correlation",
    "cache_with_ttl",
    "stale_value",
    "patch_only",
]

# ---------------------------------------------------------------------------
# Locked values (decision 3 of 4)
# ---------------------------------------------------------------------------

#: Decision 3: behavior when a PhysicalLink transitions from UP to DOWN.
#:
#: - ``"generate_descendant_event"`` (locked): the system generates a new
#:   event whose ``root_cause_ci_id`` is the link itself and whose affected
#:   CIs are the two endpoints of the link.
#: - ``"block_only"``: DOWN blocks correlation, no new event.
#: - ``"both"``: generate descendant event AND block future correlation.
#: - ``"mark_existing"``: existing events on the endpoints are marked
#:   suspect (``suspect=true``); no new events.
PHYSICAL_LINK_DOWN_BEHAVIOR: Final = "generate_descendant_event"
DownBehaviorPolicy = Literal[
    "generate_descendant_event",
    "block_only",
    "both",
    "mark_existing",
]

# ---------------------------------------------------------------------------
# Locked values (decision 4 of 4)
# ---------------------------------------------------------------------------

#: Decision 4: default propagation for ``:MANAGES``, ``:USES``, ``:PROVIDES``.
#:
#: - ``"all_propagate"`` (locked): the three relationship types are added
#:   to the traversal with default propagation. No per-CI flag, no
#:   per-metric flag, no env-var gate.
#: - ``"none_propagate"``: none propagate (opt-in per metric).
#: - ``"configurable_per_metric"``: opt-in via ``MetricDef`` flag.
#: - ``"configurable_per_ci"``: opt-in via CI node field.
#: - ``"configurable_global"``: env var.
MANAGES_USES_PROVIDES_DEFAULT: Final = "all_propagate"
RelationshipPropagationDefault = Literal[
    "all_propagate",
    "none_propagate",
    "configurable_per_metric",
    "configurable_per_ci",
    "configurable_global",
]

# ---------------------------------------------------------------------------
# Relationship set registry (used by PR2 / PR3 / PR4 to align traversals)
# ---------------------------------------------------------------------------

#: Relationship types that the chained PRs will eventually walk. Includes
#: the pre-#539 three (``DEPENDS_ON`` / ``HOSTED_ON`` / ``CONNECTS_TO``)
#: plus the four new types introduced or filtered by the chained PRs:
#:
#: - ``CONNECTED_VIA`` — PhysicalLink, status-gated (PR2)
#: - ``MANAGES`` / ``USES`` / ``PROVIDES`` — default-propagate (PR3)
#: - ``CONNECTS_TO`` — receives a ``medium`` predicate (PR4)
SUPPORTED_TRAVERSAL_RELATIONSHIP_TYPES: Final = frozenset({
    "DEPENDS_ON",
    "HOSTED_ON",
    "CONNECTS_TO",
    "CONNECTED_VIA",
    "MANAGES",
    "USES",
    "PROVIDES",
})

#: Relationships that the pre-#539 traversal walks. Matches the existing
#: 3-of-6 behavior in ``backend/repositories/topology_repo.py``. PR1 does
#: NOT change this; PR2/3/4 extend it.
CURRENT_TRAVERSAL_RELATIONSHIP_TYPES: Final = frozenset({
    "DEPENDS_ON",
    "HOSTED_ON",
    "CONNECTS_TO",
})

# ---------------------------------------------------------------------------
# Feature-flag names (for the rollout plan recorded in decision #6)
# ---------------------------------------------------------------------------

#: Feature flag for PR2 (CONNECTED_VIA + status gate). Default off until
#: PR2 lands and CI is green; flip to ``true`` to enable in production.
FEATURE_FLAG_PHYSICAL_LINK_CORRELATION: Final = (
    "FEATURE_CMDB_CORRELATION_PHYSICAL_LINK_PROPAGATION_ENABLED"
)
#: Feature flag for PR3 (MANAGES/USES/PROVIDES). Default off until PR3
#: lands and CI is green.
FEATURE_FLAG_MANAGES_USES_PROVIDES_CORRELATION: Final = (
    "FEATURE_CMDB_CORRELATION_MANAGES_USES_PROVIDES_ENABLED"
)
#: Feature flag for PR4 (CONNECTS_TO medium predicate). Default off until
#: PR4 lands and CI is green.
FEATURE_FLAG_CONNECTS_TO_MEDIUM_FILTER: Final = (
    "FEATURE_CMDB_CORRELATION_CONNECTS_TO_MEDIUM_FILTER_ENABLED"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def should_propagate_unknown_severity_degrade() -> bool:
    """Decision 1: whether UNKNOWN status degrades severity on propagation.

    Used by the severity-mapping layer (PR2) to decide whether to demote a
    propagated event to ``WARNING``.
    """
    return PHYSICAL_LINK_UNKNOWN_PROPAGATION == "degrade_severity_and_propagate"


def should_re_query_status_per_correlation() -> bool:
    """Decision 2: whether the traversal re-queries PhysicalLink.status.

    Used by the Cypher builder (PR2) to decide whether to inline a
    status-fetch sub-query in the traversal.
    """
    return PHYSICAL_LINK_STATUS_FRESHNESS == "re_query_per_correlation"


def should_generate_descendant_event_on_down() -> bool:
    """Decision 3: whether DOWN generates a descendant event on the endpoints.

    Used by the polling integration (slice 4 / #443) to decide whether a
    UP -> DOWN transition triggers a new event.
    """
    return PHYSICAL_LINK_DOWN_BEHAVIOR == "generate_descendant_event"


def should_default_propagate_manages_uses_provides() -> bool:
    """Decision 4: whether MANAGES / USES / PROVIDES propagate by default.

    Used by the traversal builder (PR3) to decide whether the three types
    are added unconditionally or gated by a flag.
    """
    return MANAGES_USES_PROVIDES_DEFAULT == "all_propagate"


def all_locked_values() -> dict[str, str]:
    """Return a snapshot of the four locked values for logging and diagnostics.

    Useful for log lines, support bundles, and the OpenSpec deltas that the
    chained PRs introduce.
    """
    return {
        "physical_link_unknown_propagation": PHYSICAL_LINK_UNKNOWN_PROPAGATION,
        "physical_link_status_freshness": PHYSICAL_LINK_STATUS_FRESHNESS,
        "physical_link_down_behavior": PHYSICAL_LINK_DOWN_BEHAVIOR,
        "manages_uses_provides_default": MANAGES_USES_PROVIDES_DEFAULT,
    }
