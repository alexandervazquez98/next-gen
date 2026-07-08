import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

import schedule
from neo4j import GraphDatabase

# Add root and backend to python path to verify imports work
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(os.path.dirname(__file__), "../backend"))

from config import get_icmp_settings, get_polling_pipeline_settings  # noqa: E402
from polling.icmp_measurements import (  # noqa: E402
    ICMP_AVAILABILITY_METRIC_ID,
    ICMP_LATENCY_METRIC_ID,
    PingMeasurement,
    build_icmp_sidecar_samples,
    coerce_ping_measurement,
    evaluate_latency_status,
    is_icmp_availability_metric,
    is_icmp_telemetry_metric,
    latency_threshold_metadata,
    parse_ping_latency_ms,
)
from postgres_db import SessionLocal  # noqa: E402
from repositories.metric_repo import bulk_insert_metrics  # noqa: E402
from repositories.topology_repo import build_open_parent_index  # noqa: E402
from services.event_lock import POLL_COLLECTOR_ID, acquire_event_triplet_lock  # noqa: E402
from services.neo4j_write_guard import (  # noqa: E402
    is_poll_collector_id_undefined_error,
    run_with_cypher_param_fallback,
)
from services.polling_event_lifecycle import (  # noqa: E402
    EVENT_TYPE_AVAILABILITY,
    EVENT_TYPE_COLLECTION_FAILURE,
    EVENT_TYPE_THRESHOLD_BREACH,
    FAILURE_FAMILY_SNMP_NO_RESPONSE,
    SOURCE_PROTOCOL_ICMP,
    SOURCE_PROTOCOL_SNMP,
    is_snmp_no_response_failure,
    normalized_protocol,
)
from sqlalchemy import text  # noqa: E402

logger = logging.getLogger(__name__)


def configure_worker_runtime_logging() -> None:
    """Configure executable-path logging for the SNMP worker process."""
    logging.basicConfig(level=logging.INFO)
    logging.getLogger().setLevel(logging.INFO)


# poll_collector_id is sourced from services.event_lock.get_poll_collector_id
# (cached at module load from HOSTNAME env var with socket.gethostname()
# fallback) — see services/event_lock.py for the canonical implementation.

# SNMP Support
try:
    from pysnmp.hlapi import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd,
    )

    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False

# Connection
URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

