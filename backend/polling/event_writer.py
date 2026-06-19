"""Batch-friendly Neo4j event updates for polling writer results."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping
from uuid import UUID

from services.polling_event_lifecycle import (
    COLLECTION_FAILURE_PREFIX,
    EVENT_TYPE_AVAILABILITY,
    EVENT_TYPE_COLLECTION_FAILURE,
    EVENT_TYPE_THRESHOLD_BREACH,
    FAILURE_FAMILY_SNMP_NO_RESPONSE,
    SOURCE_PROTOCOL_SNMP,
    collection_failure_message,
    is_snmp_no_response_failure,
    normalized_protocol,
)


def _value(item: Any) -> Any:
    if isinstance(item, Enum):
        return item.value
    if isinstance(item, UUID):
        return str(item)
    if isinstance(item, datetime):
        return item.isoformat()
    return item


def _num(envelope: Mapping[str, Any]) -> float | None:
    value = envelope.get("value") or {}
    try:
        raw = value.get("numeric")
        return None if raw is None else float(raw)
    except (TypeError, ValueError):
        return None


def _check(left: float, right: float, op: str) -> bool:
    if op == "<=":
        return left <= right
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    return left >= right


def _base_severity(metadata: Mapping[str, Any]) -> str:
    return {2: "WARNING", 3: "CRITICAL"}.get(int(metadata.get("criticality") or 1), "INFO")


def _availability_source(metadata: Mapping[str, Any]) -> str | None:
    source = str(metadata.get("availability_source") or "").strip().upper()
    return source if source in {"PING", "ICMP"} else None


def _collection_failure_event_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[Any, Any, Any, Any], dict[str, Any]] = {}
    for row in rows:
        if not (row.get("is_breach") and row.get("event_type") == EVENT_TYPE_COLLECTION_FAILURE):
            continue
        key = (row.get("ci_id"), row.get("metric_id"), row.get("event_type"), row.get("failure_family"))
        deduped[key] = row
    return list(deduped.values())


def _observed_at_order(value: Any) -> float | None:
    if isinstance(value, datetime):
        observed = value
    elif isinstance(value, str) and value.strip():
        try:
            observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.timestamp()


def _non_collection_target_event_type(row: Mapping[str, Any]) -> str | None:
    event_type = row.get("event_type")
    if event_type and event_type != EVENT_TYPE_COLLECTION_FAILURE:
        return str(event_type)
    if not row.get("recover_non_collection_event"):
        return None
    if row.get("source_protocol") == "ICMP" and row.get("availability_source") in {"PING", "ICMP"}:
        return EVENT_TYPE_AVAILABILITY
    return EVENT_TYPE_THRESHOLD_BREACH


def _dedupe_non_collection_latest_state(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[Any, ...], tuple[bool, float, int, dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        event_type = _non_collection_target_event_type(row)
        if event_type is None:
            continue
        key = (
            row.get("ci_id"),
            row.get("metric_id"),
            event_type,
            row.get("correlation_type") or "ROOT",
            row.get("propagated_from"),
            row.get("root_cause_event_id"),
            row.get("root_cause_ci_id"),
        )
        observed_order = _observed_at_order(row.get("observed_at"))
        order = (observed_order is not None, observed_order or 0.0, index)
        existing = deduped.get(key)
        if existing is None or order >= (existing[0], existing[1], existing[2]):
            deduped[key] = (*order, row)
    return [item[3] for item in deduped.values()]


def _non_collection_event_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in _dedupe_non_collection_latest_state(rows)
        if row.get("is_breach") and row.get("event_type") and row.get("event_type") != EVENT_TYPE_COLLECTION_FAILURE
    ]


def _latest_metric_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    row_list = list(rows)
    non_collection_latest_ids = {id(row) for row in _dedupe_non_collection_latest_state(row_list)}
    return [
        row
        for row in row_list
        if _non_collection_target_event_type(row) is None or id(row) in non_collection_latest_ids
    ]


def build_event_rows(envelopes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Derive latest-value/event rows from normalized result envelopes."""
    rows: list[dict[str, Any]] = []
    for envelope in envelopes:
        metadata = envelope.get("metadata") or {}
        protocol = normalized_protocol(envelope.get("protocol"))
        metric_id = str(envelope.get("metric_id"))
        metric_name = str(metadata.get("name") or metric_id)
        numeric = _num(envelope)
        result_status = str(_value(envelope.get("status")) or "OK")
        severity = "INFO"
        is_breach = False
        event_type = None
        failure_family = None
        source_protocol = protocol or None
        recover_collection_failure = numeric is not None
        recover_non_collection_event = False
        display_value = "N/A" if numeric is None else str(numeric)
        message = f"Metric {metric_name} is OK. Value: {display_value}"
        collection_recovery_message = f"Metric collection recovered. Value: {display_value}"

        if is_snmp_no_response_failure(protocol, result_status, envelope.get("error") or {}):
            severity = "WARNING"
            is_breach = True
            event_type = EVENT_TYPE_COLLECTION_FAILURE
            failure_family = FAILURE_FAMILY_SNMP_NO_RESPONSE
            source_protocol = SOURCE_PROTOCOL_SNMP
            message = collection_failure_message(envelope.get("error") or {}, result_status)
        elif result_status not in {"OK", "WARNING", "CRITICAL"}:
            severity = _base_severity(metadata)
            is_breach = True
            event_type = EVENT_TYPE_COLLECTION_FAILURE
            message = collection_failure_message(envelope.get("error") or {}, result_status)
        elif numeric is not None:
            availability_source = _availability_source(metadata)
            availability = protocol == "ICMP" and availability_source is not None
            if availability and numeric == 0:
                severity = _base_severity(metadata)
                is_breach = True
                event_type = EVENT_TYPE_AVAILABILITY
                message = f"Service/Host Down: {metric_name}"
            elif not availability:
                op = str(metadata.get("operator") or ">=")
                if metadata.get("critical") is not None and _check(numeric, float(metadata["critical"]), op):
                    severity = "CRITICAL"
                    is_breach = True
                    event_type = EVENT_TYPE_THRESHOLD_BREACH
                    message = f"Critical Threshold Breached: {display_value} {op} {metadata['critical']}"
                elif metadata.get("warning") is not None and _check(numeric, float(metadata["warning"]), op):
                    severity = "WARNING"
                    is_breach = True
                    event_type = EVENT_TYPE_THRESHOLD_BREACH
                    message = f"Warning Threshold Breached: {display_value} {op} {metadata['warning']}"

        recover_non_collection_event = numeric is not None and not is_breach

        rows.append({
            "idempotency_key": envelope.get("idempotency_key"),
            "ci_id": envelope.get("ci_id"),
            "metric_id": metric_id,
            "value": display_value,
            "status": severity if is_breach else "OK",
            "severity": severity,
            "message": message,
            "is_breach": is_breach,
            "event_type": event_type,
            "failure_family": failure_family,
            "source_protocol": source_protocol,
            "availability_source": _availability_source(metadata),
            "recover_collection_failure": recover_collection_failure,
            "recover_non_collection_event": recover_non_collection_event,
            "collection_recovery_message": collection_recovery_message,
            "observed_at": _value(envelope.get("observed_at")),
            "correlation_type": metadata.get("correlation_type") or "ROOT",
            "propagated_from": metadata.get("propagated_from"),
            "root_cause_event_id": metadata.get("root_cause_event_id"),
            "root_cause_ci_id": metadata.get("root_cause_ci_id") or envelope.get("ci_id"),
            "business_service_id": metadata.get("business_service_id"),
            "business_service_name": metadata.get("business_service_name"),
            "business_service_tier": metadata.get("business_service_tier"),
            "owner_t1": metadata.get("owner_t1"),
            "owner_t2": metadata.get("owner_t2"),
            "owner_t3": metadata.get("owner_t3"),
            "impacted_users": metadata.get("impacted_users"),
            "site": metadata.get("site") or metadata.get("site_id"),
            "service_catalog_id": metadata.get("service_catalog_id"),
            "service_category": metadata.get("service_category"),
            "service_tier": metadata.get("service_tier"),
            "sla_minutes": metadata.get("sla_minutes"),
        })
    return rows


