"""One-shot backfill for stuck ICMP-jitter and ICMP-packet-loss Event rows.

PR #3 of chore-events-backfill-stuck-icmp-recovery-486: ships the
``--execute`` and ``--rollback`` modes. PR #2 added the ``--dry-run``
inventory; this module unifies the three modes behind one CLI.

Public API:

* :func:`inventory_buckets` — four read-only Neo4j queries returning
  bucket counts.
* :func:`capture_ci_snapshot` — single Neo4j query producing the
  ``{ci_id: latest_availability}`` map.
* :func:`dry_run` — captures the snapshot once, then runs the four
  bucket queries. Issues no ``SET`` or ``DELETE`` clauses.
* :func:`select_cascade_targets` — pre-mutation read returning
  per-event pre-state for the snapshot.
* :func:`select_legacy_nulls` — pre-mutation read of legacy
  NULL-discriminator events.
* :func:`cascade_root_events` — cascade mutation of ROOT events and
  their PROPAGATED descendants via the ICMP direct-child predicate.
* :func:`close_legacy_nulls` — conservative closure of legacy
  NULL-discriminator events as ``event_type='legacy-no-relevant'``.
* :func:`execute_cascade` — orchestrates the cascade. Writes the
  snapshot before any mutation.
* :func:`rollback` — replays the snapshot to undo the cascade.
* :func:`build_parser` — argparse factory.

Importing this module does NOT touch Neo4j. The unit-test surface runs
without a live DB.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Metric IDs mirror those in ``backend/polling/icmp_measurements.py``.
ICMP_JITTER_METRIC_ID = "icmp_jitter_ms"
ICMP_PACKET_LOSS_METRIC_ID = "packet_loss_pct"

ICMP_METRIC_IDS = (ICMP_JITTER_METRIC_ID, ICMP_PACKET_LOSS_METRIC_ID)

# The PR #432 merge date. Legacy NULL-discriminator events opened before
# this date are conservatively closed as ``event_type='legacy-no-relevant'``.
LEGACY_NULL_CUTOFF_ISO = "2026-08-28T00:00:00Z"


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
# has value=0). Cascade targets.
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
  AND NOT EXISTS {
    MATCH (:CI {id: e.ci_id})
  }
RETURN count(e) AS count
"""

# Pre-mutation read: PROPAGATED descendants of cascade-target ROOTs that
# will be cascade-recovered. Mirrors the inner CALL block of
# ``_QUERY_CASCADE_ROOT``. Used to include these rows in the apply-progress
# snapshot so ``--rollback`` can restore them.
_QUERY_SELECT_PROPAGATED_CASCADE_TARGETS = """
MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
WHERE pe.propagated_from IN $root_event_ids
  AND pe.root_cause_ci_id IN $root_ci_ids
  AND pe.correlation_type = 'PROPAGATED'
  AND pe.status IN ['OPEN', 'ACK']
  AND coalesce(m.can_propagate, true) = true
RETURN pe.id AS event_id,
       pe.ci_id AS ci_id,
       pe.metric_id AS metric_id,
       pe.status AS status,
       pe.recovered_at AS recovered_at,
       pe.event_type AS event_type
"""

# CI availability snapshot. Captures the latest sample per CI in a single
# query so the cascade makes decisions against a frozen state.
_QUERY_CI_SNAPSHOT = """
MATCH (ci:CI)
OPTIONAL MATCH (ci)-[:HAS_AVAILABILITY_SAMPLE]->(s)
WITH ci, s
ORDER BY s.collected_at DESC
WITH ci, head(collect(s)) AS latest
WHERE latest IS NOT NULL
RETURN ci.id AS ci_id, latest.value AS latest_value
"""