driver = GraphDatabase.driver(URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def verify_connection():
    max_retries = 60
    for i in range(max_retries):
        try:
            driver.verify_connectivity()
            print("Connected to Neo4j!")
            return
        except Exception:
            print(f"Waiting for Neo4j... ({i+1}/{max_retries})")
            time.sleep(2)
    raise Exception("Could not connect to Neo4j after multiple retries")


# Module-level consecutive failure counter for ICMP debounce (keyed by node_id)
# NOTE: This dict grows unbounded. If a node is deleted from Neo4j, its entry remains.
# For production, consider persisting this to Neo4j or using a bounded cache (e.g. LRU).
_consecutive_failures: dict[str, int] = {}


def fetch_icmp_ping_measurement(
    ip: str, timeout_ms: int = 3000, retries: int = 2
) -> PingMeasurement:
    """Perform ICMP ping with configurable timeout and retry.

    Args:
        ip: Target IP address.
        timeout_ms: Timeout per ping attempt in milliseconds.
        retries: Number of additional attempts after initial failure.

    Returns:
        Structured ping availability and latency when parsed.
    """
    attempts = retries + 1
    system = platform.system().lower()

    for attempt in range(attempts):
        try:
            if system == "windows":
                cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
            else:
                timeout_sec = max(1, timeout_ms // 1000)
                cmd = ["ping", "-c", "1", "-W", str(timeout_sec), ip]
            result = subprocess.run(cmd, capture_output=True, text=True)
            output = f"{result.stdout or ''}\n{result.stderr or ''}"
            if result.returncode == 0:
                return PingMeasurement(True, parse_ping_latency_ms(output), raw=output)
        except OSError as e:
            logger.warning(f"Ping attempt {attempt + 1}/{attempts} failed for {ip}: {e}")
            continue
        except subprocess.TimeoutExpired as e:
            logger.warning(f"Ping attempt {attempt + 1}/{attempts} timed out for {ip}: {e}")
            continue
    return PingMeasurement(False, None, raw=None, error="ICMP ping failed")


def fetch_icmp_ping(
    ip: str, timeout_ms: int = 3000, retries: int = 2, include_measurement: bool = False
):
    """Perform ICMP ping and preserve the legacy binary availability contract by default."""
    measurement = fetch_icmp_ping_measurement(ip, timeout_ms=timeout_ms, retries=retries)
    return measurement if include_measurement else measurement.availability_value


def fetch_snmp_value(ip, community, oid, port=161, include_status=False):
    """Perform a real SNMP GET.

    By default this preserves the legacy float/None contract. The active worker
    requests structured status so only real timeout/no-data failures become
    SNMP_NO_RESPONSE collection-failure events.
    """

    def result(value, status, error):
        return (value, status, error) if include_status else value

    if not SNMP_AVAILABLE:
        return result(None, "ERROR", "PySNMP not installed")

    try:
        error_indication, error_status, error_index, var_binds = next(
            getCmd(
                SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((ip, port), timeout=2.0, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
        )

        if error_indication:
            error_message = str(error_indication)
            status = (
                "TIMEOUT"
                if is_snmp_no_response_failure(
                    SOURCE_PROTOCOL_SNMP, "ERROR", {"message": error_message}
                )
                else "ERROR"
            )
            return result(None, status, error_message)
        if error_status:
            error = f"{error_status.prettyPrint()} at {error_index and var_binds[int(error_index) - 1][0] or '?'}"
            return result(None, "ERROR", error)

        value = var_binds[0][1]
        try:
            return result(float(value), "OK", None)
        except (ValueError, TypeError) as exc:
            return result(None, "ERROR", str(exc))
    except Exception as exc:
        return result(None, "ERROR", str(exc))


def _coerce_snmp_fetch_result(raw: Any) -> tuple[float | None, str, str | None]:
    if isinstance(raw, tuple) and len(raw) == 3:
        value, status, error = raw
        return value, str(status or "ERROR"), None if error is None else str(error)
    if raw is None:
        return None, "TIMEOUT", "No SNMP response received before timeout"
    return raw, "OK", None


def _log_observe_only_cycle(
    settings, metrics_count, collected_count, failed_count, duration, jobs_per_min
):
    """Emit PR1 baseline telemetry without changing polling behavior."""
    if not settings.pipeline_observe_only:
        return
    logger.info(
        "polling_observe_cycle",
        extra={
            "polling": {
                "metrics_processed": metrics_count,
                "metrics_collected": collected_count,
                "metrics_failed": failed_count,
                "cycle_duration": round(duration, 2),
                "jobs_per_min": jobs_per_min,
                "pipeline_observe_only": True,
            }
        },
    )


def _count_monitored_cis(session) -> int:
    """Return the stable count of distinct CIs with active metric assignments."""
    record = session.run(
        """
        MATCH (n:CI)-[:HAS_METRIC]->(:MetricDef)
        RETURN count(DISTINCT n) AS cis_monitored
    """
    ).single()
    if not record:
        return 0
    return int(record.get("cis_monitored") or 0)


def _base_severity_from_criticality(criticality) -> str:
    try:
        normalized = int(criticality or 1)
    except (TypeError, ValueError):
        normalized = 1
    return {2: "WARNING", 3: "CRITICAL"}.get(normalized, "INFO")


def _previous_latency_ms(db, node_id: str, before: datetime) -> float | None:
    result = db.execute(
        text(
            """
            SELECT value FROM metric_values
            WHERE node_id = :node_id AND metric_id = :metric_id AND time < :before
            ORDER BY time DESC LIMIT 1
        """
        ),
        {"node_id": node_id, "metric_id": ICMP_LATENCY_METRIC_ID, "before": before},
    )
    row = result.first() if hasattr(result, "first") else None
    if not row:
        return None
    value = row[0] if not isinstance(row, dict) else row.get("value")
    return None if value is None else float(value)


def _dedupe_snmp_collection_failures(failures):
    deduped = {}
    for row in failures:
        key = (row.get("node_id"), row.get("metric_id"), row.get("failure_family"))
        deduped[key] = row
    return list(deduped.values())


def _resolve_correlation(cache, ci_id, metric_id):
    """Return ``{correlation_type, propagated_from, root_cause_ci_id}`` for a failing (CI, metric).

    Looks up the per-cycle cache built by ``build_open_parent_index``. The cache is
    pre-filtered by ``MetricDef.can_propagate`` at build time, so non-propagating
    metrics simply miss the cache and resolve to ROOT. No I/O; never raises.

    Design Decision 3 (C2-corrected): no ``session`` parameter — this helper only
    does dict lookups after the cache is built, keeping the hot CREATE path
    exception-free.
    """
    try:
        parent = cache.get((ci_id, metric_id)) if cache else None
    except Exception:
        # A malformed cache (wrong type, unhashable key, etc.) must not break the
        # write path. Fall through to ROOT — matches the resilience contract.
        parent = None
    if parent and parent.get("parent_event_id"):
        parent_event_id = parent["parent_event_id"]
        # Contract: root_cause_ci_id must NEVER be an event id (recovery queries
        # match it against e.ci_id). If the cache entry lacks a CI-level root
        # cause, degrade to ROOT instead of writing an event id into a CI field.
        root_cause_ci_id = parent.get("root_cause_ci_id")
        if not root_cause_ci_id:
            return {"correlation_type": "ROOT", "propagated_from": None, "root_cause_ci_id": ci_id}
        return {
            "correlation_type": "PROPAGATED",
            "propagated_from": parent_event_id,
            "root_cause_ci_id": root_cause_ci_id,
        }
    return {"correlation_type": "ROOT", "propagated_from": None, "root_cause_ci_id": ci_id}


def _build_propagated_root_update_comment(row):
    return (
        f"CI '{row.get('node_id')}' is affected by root cause CI '{row.get('root_cause_ci_id')}' "
        "reported by child dependency polling."
    )


def _update_propagated_root_events(session, propagated_rows):
    """Attach propagated children to existing ROOT events without creating child events."""
    if not propagated_rows:
        return
    for row in propagated_rows:
        row["affected_ci_comment"] = _build_propagated_root_update_comment(row)

    query = """
        UNWIND $propagated_rows AS row
        MATCH (root:Event {id: row.propagated_from})
        WHERE root.status IN ['OPEN', 'ACK', 'RECOVERED']
          AND row.propagated_from IS NOT NULL
          AND row.node_id IS NOT NULL
          AND coalesce(root.correlation_type, 'ROOT') = 'ROOT'
        WITH root, row,
             CASE
               WHEN root.affected_ci_ids IS NULL OR size(root.affected_ci_ids) = 0 THEN [row.node_id]
               WHEN row.node_id IN root.affected_ci_ids THEN root.affected_ci_ids
               ELSE root.affected_ci_ids + [row.node_id]
             END AS affected_ci_ids
        SET root.affected_ci_ids = affected_ci_ids,
            root.affected_ci_count = size(affected_ci_ids),
            root.comments = CASE
              WHEN root.comments IS NULL OR size(root.comments) = 0 THEN [row.affected_ci_comment]
              WHEN row.affected_ci_comment IN root.comments THEN root.comments
              ELSE root.comments + [row.affected_ci_comment]
            END
        RETURN count(row) AS updated_roots
    """

    result = session.run(query, propagated_rows=propagated_rows)
    summary = result.single() if hasattr(result, "single") else None
    updated_roots = int(summary.get("updated_roots") or 0) if summary else 0
    if updated_roots < len(propagated_rows):
        logger.warning(
            "topology_rca_propagated_root_update_partial rows=%s updated_roots=%s",
            len(propagated_rows),
            updated_roots,
        )


def _refresh_snmp_collection_failures(session, failures, cache=None, lock_db=None):
    failures = _dedupe_snmp_collection_failures(failures)
    if not failures:
        return
    # Decorate each row with topology-derived correlation fields (fix #310).
    # _resolve_correlation is a pure dict lookup; default cache={} preserves the
    # pre-fix all-ROOT behaviour for callers that don't pass a cache.
    if cache is None:
        cache = {}
    for row in failures:
        row.update(_resolve_correlation(cache, row.get("node_id"), row.get("metric_id")))

    root_rows = [row for row in failures if row.get("correlation_type") != "PROPAGATED"]
    propagated_rows = [row for row in failures if row.get("correlation_type") == "PROPAGATED"]

    # Serialize concurrent writers for the same (ci_id, metric_id, event_type)
    # triplet before the Neo4j OPTIONAL MATCH + FOREACH(CREATE) Event write
    # (issue #322). The pg_advisory_xact_lock is transaction-scoped: poll_snmp
    # owns the SQLAlchemy session passed as lock_db and keeps it open through
    # this Neo4j write, then db.close() releases the lock after the cycle.
    # Locks are sorted lexicographically so two batches do not trigger Postgres
    # deadlock detection when they overlap on different keys.
    if lock_db is not None:
        distinct_triplets = sorted(
            {
                (row.get("node_id"), row.get("metric_id"), row.get("event_type"))
                for row in failures
                if row.get("node_id") and row.get("metric_id") and row.get("event_type")
            }
        )
        for ci_id, metric_id, event_type in distinct_triplets:
            acquire_event_triplet_lock(
                lock_db,
                ci_id,
                metric_id,
                event_type,
                writer_context="snmp_worker_collection_failure",
            )

    if root_rows:
        primary_query = """
            UNWIND $failures AS row
            MATCH (n:CI {id: row.node_id})
            MATCH (m:MetricDef {id: row.metric_id})
            OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})
            WHERE existing.status IN ['OPEN', 'ACK', 'RECOVERED']
              AND (
                existing.event_type = 'COLLECTION_FAILURE'
                OR (existing.event_type IS NULL AND existing.message STARTS WITH 'Metric Collection Failed:')
              )
              AND (existing.failure_family = 'SNMP_NO_RESPONSE' OR existing.failure_family IS NULL)
              AND (existing.source_protocol IS NULL OR toUpper(existing.source_protocol) = row.source_protocol)
            WITH row, n, m, head(collect(existing)) AS existing
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                CREATE (created:Event {
                    id: randomUUID(), ci_id: row.node_id, metric_id: row.metric_id,
                    status: 'OPEN', severity: row.severity, message: row.message,
                    event_type: row.event_type, failure_family: row.failure_family,
                    source_protocol: row.source_protocol, created_at: datetime(),
                    last_seen: datetime(), ack: false,
                    correlation_type: row.correlation_type,
                    propagated_from: row.propagated_from,
                    root_cause_ci_id: row.root_cause_ci_id,
                    poll_collector_id: $poll_collector_id
                })
                MERGE (n)-[:HAS_EVENT]->(created)
                MERGE (created)-[:TRIGGERED_BY]->(m)
            )
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
                SET existing.status = 'OPEN', existing.severity = row.severity,
                    existing.message = row.message, existing.last_seen = datetime(),
                    existing.recovered_at = NULL, existing.ack = false,
                    existing.event_type = row.event_type,
                    existing.failure_family = row.failure_family,
                    existing.source_protocol = row.source_protocol,
                    existing.poll_collector_id = $poll_collector_id
                MERGE (n)-[:HAS_EVENT]->(existing)
                MERGE (existing)-[:TRIGGERED_BY]->(m)
            )
        """
        # Fallback Cypher — hand-written to avoid dangling-comma artifacts
        # that naive ``.replace()`` would leave in the SET clause
        # (verify-report CRITICAL #1 — issue #340). The CREATE row-dict
        # removal is safe because the next line is ``})``; the SET clause
        # removal requires also dropping the trailing comma after
        # ``existing.source_protocol = row.source_protocol``.
        fallback_query = """
            UNWIND $failures AS row
            MATCH (n:CI {id: row.node_id})
            MATCH (m:MetricDef {id: row.metric_id})
            OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})
            WHERE existing.status IN ['OPEN', 'ACK', 'RECOVERED']
              AND (
                existing.event_type = 'COLLECTION_FAILURE'
                OR (existing.event_type IS NULL AND existing.message STARTS WITH 'Metric Collection Failed:')
              )
              AND (existing.failure_family = 'SNMP_NO_RESPONSE' OR existing.failure_family IS NULL)
              AND (existing.source_protocol IS NULL OR toUpper(existing.source_protocol) = row.source_protocol)
            WITH row, n, m, head(collect(existing)) AS existing
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                CREATE (created:Event {
                    id: randomUUID(), ci_id: row.node_id, metric_id: row.metric_id,
                    status: 'OPEN', severity: row.severity, message: row.message,
                    event_type: row.event_type, failure_family: row.failure_family,
                    source_protocol: row.source_protocol, created_at: datetime(),
                    last_seen: datetime(), ack: false,
                    correlation_type: row.correlation_type,
                    propagated_from: row.propagated_from,
                    root_cause_ci_id: row.root_cause_ci_id
                })
                MERGE (n)-[:HAS_EVENT]->(created)
                MERGE (created)-[:TRIGGERED_BY]->(m)
            )
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
                SET existing.status = 'OPEN', existing.severity = row.severity,
                    existing.message = row.message, existing.last_seen = datetime(),
                    existing.recovered_at = NULL, existing.ack = false,
                    existing.event_type = row.event_type,
                    existing.failure_family = row.failure_family,
                    existing.source_protocol = row.source_protocol
                MERGE (n)-[:HAS_EVENT]->(existing)
                MERGE (existing)-[:TRIGGERED_BY]->(m)
            )
        """
        run_with_cypher_param_fallback(
            session,
            primary_query,
            {"failures": root_rows, "poll_collector_id": POLL_COLLECTOR_ID},
            fallback_query,
            {"failures": root_rows},
            is_poll_collector_id_undefined_error,
            logger,
        )

    # Keep PROPAGATED children from creating their own child events.
    # Instead, attach affected-CI metadata to the ROOT event.
    _update_propagated_root_events(session, propagated_rows)


def _availability_source(value: Any) -> str | None:
    source = str(value or "").strip().upper()
    return source if source in {"PING", "ICMP"} else None


def _refresh_icmp_availability_events(session, updates, cache=None, lock_db=None):
    availability_events = [
        u
        for u in updates
        if str(u.get("protocol") or "").upper() == SOURCE_PROTOCOL_ICMP
        and _availability_source(u.get("availability_source")) is not None
        and float(u.get("value") or 0) == 0.0
    ]
    if not availability_events:
        return
    # Decorate each row with topology-derived correlation fields (fix #310).
    if cache is None:
        cache = {}
    for row in availability_events:
        row.update(_resolve_correlation(cache, row.get("node_id"), row.get("metric_id")))

    root_rows = [row for row in availability_events if row.get("correlation_type") != "PROPAGATED"]
    propagated_rows = [
        row for row in availability_events if row.get("correlation_type") == "PROPAGATED"
    ]

    # Serialize concurrent writers per (ci_id, metric_id, event_type) triplet
    # before the Neo4j OPTIONAL MATCH + FOREACH(CREATE) Event write (issue #322).
    # The pg_advisory_xact_lock is transaction-scoped: poll_snmp owns the
    # SQLAlchemy session passed as lock_db and keeps it open through this Neo4j
    # write, then db.close() releases the lock after the cycle. Sorted
    # lexicographic acquisition prevents Postgres deadlock detection from
    # aborting one of two overlapping batches.
    if lock_db is not None:
        distinct_triplets = sorted(
            {
                (row.get("node_id"), row.get("metric_id"), row.get("event_type"))
                for row in availability_events
                if row.get("node_id") and row.get("metric_id") and row.get("event_type")
            }
        )
        for ci_id, metric_id, event_type in distinct_triplets:
            acquire_event_triplet_lock(
                lock_db,
                ci_id,
                metric_id,
                event_type,
                writer_context="snmp_worker_icmp_availability",
            )

    if root_rows:
        primary_query = """
            UNWIND $availability_events AS row
            WITH row WHERE row.event_type = 'AVAILABILITY'
              AND row.source_protocol = 'ICMP'
              AND row.availability_source IN ['PING', 'ICMP']
            MATCH (n:CI {id: row.node_id})
            MATCH (m:MetricDef {id: row.metric_id})
            OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})
            WHERE existing.status IN ['OPEN', 'ACK', 'RECOVERED']
              AND existing.event_type = 'AVAILABILITY'
              AND coalesce(existing.correlation_type, 'ROOT') = 'ROOT'
              AND existing.availability_source IN ['PING', 'ICMP']
              AND (existing.source_protocol IS NULL OR toUpper(existing.source_protocol) = row.source_protocol)
            WITH row, n, m, head(collect(existing)) AS existing
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                CREATE (created:Event {
                    id: randomUUID(), ci_id: row.node_id, metric_id: row.metric_id,
                    status: 'OPEN', severity: row.severity, message: row.message,
                    event_type: row.event_type, source_protocol: row.source_protocol,
                    availability_source: row.availability_source,
                    created_at: datetime(), last_seen: datetime(), ack: false,
                    correlation_type: row.correlation_type,
                    propagated_from: row.propagated_from,
                    root_cause_ci_id: row.root_cause_ci_id,
                    poll_collector_id: $poll_collector_id
                })
                MERGE (n)-[:HAS_EVENT]->(created)
                MERGE (created)-[:TRIGGERED_BY]->(m)
            )
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
                SET existing.status = 'OPEN', existing.severity = row.severity,
                    existing.message = row.message, existing.last_seen = datetime(),
                    existing.recovered_at = NULL, existing.ack = false,
                    existing.event_type = row.event_type,
                    existing.source_protocol = row.source_protocol,
                    existing.availability_source = row.availability_source,
                    existing.poll_collector_id = $poll_collector_id
                MERGE (n)-[:HAS_EVENT]->(existing)
                MERGE (existing)-[:TRIGGERED_BY]->(m)
            )
        """
        # Fallback Cypher — hand-written (see #340, verify-report CRITICAL #1).
        # Drops the trailing comma after
        # ``existing.availability_source = row.availability_source`` that a
        # naive ``.replace()`` would leave dangling before ``MERGE``.
        fallback_query = """
            UNWIND $availability_events AS row
            WITH row WHERE row.event_type = 'AVAILABILITY'
              AND row.source_protocol = 'ICMP'
              AND row.availability_source IN ['PING', 'ICMP']
            MATCH (n:CI {id: row.node_id})
            MATCH (m:MetricDef {id: row.metric_id})
            OPTIONAL MATCH (existing:Event {ci_id: row.node_id, metric_id: row.metric_id})
            WHERE existing.status IN ['OPEN', 'ACK', 'RECOVERED']
              AND existing.event_type = 'AVAILABILITY'
              AND coalesce(existing.correlation_type, 'ROOT') = 'ROOT'
              AND existing.availability_source IN ['PING', 'ICMP']
              AND (existing.source_protocol IS NULL OR toUpper(existing.source_protocol) = row.source_protocol)
            WITH row, n, m, head(collect(existing)) AS existing
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                CREATE (created:Event {
                    id: randomUUID(), ci_id: row.node_id, metric_id: row.metric_id,
                    status: 'OPEN', severity: row.severity, message: row.message,
                    event_type: row.event_type, source_protocol: row.source_protocol,
                    availability_source: row.availability_source,
                    created_at: datetime(), last_seen: datetime(), ack: false,
                    correlation_type: row.correlation_type,
                    propagated_from: row.propagated_from,
                    root_cause_ci_id: row.root_cause_ci_id
                })
                MERGE (n)-[:HAS_EVENT]->(created)
                MERGE (created)-[:TRIGGERED_BY]->(m)
            )
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
                SET existing.status = 'OPEN', existing.severity = row.severity,
                    existing.message = row.message, existing.last_seen = datetime(),
                    existing.recovered_at = NULL, existing.ack = false,
                    existing.event_type = row.event_type,
                    existing.source_protocol = row.source_protocol,
                    existing.availability_source = row.availability_source
                MERGE (n)-[:HAS_EVENT]->(existing)
                MERGE (existing)-[:TRIGGERED_BY]->(m)
            )
        """
        run_with_cypher_param_fallback(
            session,
            primary_query,
            {
                "availability_events": root_rows,
                "poll_collector_id": POLL_COLLECTOR_ID,
            },
            fallback_query,
            {"availability_events": root_rows},
            is_poll_collector_id_undefined_error,
            logger,
        )

    # Keep PROPAGATED children from creating their own child events.
    # Instead, attach affected-CI metadata to the ROOT event.
    _update_propagated_root_events(session, propagated_rows)


def _recover_icmp_availability_events(session, updates):
    recoveries = [
        u
        for u in updates
        if str(u.get("protocol") or "").upper() == SOURCE_PROTOCOL_ICMP
        and _availability_source(u.get("availability_source")) is not None
        and float(u.get("value") or 0) == 1.0
    ]
    if not recoveries:
        return
    session.run(
        """
        UNWIND $recoveries AS row
        MATCH (:CI {id: row.node_id})-[:HAS_EVENT]->(e:Event {metric_id: row.metric_id})
        WHERE e.status IN ['OPEN', 'ACK']
          AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
          AND e.event_type = 'AVAILABILITY'
          AND e.availability_source IN ['PING', 'ICMP']
          AND (e.source_protocol IS NULL OR toUpper(e.source_protocol) = row.protocol)
        SET e.status = 'RECOVERED',
            e.recovered_at = datetime(),
            e.message = 'Metric ICMP availability recovered. Latest sample collected by legacy SNMP worker'
        WITH e
        CALL {
            WITH e
            MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE pe.propagated_from = e.id
              AND pe.root_cause_ci_id = e.ci_id
              AND pe.correlation_type = 'PROPAGATED'
              AND pe.status IN ['OPEN', 'ACK']
              AND coalesce(m.can_propagate, true) = true
            SET pe.status = 'RECOVERED', pe.recovered_at = datetime()
            RETURN count(pe) AS propagated_recovered
        }
        RETURN e
    """,
        recoveries=recoveries,
    )


def _refresh_icmp_latency_events(session, updates, cache=None, lock_db=None):
    breaches = [
        u
        for u in updates
        if str(u.get("protocol") or "").upper() == SOURCE_PROTOCOL_ICMP
        and u.get("metric_id") == ICMP_LATENCY_METRIC_ID
        and u.get("event_type") == EVENT_TYPE_THRESHOLD_BREACH
        and u.get("status") in {"WARNING", "CRITICAL"}
    ]
    if not breaches:
        return
    # Decorate each row with topology-derived correlation fields (fix #310).
    if cache is None:
        cache = {}
    for row in breaches:
        row.update(_resolve_correlation(cache, row.get("node_id"), row.get("metric_id")))

    root_rows = [row for row in breaches if row.get("correlation_type") != "PROPAGATED"]
    propagated_rows = [row for row in breaches if row.get("correlation_type") == "PROPAGATED"]

    # Serialize concurrent writers per (ci_id, metric_id, event_type) triplet
    # before the Neo4j OPTIONAL MATCH + FOREACH(CREATE) Event write (issue #322).
    # The pg_advisory_xact_lock is transaction-scoped: poll_snmp owns the
    # SQLAlchemy session passed as lock_db and keeps it open through this Neo4j
    # write, then db.close() releases the lock after the cycle. Sorted
    # lexicographic acquisition prevents Postgres deadlock detection from
    # aborting one of two overlapping batches.
    if lock_db is not None:
        distinct_triplets = sorted(
            {
                (row.get("node_id"), row.get("metric_id"), row.get("event_type"))
                for row in breaches
                if row.get("node_id") and row.get("metric_id") and row.get("event_type")
            }
        )
        for ci_id, metric_id, event_type in distinct_triplets:
            acquire_event_triplet_lock(
                lock_db,
                ci_id,
                metric_id,
                event_type,
                writer_context="snmp_worker_icmp_latency",
            )

    if root_rows:
        primary_query = """
            UNWIND $breaches AS row
            MATCH (n:CI {id: row.node_id})
            MATCH (m:MetricDef {id: row.metric_id})
            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: 'THRESHOLD_BREACH'})
            WHERE existing.status IN ['OPEN', 'ACK']
              AND coalesce(existing.correlation_type, 'ROOT') = 'ROOT'
            WITH row, n, m, head(collect(existing)) AS existing
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                CREATE (created:Event {
                    id: randomUUID(), ci_id: row.node_id, metric_id: row.metric_id,
                    event_type: 'THRESHOLD_BREACH', status: 'OPEN', severity: row.status,
                    message: row.message, source_protocol: row.source_protocol,
                    last_seen: datetime(), ack: false,
                    correlation_type: row.correlation_type,
                    propagated_from: row.propagated_from,
                    root_cause_ci_id: row.root_cause_ci_id,
                    poll_collector_id: $poll_collector_id
                })
                MERGE (n)-[:HAS_EVENT]->(created)
                MERGE (created)-[:TRIGGERED_BY]->(m)
            )
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
                SET existing.severity = row.status,
                    existing.message = row.message,
                    existing.source_protocol = row.source_protocol,
                    existing.last_seen = datetime(),
                    existing.ack = CASE WHEN existing.status = 'ACK' THEN existing.ack ELSE false END,
                    existing.recovered_at = NULL,
                    existing.correlation_type = coalesce(existing.correlation_type, 'ROOT'),
                    existing.root_cause_ci_id = coalesce(existing.root_cause_ci_id, row.node_id),
                    existing.poll_collector_id = $poll_collector_id
                MERGE (n)-[:HAS_EVENT]->(existing)
                MERGE (existing)-[:TRIGGERED_BY]->(m)
            )
        """
        # Fallback Cypher — hand-written (see #340, verify-report CRITICAL #1).
        # Drops the trailing comma after
        # ``existing.root_cause_ci_id = coalesce(...)`` that a naive
        # ``.replace()`` would leave dangling before ``MERGE``.
        fallback_query = """
            UNWIND $breaches AS row
            MATCH (n:CI {id: row.node_id})
            MATCH (m:MetricDef {id: row.metric_id})
            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: 'THRESHOLD_BREACH'})
            WHERE existing.status IN ['OPEN', 'ACK']
              AND coalesce(existing.correlation_type, 'ROOT') = 'ROOT'
            WITH row, n, m, head(collect(existing)) AS existing
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                CREATE (created:Event {
                    id: randomUUID(), ci_id: row.node_id, metric_id: row.metric_id,
                    event_type: 'THRESHOLD_BREACH', status: 'OPEN', severity: row.status,
                    message: row.message, source_protocol: row.source_protocol,
                    last_seen: datetime(), ack: false,
                    correlation_type: row.correlation_type,
                    propagated_from: row.propagated_from,
                    root_cause_ci_id: row.root_cause_ci_id
                })
                MERGE (n)-[:HAS_EVENT]->(created)
                MERGE (created)-[:TRIGGERED_BY]->(m)
            )
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
                SET existing.severity = row.status,
                    existing.message = row.message,
                    existing.source_protocol = row.source_protocol,
                    existing.last_seen = datetime(),
                    existing.ack = CASE WHEN existing.status = 'ACK' THEN existing.ack ELSE false END,
                    existing.recovered_at = NULL,
                    existing.correlation_type = coalesce(existing.correlation_type, 'ROOT'),
                    existing.root_cause_ci_id = coalesce(existing.root_cause_ci_id, row.node_id)
                MERGE (n)-[:HAS_EVENT]->(existing)
                MERGE (existing)-[:TRIGGERED_BY]->(m)
            )
        """
        run_with_cypher_param_fallback(
            session,
            primary_query,
            {
                "breaches": root_rows,
                "poll_collector_id": POLL_COLLECTOR_ID,
            },
            fallback_query,
            {"breaches": root_rows},
            is_poll_collector_id_undefined_error,
            logger,
        )

    # Keep PROPAGATED children from creating their own child events.
    # Instead, attach affected-CI metadata to the ROOT event.
    _update_propagated_root_events(session, propagated_rows)


def _recover_icmp_latency_events(session, updates):
    recoveries = [
        u
        for u in updates
        if str(u.get("protocol") or "").upper() == SOURCE_PROTOCOL_ICMP
        and u.get("metric_id") == ICMP_LATENCY_METRIC_ID
        and u.get("status") == "OK"
    ]
    if not recoveries:
        return
    session.run(
        """
        UNWIND $recoveries AS row
        MATCH (:CI {id: row.node_id})-[:HAS_EVENT]->(e:Event {metric_id: row.metric_id})
        WHERE e.status IN ['OPEN', 'ACK']
          AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
          AND e.event_type = 'THRESHOLD_BREACH'
          AND (e.source_protocol IS NULL OR toUpper(e.source_protocol) = row.source_protocol)
        SET e.status = 'RECOVERED',
            e.recovered_at = datetime(),
            e.message = row.message
        WITH e
        CALL {
            WITH e
            MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE pe.propagated_from = e.id
              AND pe.root_cause_ci_id = e.ci_id
              AND pe.correlation_type = 'PROPAGATED'
              AND pe.status IN ['OPEN', 'ACK']
              AND coalesce(m.can_propagate, true) = true
            SET pe.status = 'RECOVERED', pe.recovered_at = datetime()
            RETURN count(pe) AS propagated_recovered
        }
        RETURN e
    """,
        recoveries=recoveries,
    )


def _recover_snmp_collection_failures(session, updates):
    recoveries = [
        u for u in updates if str(u.get("protocol") or "").upper() == SOURCE_PROTOCOL_SNMP
    ]
    if not recoveries:
        return
    session.run(
        """
        UNWIND $recoveries AS row
        MATCH (:CI {id: row.node_id})-[:HAS_EVENT]->(e:Event {metric_id: row.metric_id})
        WHERE e.status IN ['OPEN', 'ACK']
          AND (
            e.event_type = 'COLLECTION_FAILURE'
            OR (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')
          )
          AND (e.failure_family = 'SNMP_NO_RESPONSE' OR e.failure_family IS NULL)
          AND (e.source_protocol IS NULL OR toUpper(e.source_protocol) = row.protocol)
        SET e.status = 'RECOVERED',
            e.recovered_at = datetime(),
            e.message = 'Metric collection recovered. Latest sample collected by legacy SNMP worker'
        WITH e
        CALL {
            WITH e
            # SNMP recovery intentionally matches by root_cause_ci_id for
            # FULL-CASCADE recovery: every descendant whose root cause is the
            # recovering CI is closed in one pass. This differs from the ICMP
            # recovery paths (_recover_icmp_availability_events and
            # _recover_icmp_latency_events), which match by propagated_from = e.id
            # (direct-child only). The asymmetry is deliberate and NOT changed
            # by this PR — do not "fix" it without a deliberate design decision.
            MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE pe.root_cause_ci_id = e.ci_id
              AND pe.correlation_type = 'PROPAGATED'
              AND pe.status IN ['OPEN', 'ACK']
              AND coalesce(m.can_propagate, true) = true
            SET pe.status = 'RECOVERED', pe.recovered_at = datetime()
            RETURN count(pe) AS propagated_recovered
        }
        RETURN e
    """,
        recoveries=recoveries,
    )


def poll_snmp():
    start_time = time.time()
    polling_settings = get_polling_pipeline_settings()
    print(f"[{datetime.now().isoformat()}] Starting Real-World Polling Cycle...")
    # Cycle-owned SQLAlchemy session. Event triplet locks acquired with
    # pg_advisory_xact_lock by the refresh helpers are transaction-scoped and
    # rely on this session staying open through the following Neo4j Event writes;
    # the finally block closes db only after those writes complete.
    db = SessionLocal()
    metrics_to_save = []
    latest_updates = []
    failure_updates = []
    metrics_count = 0
    failed_count = 0
    try:
        with driver.session() as session:
            # Enhanced query: Get CI credentials and Metric metadata
            result = session.run(
                """
                MATCH (n:CI)-[r:HAS_METRIC]->(m:MetricDef)
                WITH n, r, m,
                     coalesce(m.polling_interval, 60) as interval,
                     coalesce(r.last_polled, datetime({year:1970})) as last_p
                WHERE duration.between(last_p, datetime()).seconds >= interval
                RETURN n.id as node_id, n.ip as ip,
                       coalesce(n.snmp_community, 'public') as community,
                       coalesce(n.snmp_port, 161) as port,
                       m.id as metric_id, m.name as metric_name, m.protocol as protocol,
                       m.oid as oid, m.criticality as criticality,
                       m.metric_kind as metric_kind,
                       m.availability_source as availability_source,
                       interval
            """
            )

            records = list(result)
            records.sort(
                key=lambda record: (
                    (
                        1
                        if normalized_protocol(record["protocol"]) == "ICMP"
                        and is_icmp_telemetry_metric(
                            record["metric_id"], {"metric_kind": record.get("metric_kind")}
                        )
                        else 0
                    ),
                    record["node_id"],
                    record["metric_id"],
                )
            )
            polled_icmp_nodes = set()

            # Use iterator to process one by one
            for record in records:
                metrics_count += 1
                node_id = record["node_id"]
                mid = record["metric_id"]
                protocol = normalized_protocol(record["protocol"])
                ip = record["ip"]

                if not ip:
                    print(f"Skipping {node_id}: No IP address.")
                    continue

                val = None
                sidecar_samples = []
                availability_source = _availability_source(record.get("availability_source"))
                metric_metadata = {
                    "metric_kind": record.get("metric_kind"),
                    "availability_source": availability_source,
                }
                icmp_settings = get_icmp_settings()
                internal_icmp_poll = False
                if protocol == "ICMP" and is_icmp_telemetry_metric(mid, metric_metadata):
                    if node_id in polled_icmp_nodes:
                        continue
                    polled_icmp_nodes.add(node_id)
                    mid = ICMP_AVAILABILITY_METRIC_ID
                    internal_icmp_poll = True
                elif (
                    protocol == "ICMP"
                    and availability_source
                    and is_icmp_availability_metric(mid, metric_metadata)
                ):
                    if node_id in polled_icmp_nodes:
                        continue
                    polled_icmp_nodes.add(node_id)
                elif protocol == "ICMP":
                    continue
                if protocol == "ICMP":
                    measurement = coerce_ping_measurement(
                        fetch_icmp_ping(
                            ip,
                            timeout_ms=icmp_settings.timeout_ms,
                            retries=icmp_settings.retries,
                            include_measurement=True,
                        )
                    )
                    val = measurement.availability_value
                    sample_time = datetime.utcnow()
                    # Debounce logic: track consecutive failures per node
                    if val == 0:
                        _consecutive_failures[node_id] = _consecutive_failures.get(node_id, 0) + 1
                        if _consecutive_failures[node_id] >= icmp_settings.debounce_count:
                            # DOWN event: allow the debounced 0.0 observation
                            # to flow to durable metric/event writes. CI status
                            # and debounce reset happen only after Timescale
                            # persistence succeeds below.
                            val = 0.0
                        else:
                            # Below threshold: suppress metric recording until threshold
                            val = None
                            sidecar_samples = []
                    else:
                        # Success: reset counter and proceed normally
                        _consecutive_failures[node_id] = 0
                    if val is not None:
                        previous_latency = (
                            _previous_latency_ms(db, node_id, sample_time)
                            if measurement.available
                            else None
                        )
                        sidecar_samples = build_icmp_sidecar_samples(
                            node_id,
                            measurement,
                            previous_latency_ms=previous_latency,
                            observed_at=sample_time,
                        )
                snmp_status = "OK"
                snmp_error = None
                if protocol == SOURCE_PROTOCOL_SNMP and record["oid"]:
                    val, snmp_status, snmp_error = _coerce_snmp_fetch_result(
                        fetch_snmp_value(
                            ip,
                            record["community"],
                            record["oid"],
                            int(record["port"]),
                            include_status=True,
                        )
                    )

                if val is not None:
                    primary_time = datetime.utcnow()
                    if not internal_icmp_poll:
                        metrics_to_save.append(
                            {
                                "node_id": node_id,
                                "metric_id": mid,
                                "value": val,
                                "time": primary_time,
                            }
                        )
                    metrics_to_save.extend(sidecar_samples)

                    metric_name = record["metric_name"] or mid
                    severity = _base_severity_from_criticality(record["criticality"])
                    if not internal_icmp_poll:
                        latest_updates.append(
                            {
                                "node_id": node_id,
                                "metric_id": mid,
                                "value": val,
                                "protocol": protocol,
                                "metric_name": metric_name,
                                "criticality": record["criticality"],
                                "status": (
                                    severity
                                    if protocol == SOURCE_PROTOCOL_ICMP
                                    and availability_source
                                    and val == 0.0
                                    else "OK"
                                ),
                                "message": (
                                    f"Service/Host Down: {metric_name}"
                                    if protocol == SOURCE_PROTOCOL_ICMP
                                    and availability_source
                                    and val == 0.0
                                    else "Latest sample collected by legacy SNMP worker"
                                ),
                                "event_type": (
                                    EVENT_TYPE_AVAILABILITY
                                    if protocol == SOURCE_PROTOCOL_ICMP
                                    and availability_source
                                    and val == 0.0
                                    else None
                                ),
                                "source_protocol": (
                                    SOURCE_PROTOCOL_ICMP
                                    if protocol == SOURCE_PROTOCOL_ICMP
                                    else protocol
                                ),
                                "availability_source": availability_source,
                                "severity": severity,
                                "metric_kind": (
                                    "availability"
                                    if protocol == SOURCE_PROTOCOL_ICMP and availability_source
                                    else "telemetry"
                                ),
                            }
                        )
                    for sample in sidecar_samples:
                        latency_thresholds = latency_threshold_metadata(
                            warning_ms=icmp_settings.latency_warning_ms,
                            critical_ms=icmp_settings.latency_critical_ms,
                        )
                        sample_status = "OK"
                        sample_message = (
                            "Latest ICMP telemetry sample collected by legacy SNMP worker"
                        )
                        sample_event_type = None
                        sample_severity = "INFO"
                        if sample["metric_id"] == ICMP_LATENCY_METRIC_ID:
                            sample_status = evaluate_latency_status(
                                sample.get("value"),
                                warning_ms=icmp_settings.latency_warning_ms,
                                critical_ms=icmp_settings.latency_critical_ms,
                            )
                            sample_severity = (
                                sample_status
                                if sample_status in {"WARNING", "CRITICAL"}
                                else "INFO"
                            )
                            if sample_status == "CRITICAL":
                                sample_message = f"Critical Threshold Breached: {sample['value']} >= {icmp_settings.latency_critical_ms}"
                                sample_event_type = EVENT_TYPE_THRESHOLD_BREACH
                            elif sample_status == "WARNING":
                                sample_message = f"Warning Threshold Breached: {sample['value']} >= {icmp_settings.latency_warning_ms}"
                                sample_event_type = EVENT_TYPE_THRESHOLD_BREACH
                            else:
                                sample_message = (
                                    f"Metric ICMP Latency is OK. Value: {sample['value']}"
                                )
                        latest_updates.append(
                            {
                                "node_id": node_id,
                                "metric_id": sample["metric_id"],
                                "value": sample["value"],
                                "protocol": protocol,
                                "metric_name": sample["metric_id"],
                                "criticality": (
                                    latency_thresholds["criticality"]
                                    if sample["metric_id"] == ICMP_LATENCY_METRIC_ID
                                    else record["criticality"]
                                ),
                                "status": sample_status,
                                "message": sample_message,
                                "event_type": sample_event_type,
                                "source_protocol": SOURCE_PROTOCOL_ICMP,
                                "severity": sample_severity,
                                "metric_kind": "telemetry",
                            }
                        )
                else:
                    failed_count += 1
                    if is_snmp_no_response_failure(
                        protocol,
                        snmp_status,
                        {"message": snmp_error},
                    ):
                        failure_updates.append(
                            {
                                "node_id": node_id,
                                "metric_id": mid,
                                "severity": "WARNING",
                                "message": f"Metric Collection Failed: {snmp_error or 'No SNMP response received before timeout'}",
                                "event_type": EVENT_TYPE_COLLECTION_FAILURE,
                                "failure_family": FAILURE_FAMILY_SNMP_NO_RESPONSE,
                                "source_protocol": SOURCE_PROTOCOL_SNMP,
                            }
                        )

            # Update collector status in Neo4j
            duration_current = time.time() - start_time
            jobs_per_min = (
                round((len(metrics_to_save) / duration_current) * 60, 1)
                if duration_current > 0
                else 0.0
            )
            monitored_ci_count = _count_monitored_cis(session)
            session.run(
                """
                MERGE (c:CollectorStatus {id: 'main'})
                SET c.last_run = datetime(),
                    c.status = 'RUNNING',
                    c.cis_monitored = $cis_monitored,
                    c.last_cycle_metrics_processed = $last_cycle_metrics_processed,
                    c.metrics_collected = $collected,
                    c.metrics_failed = $failed,
                    c.cycle_duration = $duration,
                    c.jobs_per_min = $jobs_per_min
            """,
                cis_monitored=monitored_ci_count,
                last_cycle_metrics_processed=metrics_count,
                collected=len(metrics_to_save),
                failed=failed_count,
                duration=round(duration_current, 2),
                jobs_per_min=jobs_per_min,
            )
            _log_observe_only_cycle(
                polling_settings,
                metrics_count,
                len(metrics_to_save),
                failed_count,
                duration_current,
                jobs_per_min,
            )

            # ── Topology RCA cache (fix #310) ───────────────────────────────
            # Build the open-parent cache ONCE per cycle, BEFORE any of the
            # three CREATE sites run (C1 fix). The cache is a LOCAL variable —
            # it does not leak across cycles. When ENABLE_TOPOLOGY_RCA=false or
            # build_open_parent_index raises, the cache is empty and every event
            # falls back to ROOT (identical to pre-fix behaviour).
            #
            # W2 blast radius: a single transient Neo4j error during the
            # cache-build degrades correlation for the ENTIRE cycle (every event
            # becomes ROOT). This is acceptable because (a) the next cycle
            # rebuilds the cache automatically, and (b) ENABLE_TOPOLOGY_RCA=false
            # is the deterministic operator kill-switch.
            availability_pairs_updates = [
                u
                for u in latest_updates
                if str(u.get("protocol") or "").upper() == SOURCE_PROTOCOL_ICMP
                and _availability_source(u.get("availability_source")) is not None
                and float(u.get("value") or 0) == 0.0
            ]
            latency_pairs_updates = [
                u
                for u in latest_updates
                if str(u.get("protocol") or "").upper() == SOURCE_PROTOCOL_ICMP
                and u.get("metric_id") == ICMP_LATENCY_METRIC_ID
                and u.get("event_type") == EVENT_TYPE_THRESHOLD_BREACH
                and u.get("status") in {"WARNING", "CRITICAL"}
            ]
            correlation_pairs = set()
            for u in failure_updates:
                correlation_pairs.add((u.get("node_id"), u.get("metric_id")))
            for u in availability_pairs_updates:
                correlation_pairs.add((u.get("node_id"), u.get("metric_id")))
            for u in latency_pairs_updates:
                correlation_pairs.add((u.get("node_id"), u.get("metric_id")))
            # Drop any pair with a None component (cannot be a cache key).
            correlation_pairs = {p for p in correlation_pairs if p[0] and p[1]}

            cache = {}  # local to this cycle — never module-level
            if polling_settings.enable_topology_rca and correlation_pairs:
                try:
                    cache = build_open_parent_index(session, correlation_pairs)
                except Exception as exc:
                    # Whole-cycle blast radius (W2): log once, fall back to ROOT
                    # for every row this cycle. Next cycle rebuilds the cache.
                    logger.warning(
                        "topology_rca_cache_build_failed falling back to ROOT "
                        "for entire cycle; pairs=%s error=%s",
                        sorted(correlation_pairs),
                        exc,
                    )
                    cache = {}

            _refresh_snmp_collection_failures(session, failure_updates, cache=cache, lock_db=db)

            # Perform Bulk Insert at the end of the cycle. Only publish latest
            # values to Neo4j after Timescale persistence succeeds, so the UI
            # does not advertise samples that failed durable storage.
            if metrics_to_save:
                bulk_insert_metrics(db, metrics_to_save)
                for update in latest_updates:
                    if (
                        update["protocol"].upper() == "ICMP"
                        and update.get("metric_kind") == "availability"
                        and update["value"] in (0.0, 1.0)
                    ):
                        session.run(
                            "MATCH (n:CI {id: $id}) SET n.status = $status, n.last_seen = datetime()",
                            id=update["node_id"],
                            status="CRITICAL" if update["value"] == 0.0 else "OK",
                        )
                        _consecutive_failures[update["node_id"]] = 0
                    session.run(
                        """
                        MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
                        SET r.last_polled = datetime(),
                            r.last_value = $val,
                            r.last_updated = datetime(),
                            r.status = $status,
                            r.last_message = $msg
                    """,
                        nid=update["node_id"],
                        mid=update["metric_id"],
                        val=update["value"],
                        status=update["status"],
                        msg=update["message"],
                    )
                availability_updates = [
                    u for u in latest_updates if u.get("metric_kind") == "availability"
                ]
                _refresh_icmp_availability_events(
                    session, availability_updates, cache=cache, lock_db=db
                )
                _recover_icmp_availability_events(session, availability_updates)
                latency_updates = [
                    u for u in latest_updates if u.get("metric_id") == ICMP_LATENCY_METRIC_ID
                ]
                _refresh_icmp_latency_events(session, latency_updates, cache=cache, lock_db=db)
                _recover_icmp_latency_events(session, latency_updates)
                _recover_snmp_collection_failures(session, latest_updates)
                print(
                    f"[{datetime.now().isoformat()}] Bulk saved {len(metrics_to_save)} metrics to TimescaleDB."
                )

        duration = time.time() - start_time
        if metrics_count > 0:
            print(
                f"[{datetime.now().isoformat()}] Cycle Complete: {metrics_count} metrics processed ({failed_count} failed) in {duration:.2f}s."
            )

    except Exception as e:
        print(f"Error during dynamic polling cycle: {e}")
    finally:
        db.close()


def job():
    try:
        polling_settings = get_polling_pipeline_settings()
        if polling_settings.snmp_leased_worker_enabled:
            from polling.snmp_worker import run_leased_snmp_worker_once

            db = SessionLocal()
            try:
                run_leased_snmp_worker_once(db, settings=polling_settings)
            finally:
                db.close()
            return
        poll_snmp()
    except Exception as e:
        print(f"Error in polling job: {e}")


# Run once every 10 seconds
schedule.every(10).seconds.do(job)

if __name__ == "__main__":
    configure_worker_runtime_logging()
    print("NEX-GEN Real-World SNMP Engine Starting...")
    if not SNMP_AVAILABLE:
        print("WARNING: PySNMP not found. SNMP polling will be unavailable.")
    verify_connection()
    print("Engine Running. Waiting for scheduled tasks...")
    while True:
        schedule.run_pending()
        time.sleep(1)
