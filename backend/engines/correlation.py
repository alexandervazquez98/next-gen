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

import logging
from typing import Any, Callable


logger = logging.getLogger(__name__)


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


# Event-type → per-family refresh-helper bucket used by materialize. The
# refresh helpers themselves are injected at the call site so this module
# stays Neo4j-free (the helpers live in ``engines.snmp_worker``).
_EVENT_TYPE_FAMILIES: dict[str, str] = {
    EVENT_TYPE_COLLECTION_FAILURE: "collection",
    EVENT_TYPE_AVAILABILITY: "availability",
    EVENT_TYPE_THRESHOLD_BREACH: "latency",
}


def materialize_current_cycle_roots(
    session: Any,
    db: Any,
    candidates: set[tuple[str, str, str]],
    refresh_collection_failures: Callable[..., Any],
    refresh_icmp_availability: Callable[..., Any],
    refresh_icmp_latency: Callable[..., Any],
) -> int:
    """Route ``candidates`` through the existing ``_refresh_*`` helpers with
    ``cache={}`` so every row follows ROOT semantics.

    Pass 2 of the two-pass correlation flow (see design.md AD-3 + AD-7):

    1. Group the candidates by event family (collection / availability /
       latency). Within a family, call the matching refresh helper exactly
       once with the full set of family candidates. Each call passes
       ``cache={}`` — the empty cache forces the helper's
       ``_resolve_correlation`` to tag every row as ROOT (no PROPAGATED
       writes, no child Events).
    2. Share the caller's ``db`` (the SQLAlchemy session opened in
       ``poll_snmp``) so the transaction-scoped ``pg_advisory_xact_lock``
       acquired inside each helper survives Pass 2 → Pass 3 (REQ-007).
    3. Per-helper try/except: a failure in one family is logged and
       skipped, but the other families still receive their candidates
       (REQ-005, SCN-009). The cycle is never aborted.
    4. Unknown event types are logged at WARNING and skipped — a stale
       enum value must never crash the cycle.

    The function does NOT itself run any Cypher. It only orchestrates the
    call into the existing helpers which own the FORACH(CREATE) write path
    (proven dedup, ``poll_collector_id`` fallback, ROOT / PROPAGATED
    discrimination, recovery semantics).

    Args:
        session: the Neo4j session owned by ``poll_snmp``. Forwarded to
            every refresh helper.
        db: the SQLAlchemy session owned by ``poll_snmp``. Forwarded as
            ``lock_db`` to every refresh helper so the Event advisory-lock
            triplet contract is preserved across Pass 2 → Pass 3.
        candidates: set of ``(ci_id, metric_id, event_type)`` tuples that
            must be materialized as ROOT this cycle. Produced by
            ``cycle_root_candidates``.
        refresh_collection_failures: ``_refresh_snmp_collection_failures``.
        refresh_icmp_availability: ``_refresh_icmp_availability_events``.
        refresh_icmp_latency: ``_refresh_icmp_latency_events``.

    Returns:
        Number of candidates that were successfully routed to a refresh
        helper. Failures inside a refresh helper are NOT counted.
    """
    if not candidates:
        return 0

    # Group candidates by family. Order within a family is irrelevant;
    # each helper applies its own dedup.
    by_family: dict[str, list[dict[str, Any]]] = {
        "collection": [],
        "availability": [],
        "latency": [],
    }
    skipped_unknown: list[tuple[str, str, str]] = []
    for ci_id, metric_id, event_type in candidates:
        family = _EVENT_TYPE_FAMILIES.get(event_type)
        if family is None:
            skipped_unknown.append((ci_id, metric_id, event_type))
            continue
        by_family[family].append(
            {
                "node_id": ci_id,
                "metric_id": metric_id,
                "event_type": event_type,
            }
        )

    if skipped_unknown:
        logger.warning(
            "topology_rca_materialize_unknown_event_type skipped=%s",
            skipped_unknown,
        )

    refresh_map = {
        "collection": refresh_collection_failures,
        "availability": refresh_icmp_availability,
        "latency": refresh_icmp_latency,
    }

    materialized = 0
    for family, rows in by_family.items():
        if not rows:
            continue
        try:
            refresh_map[family](session, rows, cache={}, lock_db=db)
            materialized += len(rows)
        except Exception as exc:  # pragma: no cover - defensive
            # REQ-005 / SCN-009: a single family failure must NOT abort the
            # cycle. The other families already received their candidates
            # above; downstream passes will fall back to ROOT naturally
            # because the cache we hand to them is empty.
            logger.error(
                "topology_rca_materialize_family_failed family=%s "
                "candidates=%s error=%s",
                family,
                rows,
                exc,
            )

    return materialized