def batch_update_events(driver, envelopes: Iterable[Mapping[str, Any]]) -> int:
    """Apply latest metric/result/event updates with batched UNWIND queries."""
    rows = build_event_rows(envelopes)
    if not rows:
        return 0
    latest_metric_rows = _latest_metric_rows(rows)
    collection_failure_rows = _collection_failure_event_rows(rows)
    non_collection_state_rows = _dedupe_non_collection_latest_state(rows)
    non_collection_event_rows = _non_collection_event_rows(non_collection_state_rows)
    with driver.session() as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (n:CI {id: row.ci_id})
            MATCH (m:MetricDef {id: row.metric_id})
            MERGE (n)-[r:HAS_METRIC]->(m)
            SET r.last_value = row.value, r.last_updated = datetime(), r.status = row.status, r.last_message = row.message
            CREATE (res:MetricResult {timestamp: datetime(), value: row.value, status: row.status})
            CREATE (n)-[:HAS_RESULT]->(res)
            CREATE (res)-[:FOR_METRIC]->(m)
            """,
            rows=latest_metric_rows,
        )
        session.run(
            """
            UNWIND $rows AS row
            WITH row WHERE row.is_breach AND row.event_type = 'COLLECTION_FAILURE'
            MATCH (n:CI {id: row.ci_id})
            MATCH (m:MetricDef {id: row.metric_id})
            OPTIONAL MATCH (existing:Event {ci_id: row.ci_id, metric_id: row.metric_id})
            WHERE existing.status IN ['OPEN', 'ACK', 'RECOVERED']
              AND (
                existing.event_type = row.event_type
                OR (existing.event_type IS NULL AND existing.message STARTS WITH 'Metric Collection Failed:')
              )
              AND (
                (row.failure_family IS NOT NULL AND (existing.failure_family = row.failure_family OR existing.failure_family IS NULL))
                OR (row.failure_family IS NULL AND existing.failure_family IS NULL)
              )
              AND (row.source_protocol IS NULL OR existing.source_protocol IS NULL OR toUpper(existing.source_protocol) = row.source_protocol)
            WITH row, n, m, head(collect(existing)) AS existing
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                CREATE (created:Event {
                    id: randomUUID(), ci_id: row.ci_id, metric_id: row.metric_id, status: 'OPEN',
                    event_type: row.event_type, failure_family: row.failure_family, source_protocol: row.source_protocol,
                    availability_source: row.availability_source,
                    severity: row.severity, message: row.message, created_at: datetime(), last_seen: datetime(), ack: false,
                    correlation_type: row.correlation_type, propagated_from: row.propagated_from, root_cause_ci_id: row.root_cause_ci_id,
                    business_service_id: row.business_service_id, business_service_name: row.business_service_name,
                    business_service_tier: row.business_service_tier, owner_t1: row.owner_t1, owner_t2: row.owner_t2,
                    owner_t3: row.owner_t3, impacted_users: row.impacted_users, site: row.site,
                    service_catalog_id: row.service_catalog_id, service_category: row.service_category,
                    service_tier: row.service_tier, sla_minutes: row.sla_minutes
                })
                MERGE (n)-[:HAS_EVENT]->(created)
                MERGE (created)-[:TRIGGERED_BY]->(m)
            )
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
                SET existing.status = 'OPEN', existing.severity = row.severity, existing.message = row.message,
                    existing.last_seen = datetime(), existing.ack = false, existing.recovered_at = NULL,
                    existing.event_type = row.event_type, existing.failure_family = row.failure_family,
                    existing.source_protocol = row.source_protocol,
                    existing.availability_source = row.availability_source
                MERGE (n)-[:HAS_EVENT]->(existing)
                MERGE (existing)-[:TRIGGERED_BY]->(m)
            )
            """,
            rows=collection_failure_rows,
        )
        session.run(
            """
            UNWIND $rows AS row
            WITH row WHERE row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'
            MATCH (n:CI {id: row.ci_id})
            MATCH (m:MetricDef {id: row.metric_id})
            OPTIONAL MATCH (n)-[:HAS_EVENT]->(existing:Event {metric_id: row.metric_id, event_type: row.event_type})
            WHERE existing.status IN ['OPEN', 'ACK']
              AND coalesce(existing.correlation_type, 'ROOT') = coalesce(row.correlation_type, 'ROOT')
              AND (
                coalesce(row.correlation_type, 'ROOT') <> 'PROPAGATED'
                OR (
                  (row.propagated_from IS NULL OR existing.propagated_from = row.propagated_from)
                  AND (row.root_cause_event_id IS NULL OR existing.root_cause_event_id = row.root_cause_event_id)
                  AND (row.root_cause_ci_id IS NULL OR existing.root_cause_ci_id = row.root_cause_ci_id)
                )
              )
            WITH row, n, m, head(collect(existing)) AS existing
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                CREATE (created:Event {
                    id: randomUUID(), ci_id: row.ci_id, metric_id: row.metric_id, event_type: row.event_type, status: 'OPEN',
                    severity: row.severity, message: row.message, source_protocol: row.source_protocol,
                    availability_source: row.availability_source, created_at: datetime(), last_seen: datetime(), ack: false,
                    correlation_type: row.correlation_type, propagated_from: row.propagated_from,
                    root_cause_event_id: row.root_cause_event_id, root_cause_ci_id: row.root_cause_ci_id,
                    business_service_id: row.business_service_id,
                    business_service_name: row.business_service_name, business_service_tier: row.business_service_tier,
                    owner_t1: row.owner_t1, owner_t2: row.owner_t2, owner_t3: row.owner_t3,
                    impacted_users: row.impacted_users, site: row.site, service_catalog_id: row.service_catalog_id,
                    service_category: row.service_category, service_tier: row.service_tier, sla_minutes: row.sla_minutes
                })
                MERGE (n)-[:HAS_EVENT]->(created)
                MERGE (created)-[:TRIGGERED_BY]->(m)
            )
            FOREACH (_ IN CASE WHEN existing IS NULL THEN [] ELSE [1] END |
                SET existing.severity = row.severity,
                    existing.message = row.message,
                    existing.source_protocol = row.source_protocol,
                    existing.availability_source = row.availability_source,
                    existing.created_at = coalesce(existing.created_at, existing.last_seen, datetime()),
                    existing.last_seen = datetime(),
                    existing.ack = CASE WHEN existing.status = 'ACK' THEN existing.ack ELSE false END,
                    existing.recovered_at = NULL,
                    existing.correlation_type = coalesce(existing.correlation_type, row.correlation_type),
                    existing.propagated_from = coalesce(existing.propagated_from, row.propagated_from),
                    existing.root_cause_event_id = coalesce(existing.root_cause_event_id, row.root_cause_event_id),
                    existing.root_cause_ci_id = coalesce(existing.root_cause_ci_id, row.root_cause_ci_id),
                    existing.business_service_id = coalesce(existing.business_service_id, row.business_service_id),
                    existing.business_service_name = coalesce(existing.business_service_name, row.business_service_name),
                    existing.business_service_tier = coalesce(existing.business_service_tier, row.business_service_tier),
                    existing.owner_t1 = coalesce(existing.owner_t1, row.owner_t1),
                    existing.owner_t2 = coalesce(existing.owner_t2, row.owner_t2),
                    existing.owner_t3 = coalesce(existing.owner_t3, row.owner_t3),
                    existing.impacted_users = coalesce(existing.impacted_users, row.impacted_users),
                    existing.site = coalesce(existing.site, row.site),
                    existing.service_catalog_id = coalesce(existing.service_catalog_id, row.service_catalog_id),
                    existing.service_category = coalesce(existing.service_category, row.service_category),
                    existing.service_tier = coalesce(existing.service_tier, row.service_tier),
                    existing.sla_minutes = coalesce(existing.sla_minutes, row.sla_minutes)
                MERGE (n)-[:HAS_EVENT]->(existing)
                MERGE (existing)-[:TRIGGERED_BY]->(m)
            )
            """,
            rows=non_collection_event_rows,
        )
        session.run(
            """
            UNWIND $rows AS row
            WITH row WHERE row.recover_collection_failure
            MATCH (:CI {id: row.ci_id})-[:HAS_EVENT]->(e:Event {metric_id: row.metric_id})
            WHERE e.status IN ['OPEN', 'ACK']
              AND (
                e.event_type = 'COLLECTION_FAILURE'
                OR (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')
              )
              AND (row.source_protocol IS NULL OR e.source_protocol IS NULL OR toUpper(e.source_protocol) = row.source_protocol)
              AND (
                row.source_protocol <> 'SNMP'
                OR e.failure_family = 'SNMP_NO_RESPONSE'
                OR e.failure_family IS NULL
              )
            SET e.created_at = coalesce(e.created_at, e.last_seen, datetime()),
                e.status = 'RECOVERED', e.recovered_at = datetime(), e.message = row.collection_recovery_message
            WITH e
            CALL {
                WITH e
                MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
                WHERE pe.root_cause_ci_id = e.ci_id
                  AND pe.correlation_type = 'PROPAGATED'
                  AND pe.status IN ['OPEN', 'ACK']
                  AND coalesce(m.can_propagate, true) = true
                SET pe.created_at = coalesce(pe.created_at, pe.last_seen, datetime()),
                    pe.status = 'RECOVERED', pe.recovered_at = datetime()
                RETURN count(pe) AS propagated_recovered
            }
            RETURN e
            """,
            rows=rows,
        )
        session.run(
            """
            UNWIND $rows AS row
            WITH row WHERE row.recover_non_collection_event
            MATCH (:CI {id: row.ci_id})-[:HAS_EVENT]->(e:Event {metric_id: row.metric_id})
            WHERE e.status IN ['OPEN', 'ACK']
              AND coalesce(e.correlation_type, 'ROOT') = 'ROOT'
              AND (
                (
                  row.source_protocol = 'ICMP'
                  AND (
                    e.event_type = 'AVAILABILITY'
                    OR (e.event_type = 'THRESHOLD_BREACH' AND row.metric_id = e.metric_id)
                  )
                  AND (e.source_protocol IS NULL OR toUpper(e.source_protocol) = row.source_protocol)
                )
                OR (
                  coalesce(row.source_protocol, '') <> 'ICMP'
                  AND (e.event_type IS NULL OR e.event_type <> 'COLLECTION_FAILURE')
                  AND NOT (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')
                )
              )
            SET e.created_at = coalesce(e.created_at, e.last_seen, datetime()),
                e.status = 'RECOVERED', e.recovered_at = datetime(), e.message = row.message
            WITH e
            CALL {
                WITH e
                MATCH (pe:Event)-[:TRIGGERED_BY]->(m:MetricDef)
                WHERE pe.propagated_from = e.id
                  AND pe.root_cause_ci_id = e.ci_id
                  AND pe.correlation_type = 'PROPAGATED'
                  AND pe.status IN ['OPEN', 'ACK']
                  AND coalesce(m.can_propagate, true) = true
                SET pe.created_at = coalesce(pe.created_at, pe.last_seen, datetime()),
                    pe.status = 'RECOVERED', pe.recovered_at = datetime()
                RETURN count(pe) AS propagated_recovered
            }
            RETURN e
            """,
            rows=non_collection_state_rows,
        )
    return len(rows)