# Pre-mutation read: events that will be cascade targets. Bucket is
# re-determined inline so the cascade query can re-filter idempotently.
#
# Buckets:
#   - 'deleted_ci'   — the CI is gone from the CMDB.
#   - 'down_ci'     — the CI exists AND has a recent availability=0 sample.
#   - NULL          — the CI is UP. Not a cascade target; natural recovery
#                     will close the event when the next OK sample arrives.
#
# The bucket = NULL branch is filtered out by ``WHERE bucket IS NOT NULL``
# so events on UP CIs are NOT included in the cascade.
_QUERY_SELECT_CASCADE_TARGETS = """
MATCH (e:Event)
WHERE e.status IN ['OPEN', 'ACK']
  AND e.metric_id IN $icmp_metric_ids
  AND e.event_type = 'THRESHOLD_BREACH'
  AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
WITH e,
     CASE
       WHEN NOT EXISTS {
         MATCH (:CI {id: e.ci_id})
       } THEN 'deleted_ci'
       WHEN EXISTS {
         MATCH (:CI {id: e.ci_id})-[:HAS_AVAILABILITY_SAMPLE]->(s)
         WHERE s.value = 0
       } THEN 'down_ci'
       ELSE NULL
     END AS bucket
WHERE bucket IS NOT NULL
RETURN e.id AS event_id,
       e.ci_id AS ci_id,
       e.metric_id AS metric_id,
       bucket,
       e.status AS status,
       e.recovered_at AS recovered_at,
       e.event_type AS event_type
"""

# Pre-mutation read: legacy NULL-discriminator events opened before the
# PR #432 merge date. Closed as 'legacy-no-relevant'.
_QUERY_SELECT_LEGACY_NULLS = """
MATCH (e:Event)
WHERE e.status IN ['OPEN', 'ACK']
  AND e.metric_id IN $icmp_metric_ids
  AND (e.event_type IS NULL OR e.metric_id IS NULL)
  AND e.opened_at < datetime($cutoff)
RETURN e.id AS event_id,
       e.ci_id AS ci_id,
       e.metric_id AS metric_id,
       e.status AS status,
       e.recovered_at AS recovered_at,
       e.event_type AS event_type
"""

# Cascade: ROOT + PROPAGATED via the ICMP direct-child predicate (NOT the
# SNMP full-cascade). Mirrors _recover_icmp_jitter_events /
# _recover_icmp_packet_loss_events in backend/engines/snmp_worker.py.
_QUERY_CASCADE_ROOT = """
UNWIND $event_ids AS event_id
MATCH (e:Event {id: event_id})
WHERE e.status IN ['OPEN', 'ACK']
  AND e.event_type = 'THRESHOLD_BREACH'
  AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
SET e.status = 'RECOVERED',
    e.recovered_at = datetime(),
    e.recovery_source = 'backfill',
    e.backfill_origin = 'chore-events-backfill-486-cascade'
WITH e
CALL {
    WITH e
    MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
    WHERE pe.propagated_from = e.id
      AND pe.root_cause_ci_id = e.ci_id
      AND pe.correlation_type = 'PROPAGATED'
      AND pe.status IN ['OPEN', 'ACK']
      AND coalesce(m.can_propagate, true) = true
    SET pe.status = 'RECOVERED',
        pe.recovered_at = datetime(),
        pe.recovery_source = 'backfill',
        pe.backfill_origin = 'chore-events-backfill-486-cascade'
    RETURN count(pe) AS propagated_recovered
}
RETURN e
"""

# Cascade: legacy NULL-discriminator closure. Sets event_type to
# 'legacy-no-relevant' and the dedicated audit marker.
_QUERY_CLOSE_LEGACY_NULLS = """
UNWIND $event_ids AS event_id
MATCH (e:Event {id: event_id})
WHERE e.status IN ['OPEN', 'ACK']
  AND (e.event_type IS NULL OR e.metric_id IS NULL)
SET e.event_type = 'legacy-no-relevant',
    e.status = 'RECOVERED',
    e.recovered_at = datetime(),
    e.recovery_source = 'backfill',
    e.backfill_origin = 'chore-events-backfill-486-legacy-null-discriminator',
    e.message = coalesce(e.message, '') +
        ' [closed by chore-events-backfill-486-legacy-null-discriminator on ' +
        toString(datetime()) + ']'
RETURN e
"""

