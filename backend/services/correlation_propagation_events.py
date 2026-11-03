"""Shared degraded ``PROPAGATED`` child policy for issue #539.

Locked decision #1 of issue #539 (the degrade-and-propagate decision): a
correlation that crosses a PhysicalLink whose status is ``UNKNOWN`` still
propagates, but the propagated Event is materialized at ``WARNING`` severity
instead of the parent's severity, so the operator sees the degradation
explicitly. The ROOT Event keeps its own severity and the child's
``root_cause_ci_id`` keeps pointing at the ROOT CI — never at the PhysicalLink.

Three writers can materialize that Event, and this module is the ONE
implementation of the decision they all share:

* ``engines/snmp_worker.py``   — the modern SNMP worker (a SEPARATE child);
* ``services/snmp_service.py`` — the legacy SNMP path;
* ``polling/event_writer.py``  — the leased / queued writer.

The module has NO I/O and NO Cypher. It owns the decision — does this crossing
degrade the severity, at which severity, and which markers does the child
carry — while the Event write itself stays in each writer, because the three
writers have different Event semantics and because the event-writer registry
guard (``tests/test_event_writer_lock_guard.py``) classifies every production
module that creates ``:Event`` nodes.

The values themselves live in
:mod:`services.correlation_propagation_contract`, which is the single owner
of the decision string, the degrading status and the degradation reason.
"""

from __future__ import annotations

from typing import Any

from services import correlation_propagation_contract
from services.correlation_propagation_contract import (
    DEGRADED_PROPAGATED_REASON,
    DEGRADED_PROPAGATED_SEVERITY,
    DEGRADING_PHYSICAL_LINK_STATUS,
)

__all__ = [
    "DEGRADED_PROPAGATED_REASON",
    "DEGRADED_PROPAGATED_SEVERITY",
    "DEGRADING_PHYSICAL_LINK_STATUS",
    "build_degraded_propagated_message",
    "degraded_propagated_markers",
    "degrades_propagated_severity",
]


def degrades_propagated_severity(link_status: Any) -> bool:
    """Return True when the crossed PhysicalLink degrades the child severity.

    The policy is read from
    :mod:`services.correlation_propagation_contract` — the decision string
    never appears in this module and never in a writer. The degrading status
    must also belong to the propagating status set published by the contract,
    so a status that blocks the crossing can never reach the severity layer.
    """
    if not link_status:
        return False
    if not correlation_propagation_contract.should_propagate_unknown_severity_degrade():
        return False
    status = str(link_status).strip().upper()
    if status != DEGRADING_PHYSICAL_LINK_STATUS:
        return False
    return status in correlation_propagation_contract.propagating_physical_link_statuses()


def build_degraded_propagated_message(row: Any) -> str:
    """Return the operator-facing message of a degraded propagated child.

    ``row`` is the writer's own event row; only ``message`` and ``link_id``
    are read, so every writer produces the same wording.
    """
    base = str(_row_value(row, "message") or "").strip()
    link_id = str(_row_value(row, "link_id") or "").strip() or "unknown"
    suffix = (
        f"Propagation degraded to {DEGRADED_PROPAGATED_SEVERITY}: "
        f"PhysicalLink {link_id} status is {DEGRADING_PHYSICAL_LINK_STATUS}"
    )
    return f"{base} ({suffix})" if base else suffix


def degraded_propagated_markers(link_id: Any, link_status: Any = None) -> dict[str, Any]:
    """Return the four degradation markers a degraded child carries.

    The marker names are the Neo4j property names the operator feed already
    exposes (``severity_degraded``, ``degradation_reason``,
    ``physical_link_id``, ``physical_link_status``). ``physical_link_status``
    reports the status of the link that was actually crossed; only the
    contract's degrading status can reach this function, so it falls back to
    that constant when the caller has no status to report.
    """
    status = str(link_status or "").strip().upper() or DEGRADING_PHYSICAL_LINK_STATUS
    return {
        "severity_degraded": True,
        "degradation_reason": DEGRADED_PROPAGATED_REASON,
        "physical_link_id": link_id,
        "physical_link_status": status,
    }


def _row_value(row: Any, key: str) -> Any:
    """Read ``key`` from a mapping-like or attribute-like event row."""
    if row is None:
        return None
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key)
    return getattr(row, key, None)
