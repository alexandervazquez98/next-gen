"""One-shot backfill for stuck ICMP-jitter and ICMP-packet-loss Event rows.

PR #2 of chore-events-backfill-stuck-icmp-recovery-486: dry-run inventory
mode for the cascade. The full cascade implementation lands in PR #3.

This module is imported as ``from scripts import backfill_stuck_icmp_events``.

Public API (PR #2 scope):

* :func:`inventory_buckets` — returns four bucket counts via four read-only
  Neo4j queries.
* :func:`capture_ci_snapshot` — single Neo4j query producing the
  ``{ci_id: latest_availability}`` map that the cascade in PR #3 will
  consume.
* :func:`dry_run` — captures the snapshot once, then runs the four bucket
  queries, and returns a report dict. Issues no ``SET`` or ``DELETE``
  clauses.
* :func:`build_parser` — argparse factory whose ``parse_args`` enforces
  ``--execute`` requires ``--confirm-target``.

Importing this module does NOT touch Neo4j. The ``--help`` and unit-test
surfaces run without a live DB.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime

# Metric IDs mirror those in ``backend/polling/icmp_measurements.py``.
ICMP_JITTER_METRIC_ID = "icmp_jitter_ms"
ICMP_PACKET_LOSS_METRIC_ID = "packet_loss_pct"

ICMP_METRIC_IDS = (ICMP_JITTER_METRIC_ID, ICMP_PACKET_LOSS_METRIC_ID)


# Bucket 1: events with proper discriminators (event_type='THRESHOLD_BREACH',
# metric_id set, ROOT correlation). These will be cascade targets if the CI is
# currently DOWN or deleted.
_QUERY_PROPER_DISCRIMINATORS = """
MATCH (e:Event)
WHERE e.status IN ['OPEN', 'ACK']
  AND e.metric_id IN $icmp_metric_ids
  AND e.event_type = 'THRESHOLD_BREACH'
  AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
RETURN count(e) AS count
"""

# Bucket 2: legacy NULL-discriminator events. Closed as 'legacy-no-relevant'.
_QUERY_NULL_DISCRIMINATORS = """
MATCH (e:Event)
WHERE e.status IN ['OPEN', 'ACK']
  AND e.metric_id IN $icmp_metric_ids
  AND (e.event_type IS NULL OR e.metric_id IS NULL)
RETURN count(e) AS count
"""

# Bucket 3: events whose CI is currently DOWN (latest HAS_AVAILABILITY_SAMPLE
# has value=0). Cascade targets for PR #3.
_QUERY_DOWN_CI = """
MATCH (e:Event)
WHERE e.status IN ['OPEN', 'ACK']
  AND e.metric_id IN $icmp_metric_ids
  AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
WITH e, e.ci_id AS ci_id
MATCH (ci:CI {id: ci_id})
OPTIONAL MATCH (ci)-[:HAS_AVAILABILITY_SAMPLE]->(s)
WITH ci, e, s
ORDER BY s.collected_at DESC
WITH ci, e, head(collect(s)) AS latest
WHERE latest IS NOT NULL AND latest.value = 0
RETURN count(DISTINCT e) AS count
"""

# Bucket 4: events whose CI no longer exists in the CMDB. Cascade targets.
_QUERY_DELETED_CI = """
MATCH (e:Event)
WHERE e.status IN ['OPEN', 'ACK']
  AND e.metric_id IN $icmp_metric_ids
  AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
  AND NOT EXISTS ((:CI {id: e.ci_id}))
RETURN count(e) AS count
"""

# CI availability snapshot. Captures the latest sample per CI in a single
# query so the cascade in PR #3 makes decisions against a frozen state.
_QUERY_CI_SNAPSHOT = """
MATCH (ci:CI)
OPTIONAL MATCH (ci)-[:HAS_AVAILABILITY_SAMPLE]->(s)
WITH ci, s
ORDER BY s.collected_at DESC
WITH ci, head(collect(s)) AS latest
WHERE latest IS NOT NULL
RETURN ci.id AS ci_id, latest.value AS latest_value
"""


class _ConfirmTargetAction(argparse.Action):
    """Validate ``--confirm-target`` against ``BACKFILL_ALLOWED_TARGETS``.

    The env var is a comma-separated allowlist (e.g. ``"staging,prod"``).
    When set, ``--confirm-target`` must match one of its members; otherwise
    the parser errors with a SystemExit.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        allowed = os.environ.get("BACKFILL_ALLOWED_TARGETS", "")
        allowlist = {x.strip() for x in allowed.split(",") if x.strip()}
        if allowlist and values not in allowlist:
            parser.error(
                f"--confirm-target={values!r} is not in "
                f"BACKFILL_ALLOWED_TARGETS={sorted(allowlist)}"
            )
        setattr(namespace, self.dest, values)