# Rollback: replay the snapshot. Self-bounded by backfill_origin IS NOT NULL.
_QUERY_ROLLBACK = """
UNWIND $rows AS row
MATCH (e:Event {id: row.event_id})
WHERE e.backfill_origin IS NOT NULL
SET e.status = row.status_pre,
    e.recovered_at = row.recovered_at_pre,
    e.event_type = row.event_type_pre,
    e.backfill_origin = NULL,
    e.recovery_source = NULL
RETURN count(e) AS rolled_back
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
    """ArgumentParser that rejects ``--execute``/``--rollback`` without ``--confirm-target``."""

    def parse_args(self, args=None, namespace=None):  # type: ignore[override]
        ns = super().parse_args(args, namespace)
        if getattr(ns, "execute", False) and not getattr(ns, "confirm_target", None):
            self.error(
                "--execute requires --confirm-target=<env> "
                "(BACKFILL_ALLOWED_TARGETS must be set in the env)"
            )
        if getattr(ns, "rollback", False) and not getattr(ns, "confirm_target", None):
            self.error(
                "--rollback requires --confirm-target=<env> "
                "(BACKFILL_ALLOWED_TARGETS must be set in the env)"
            )
        return ns


def capture_ci_snapshot(session) -> dict[str, float]:
    """Capture a frozen ``{ci_id: latest_availability}`` map in one query."""
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
    """Run the dry-run inventory and return a structured report."""
    snapshot = capture_ci_snapshot(session)
    buckets = inventory_buckets(session)
    return {
        "mode": "dry-run",
        "buckets": buckets,
        "ci_snapshot": snapshot,
        "ran_at": datetime.now(UTC).isoformat(),
    }


def select_cascade_targets(session) -> list[dict]:
    """Pre-mutation read returning one record per cascade-target event.

    Cascade targets are ROOT events whose CI is currently DOWN or whose
    CI has been deleted from the CMDB. Bucket classification is
    re-determined inline so the cascade query can re-filter idempotently.
    """
    result = session.run(_QUERY_SELECT_CASCADE_TARGETS, icmp_metric_ids=ICMP_METRIC_IDS)
    targets = []
    for record in result:
        targets.append(
            {
                "event_id": record["event_id"],
                "ci_id": record["ci_id"],
                "metric_id": record["metric_id"],
                "bucket": record["bucket"],
                "status_pre": record["status"],
                "recovered_at_pre": record["recovered_at"],
                "event_type_pre": record["event_type"],
            }
        )
    return targets


def select_propagated_cascade_targets(
    session, root_event_ids: list, root_ci_ids: list
) -> list[dict]:
    """Pre-mutation read of PROPAGATED descendants that the cascade will
    recover. Mirrors the inner CALL block predicate of
    ``_QUERY_CASCADE_ROOT``.

    Including these rows in ``apply-progress.json`` is what makes
    ``--rollback`` restore the PROPAGATED mutations; without it, the
    snapshot would only contain ROOT rows and the PROPAGATED events
    would stay RECOVERED after rollback.
    """
    if not root_event_ids:
        return []
    result = session.run(
        _QUERY_SELECT_PROPAGATED_CASCADE_TARGETS,
        root_event_ids=list(root_event_ids),
        root_ci_ids=list(root_ci_ids),
    )
    return [
        {
            "event_id": record["event_id"],
            "ci_id": record["ci_id"],
            "metric_id": record["metric_id"],
            "bucket": "propagated_cascade",
            "status_pre": record["status"],
            "recovered_at_pre": _isoformat_or_none(record["recovered_at"]),
            "event_type_pre": record["event_type"],
        }
        for record in result
    ]


def select_legacy_nulls(session) -> list[dict]:
    """Pre-mutation read of legacy NULL-discriminator events.

    Limited to events opened before the PR #432 merge date so newer
    NULL-discriminator rows (which should be rare after #432) are not
    silently closed.
    """
    result = session.run(
        _QUERY_SELECT_LEGACY_NULLS,
        icmp_metric_ids=ICMP_METRIC_IDS,
        cutoff=LEGACY_NULL_CUTOFF_ISO,
    )
    return [
        {
            "event_id": record["event_id"],
            "ci_id": record["ci_id"],
            "metric_id": record["metric_id"],
            "bucket": "null_discriminator",
            "status_pre": record["status"],
            "recovered_at_pre": record["recovered_at"],
            "event_type_pre": record["event_type"],
        }
        for record in result
    ]


def cascade_root_events(session, event_ids: list) -> int:
    """Cascade ROOT events and their PROPAGATED descendants.

    The predicate mirrors ``_recover_icmp_*_events``:
    ``propagated_from = e.id AND root_cause_ci_id = e.ci_id AND
    correlation_type = 'PROPAGATED' AND can_propagate``. Does NOT use
    the SNMP full-cascade predicate (``root_cause_ci_id = e.ci_id``),
    preserving the deliberate ICMP-direct-child asymmetry.

    Both the ROOT and PROPAGATED branches are gated by
    ``status IN ['OPEN', 'ACK']``, so re-running after a partial
    completion is a no-op.
    """
    if not event_ids:
        return 0
    session.run(_QUERY_CASCADE_ROOT, event_ids=list(event_ids))
    return len(event_ids)


def close_legacy_nulls(session, event_ids: list) -> int:
    """Conservative closure of legacy NULL-discriminator events.

    Sets ``event_type = 'legacy-no-relevant'`` (a new value introduced
    by this change), ``status = 'RECOVERED'``, ``recovered_at`` to the
    run timestamp, and the dedicated audit marker. Preserves
    ``metric_name``, ``ci_id``, ``severity``, and the original ``message``
    (the original message is preserved via ``coalesce(e.message, '')``
    on the RHS of the concatenation).
    """
    if not event_ids:
        return 0
    session.run(_QUERY_CLOSE_LEGACY_NULLS, event_ids=list(event_ids))
    return len(event_ids)


def _write_snapshot(
    snapshot_path: str,
    cascade_targets: list[dict],
    propagated_targets: list[dict],
    legacy_nulls: list[dict],
    confirm_target: str,
) -> None:
    """Write the apply-progress snapshot to disk atomically.

    The snapshot is the rollback anchor: it MUST exist before any
    mutation. Atomic write (temp + rename) guarantees no partial file
    is left behind if the write is interrupted.

    Includes three row groups so ``--rollback`` restores every mutated row:
      - ``cascade_targets`` (ROOT events in down_ci / deleted_ci bucket)
      - ``propagated_targets`` (PROPAGATED descendants of those ROOTs)
      - ``legacy_nulls`` (legacy NULL-discriminator events)
    """
    rows = []
    for t in cascade_targets:
        rows.append(
            {
                "event_id": t["event_id"],
                "ci_id": t["ci_id"],
                "metric_id": t["metric_id"],
                "bucket": t["bucket"],
                "status_pre": t["status_pre"],
                "recovered_at_pre": _isoformat_or_none(t["recovered_at_pre"]),
                "event_type_pre": t["event_type_pre"],
            }
        )
    for p in propagated_targets:
        rows.append(
            {
                "event_id": p["event_id"],
                "ci_id": p["ci_id"],
                "metric_id": p["metric_id"],
                "bucket": "propagated_cascade",
                "status_pre": p["status_pre"],
                "recovered_at_pre": _isoformat_or_none(p["recovered_at_pre"]),
                "event_type_pre": p["event_type_pre"],
            }
        )
    for n in legacy_nulls:
        rows.append(
            {
                "event_id": n["event_id"],
                "ci_id": n["ci_id"],
                "metric_id": n["metric_id"],
                "bucket": "null_discriminator",
                "status_pre": n["status_pre"],
                "recovered_at_pre": _isoformat_or_none(n["recovered_at_pre"]),
                "event_type_pre": n["event_type_pre"],
            }
        )
    snapshot = {
        "run_id": str(uuid.uuid4()),
        "run_at": datetime.now(UTC).isoformat(),
        "confirm_target": confirm_target,
        "ci_snapshot_at": datetime.now(UTC).isoformat(),
        "rows": rows,
    }
    target = Path(snapshot_path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2, default=str))
    os.replace(tmp, target)


def _isoformat_or_none(value):
    """Best-effort ISO formatting for Neo4j DateTime values."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def execute_cascade(session, snapshot_path: str, confirm_target: str) -> dict:
    """Run the cascade. Returns a structured report.

    Flow:
      1. ``select_cascade_targets`` — read ROOT cascade targets.
      2. ``select_propagated_cascade_targets`` — read PROPAGATED descendants
         of those ROOTs so they can be included in the snapshot.
      3. ``select_legacy_nulls`` — read legacy NULL-discriminator events.
      4. ``_write_snapshot`` — write ``apply-progress.json`` atomically,
         including ROOT + PROPAGATED + legacy rows so rollback restores all.
      5. ``cascade_root_events`` — cascade ROOT + PROPAGATED.
      6. ``close_legacy_nulls`` — close legacy NULL events.
      7. Return the report dict.
    """
    cascade_targets = select_cascade_targets(session)
    legacy_nulls = select_legacy_nulls(session)
    propagated_targets = select_propagated_cascade_targets(
        session,
        [t["event_id"] for t in cascade_targets],
        [t["ci_id"] for t in cascade_targets],
    )

    # Step 4: snapshot BEFORE any mutation. All three row groups must be
    # included so --rollback restores PROPAGATED mutations and legacy
    # event_type restorations.
    _write_snapshot(
        snapshot_path, cascade_targets, propagated_targets, legacy_nulls, confirm_target
    )

    # Step 5: cascade ROOT + PROPAGATED.
    cascade_root_events(session, [t["event_id"] for t in cascade_targets])

    # Step 6: close legacy NULLs.
    close_legacy_nulls(session, [n["event_id"] for n in legacy_nulls])

    return {
        "mode": "execute",
        "cascade_root_count": len(cascade_targets),
        "cascade_propagated_count": len(propagated_targets),
        "legacy_null_count": len(legacy_nulls),
        "snapshot_path": str(snapshot_path),
        "confirm_target": confirm_target,
        "ran_at": datetime.now(UTC).isoformat(),
    }


def rollback(session, snapshot_path: str, confirm_target: str) -> dict:
    """Replay the snapshot to undo the cascade.

    Self-bounded by ``backfill_origin IS NOT NULL`` so a double-rollback
    is a no-op (rows whose audit marker was already cleared are
    rejected by the WHERE clause).
    """
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    rows = snapshot.get("rows", [])
    if not rows:
        return {
            "mode": "rollback",
            "rolled_back": 0,
            "snapshot_path": str(snapshot_path),
            "confirm_target": confirm_target,
            "ran_at": datetime.now(UTC).isoformat(),
        }
    result = session.run(_QUERY_ROLLBACK, rows=rows)
    rolled_back = 0
    try:
        single = result.single()
        if single is not None:
            rolled_back = single["rolled_back"]
    except (StopIteration, KeyError):
        rolled_back = 0
    return {
        "mode": "rollback",
        "rolled_back": rolled_back,
        "snapshot_path": str(snapshot_path),
        "confirm_target": confirm_target,
        "ran_at": datetime.now(UTC).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the CLI surface.

    ``--dry-run`` does not require ``--confirm-target`` (read-only).
    ``--execute`` and ``--rollback`` both require ``--confirm-target``
    matching ``BACKFILL_ALLOWED_TARGETS``. ``--rollback`` also requires
    ``--output=<snapshot.json>`` to identify the snapshot to replay.
    """
    parser = _ExecuteRequiresConfirm(
        prog="backfill_stuck_icmp_events",
        description=(
            "One-shot backfill for stuck ICMP-jitter and ICMP-packet-loss "
            "Event rows. --dry-run is read-only; --execute and --rollback "
            "require --confirm-target."
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
        help="Run the cascade. Requires --confirm-target.",
    )
    mode.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback from a snapshot file. Requires --confirm-target and --output=<snapshot>.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write the report (--dry-run/--execute) or read the snapshot (--rollback) from this path.",
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


def _main(argv=None):
    """CLI entry point. Lazy-imports the Neo4j driver to keep module importable without it.

    Accepts ``argv`` for testability; falls back to ``sys.argv[1:]`` when None.
    """
    import sys as _sys

    args = build_parser().parse_args(argv if argv is not None else _sys.argv[1:])

    # Lazy import: keeps the module importable in test contexts that stub
    # the neo4j module via conftest.
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            if args.dry_run:
                report = dry_run(session)
            elif args.execute:
                snapshot_path = (
                    args.output or f"apply-progress-{datetime.now(UTC).isoformat()}.json"
                )
                report = execute_cascade(session, snapshot_path, args.confirm_target)
            elif args.rollback:
                if not args.output:
                    raise SystemExit("--rollback requires --output=<snapshot.json>")
                report = rollback(session, args.output, args.confirm_target)
            else:
                raise SystemExit("No mode selected; use --dry-run, --execute, or --rollback")

            serialized = json.dumps(report, indent=2, default=str)
            if args.dry_run and args.output:
                Path(args.output).write_text(serialized)
            else:
                print(serialized)
    finally:
        driver.close()


if __name__ == "__main__":
    _main()
