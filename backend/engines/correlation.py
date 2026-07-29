"""Pure correlation helpers for the external SNMP worker (fix #416, P0).

This module is intentionally side-effect free and contains no Neo4j I/O. Its
responsibilities are limited to:

- ``cycle_root_candidates``: select the (ci_id, metric_id, event_type) tuples
  that the worker must materialize as ROOT Events before any dependent
  ``PROPAGATED`` row can be resolved.
- ``materialize_current_cycle_roots``: orchestrate one ROOT-write pass for the
  selected candidates, delegating to the existing ``_refresh_*`` helpers with
  an empty cache so every row follows ROOT semantics.
- ``attach_dependents_to_roots``: rebuild the open-parent index from the
  just-persisted ROOTs and route the dependents through the existing
  ``_update_propagated_root_events`` idempotent enrichment path.

All three helpers stay within the strict TDD contract:

- No module-level mutable state.
- No Neo4j queries in this file (all queries live in ``snmp_worker.py`` or
  ``topology_repo.py``).
- Single SQLAlchemy session ownership is preserved at the call site (Pass 2
  and Pass 3 share ``poll_snmp``'s ``session``/``db``).
"""

from __future__ import annotations

from typing import Any, Callable


# Event-type constants used by the existing ``_refresh_*`` helpers. Importing
# them from the canonical location keeps the materializer in lockstep with
# ``snmp_worker.py`` if the lifecycle module ever renames a constant.
EVENT_TYPE_AVAILABILITY = "AVAILABILITY"
EVENT_TYPE_COLLECTION_FAILURE = "COLLECTION_FAILURE"
EVENT_TYPE_THRESHOLD_BREACH = "THRESHOLD_BREACH"


def cycle_root_candidates(
    observations: list[dict[str, Any]],
    topology_index: dict[tuple[str, str], dict[str, Any]] | None,
) -> set[tuple[str, str, str]]:
    """Return the (ci_id, metric_id, event_type) tuples that must be ROOT.

    Pure helper — no I/O, no global state, no module-level caching. The
    function is order-independent (a ``set`` is built without iterating
    order). It is invoked from the same-cycle correlation pass in
    ``snmp_worker.poll_snmp``.

    Args:
        observations: list of event-producing observation rows from the
            current cycle. Each row must expose at least ``node_id``,
            ``metric_id`` and ``event_type``. Rows whose ``event_type`` is
            ``None`` or empty are not event-producing and are skipped.
        topology_index: the per-cycle ``build_open_parent_index`` cache, or
            ``None`` when the kill-switch is off or the cache build failed.
            A non-dict value (defensive — mirrors the ``_resolve_correlation``
            contract) is treated as empty so the helper never raises.

    Returns:
        Set of ``(ci_id, metric_id, event_type)`` tuples that are missing
        from ``topology_index`` and therefore must be materialized as ROOT
        Events before the dependent-attachment pass. Malformed rows (missing
        ``node_id`` or ``metric_id``) are dropped because they cannot form a
        valid cache key.
    """
    candidates: set[tuple[str, str, str]] = set()

    # Defensive: a malformed cache (None, wrong type, etc.) must NEVER break
    # the write path. We mirror the resilience contract already established by
    # ``_resolve_correlation``: degrade to all-ROOT.
    safe_index: dict[tuple[str, str], dict[str, Any]]
    if isinstance(topology_index, dict):
        safe_index = topology_index
    else:
        safe_index = {}

    for row in observations:
        node_id = row.get("node_id")
        metric_id = row.get("metric_id")
        event_type = row.get("event_type")
        # Rows without an event_type are not event-producing — skip them.
        if not event_type:
            continue
        # Rows missing node_id or metric_id cannot form a cache key — skip.
        if not node_id or not metric_id:
            continue
        # Cache hit ⇒ the row will resolve to PROPAGATED via the existing
        # _refresh_* path; do not include it as a ROOT candidate.
        if (node_id, metric_id) in safe_index:
            continue
        candidates.add((node_id, metric_id, event_type))

    return candidates