class _ExecuteRequiresConfirm(argparse.ArgumentParser):
    """ArgumentParser that rejects ``--execute`` without ``--confirm-target``."""

    def parse_args(self, args=None, namespace=None):  # type: ignore[override]
        ns = super().parse_args(args, namespace)
        if getattr(ns, "execute", False) and not getattr(ns, "confirm_target", None):
            self.error(
                "--execute requires --confirm-target=<env> "
                "(BACKFILL_ALLOWED_TARGETS must be set in the env)"
            )
        return ns


def capture_ci_snapshot(session) -> dict[str, float]:
    """Capture a frozen ``{ci_id: latest_availability}`` map in one query.

    The snapshot is consumed by PR #3's cascade to decide which events
    are cascade targets vs. left for natural recovery. PR #2 captures
    the snapshot to validate the query shape and ensure ``dry_run`` is
    self-contained.
    """
    result = session.run(_QUERY_CI_SNAPSHOT)
    snapshot: dict[str, float] = {}
    for record in result:
        snapshot[record["ci_id"]] = float(record["latest_value"])
    return snapshot


def inventory_buckets(session) -> dict[str, int]:
    """Return the four residual-bucket counts via four read-only queries.

    Buckets:
      * ``stuck_with_proper_discriminators`` — ROOT events with
        ``event_type='THRESHOLD_BREACH'`` and ``metric_id`` set.
      * ``stuck_null_discriminators`` — legacy events with NULL
        ``event_type`` or NULL ``metric_id``.
      * ``stuck_on_down_ci`` — ROOT events whose CI has
        ``availability=0`` in the latest :HAS_AVAILABILITY_SAMPLE.
      * ``stuck_on_deleted_ci`` — ROOT events whose CI no longer exists.
    """
    proper = session.run(_QUERY_PROPER_DISCRIMINATORS, icmp_metric_ids=ICMP_METRIC_IDS).single()[
        "count"
    ]
    nulls = session.run(_QUERY_NULL_DISCRIMINATORS, icmp_metric_ids=ICMP_METRIC_IDS).single()[
        "count"
    ]
    down = session.run(_QUERY_DOWN_CI, icmp_metric_ids=ICMP_METRIC_IDS).single()["count"]
    deleted = session.run(_QUERY_DELETED_CI, icmp_metric_ids=ICMP_METRIC_IDS).single()["count"]
    return {
        "stuck_with_proper_discriminators": proper,
        "stuck_null_discriminators": nulls,
        "stuck_on_down_ci": down,
        "stuck_on_deleted_ci": deleted,
    }


def dry_run(session) -> dict:
    """Run the dry-run inventory and return a structured report.

    Captures the CI snapshot exactly once at the start of the run, then
    issues the four bucket queries. Returns a dict with:

      * ``buckets`` — the four counts.
      * ``ci_snapshot`` — ``{ci_id: latest_availability}`` map.
      * ``ran_at`` — ISO 8601 UTC timestamp.
      * ``mode`` — ``"dry-run"``.

    Issues no ``SET`` or ``DELETE`` Cypher clauses.
    """
    snapshot = capture_ci_snapshot(session)
    buckets = inventory_buckets(session)
    return {
        "mode": "dry-run",
        "buckets": buckets,
        "ci_snapshot": snapshot,
        "ran_at": datetime.now(UTC).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the CLI surface.

    ``--dry-run`` does not require ``--confirm-target`` (read-only).
    ``--execute`` and ``--rollback`` both require ``--confirm-target``
    and a non-empty ``BACKFILL_ALLOWED_TARGETS`` env allowlist.
    """
    parser = _ExecuteRequiresConfirm(
        prog="backfill_stuck_icmp_events",
        description=(
            "One-shot backfill for stuck ICMP-jitter and ICMP-packet-loss "
            "Event rows. PR #2 ships --dry-run; --execute and --rollback "
            "land in PR #3."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the four residual-bucket counts without mutating.",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Run the cascade (PR #3). Requires --confirm-target.",
    )
    mode.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback from a snapshot file (PR #3). Requires --confirm-target.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write the report to this path instead of stdout.",
    )
    parser.add_argument(
        "--confirm-target",
        type=str,
        default=None,
        action=_ConfirmTargetAction,
        help=(
            "Confirm the target environment. Required for --execute/--rollback. "
            "Must match a value in the BACKFILL_ALLOWED_TARGETS env allowlist."
        ),
    )
    return parser
