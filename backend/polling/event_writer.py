"""Batch-friendly Neo4j event updates for polling writer results."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping
from uuid import UUID


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


def build_event_rows(envelopes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Derive latest-value/event rows from normalized result envelopes."""
    rows: list[dict[str, Any]] = []
    for envelope in envelopes:
        metadata = envelope.get("metadata") or {}
        protocol = str(_value(envelope.get("protocol")) or "")
        metric_id = str(envelope.get("metric_id"))
        metric_name = str(metadata.get("name") or metric_id)
        numeric = _num(envelope)
        result_status = str(_value(envelope.get("status")) or "OK")
        severity = "INFO"
        is_breach = False
        display_value = "N/A" if numeric is None else str(numeric)
        message = f"Metric {metric_name} is OK. Value: {display_value}"

        if result_status not in {"OK", "WARNING", "CRITICAL"}:
            severity = _base_severity(metadata)
            is_breach = True
            message = f"Metric Collection Failed: {(envelope.get('error') or {}).get('message') or result_status}"
        elif numeric is not None:
            availability = protocol == "ICMP" or metric_name == "mariadb-GS"
            if availability and numeric == 0:
                severity = _base_severity(metadata)
                is_breach = True
                message = f"Service/Host Down: {metric_name}"
            elif not availability:
                op = str(metadata.get("operator") or ">=")
                if metadata.get("critical") is not None and _check(numeric, float(metadata["critical"]), op):
                    severity = "CRITICAL"
                    is_breach = True
                    message = f"Critical Threshold Breached: {display_value} {op} {metadata['critical']}"
                elif metadata.get("warning") is not None and _check(numeric, float(metadata["warning"]), op):
                    severity = "WARNING"
                    is_breach = True
                    message = f"Warning Threshold Breached: {display_value} {op} {metadata['warning']}"

        rows.append({
            "idempotency_key": envelope.get("idempotency_key"),
            "ci_id": envelope.get("ci_id"),
            "metric_id": metric_id,
            "value": display_value,
            "status": severity if is_breach else "OK",
            "severity": severity,
            "message": message,
            "is_breach": is_breach,
            "observed_at": _value(envelope.get("observed_at")),
            "correlation_type": metadata.get("correlation_type") or "ROOT",
            "propagated_from": metadata.get("propagated_from"),
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
            rows=rows,
        )
        session.run(
            """
            UNWIND $rows AS row
            WITH row WHERE row.is_breach
            MATCH (n:CI {id: row.ci_id})
            MATCH (m:MetricDef {id: row.metric_id})
            MERGE (e:Event {ci_id: row.ci_id, metric_id: row.metric_id, status: 'OPEN'})
            SET e.severity = row.severity,
                e.message = row.message,
                e.last_seen = datetime(),
                e.ack = false,
                e.correlation_type = coalesce(e.correlation_type, row.correlation_type),
                e.propagated_from = coalesce(e.propagated_from, row.propagated_from),
                e.root_cause_ci_id = coalesce(e.root_cause_ci_id, row.root_cause_ci_id),
                e.business_service_id = coalesce(e.business_service_id, row.business_service_id),
                e.business_service_name = coalesce(e.business_service_name, row.business_service_name),
                e.business_service_tier = coalesce(e.business_service_tier, row.business_service_tier),
                e.owner_t1 = coalesce(e.owner_t1, row.owner_t1),
                e.owner_t2 = coalesce(e.owner_t2, row.owner_t2),
                e.owner_t3 = coalesce(e.owner_t3, row.owner_t3),
                e.impacted_users = coalesce(e.impacted_users, row.impacted_users),
                e.site = coalesce(e.site, row.site),
                e.service_catalog_id = coalesce(e.service_catalog_id, row.service_catalog_id),
                e.service_category = coalesce(e.service_category, row.service_category),
                e.service_tier = coalesce(e.service_tier, row.service_tier),
                e.sla_minutes = coalesce(e.sla_minutes, row.sla_minutes)
            MERGE (n)-[:HAS_EVENT]->(e)
            MERGE (e)-[:TRIGGERED_BY]->(m)
            """,
            rows=rows,
        )
        session.run(
            """
            UNWIND $rows AS row
            WITH row WHERE NOT row.is_breach
            MATCH (:CI {id: row.ci_id})-[:HAS_EVENT]->(e:Event {metric_id: row.metric_id})
            WHERE e.status IN ['OPEN', 'ACK']
            SET e.status = 'RECOVERED', e.recovered_at = datetime(), e.message = row.message
            WITH e
            CALL {
                WITH e
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
            rows=rows,
        )
    return len(rows)
