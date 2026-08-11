from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from database import get_db
from fastapi import HTTPException
from services.snmp_service import run_diagnostic

logger = logging.getLogger(__name__)


def _serialize_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _node_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return {key: _serialize_value(value[key]) for key in value.keys()}  # noqa: SIM118


def _record_value(record: Any, key: str) -> Any:
    if record is None:
        return None
    try:
        return record[key]
    except Exception:
        return record.get(key) if hasattr(record, "get") else None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _compute_sla_remaining_minutes(
    created_at: Any, sla_minutes: int | None, now: datetime | None = None
) -> int | None:
    if sla_minutes is None:
        return None
    created_dt = _parse_datetime(created_at)
    if created_dt is None:
        return None
    reference = now or datetime.now(UTC)
    age_minutes = int((reference - created_dt).total_seconds() // 60)
    return int(sla_minutes) - age_minutes


def _clean_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _strip_known_audit_prefixes(message: str | None) -> str:
    if not message:
        return ""
    cleaned = message.strip()
    while cleaned.startswith("["):
        closing_idx = cleaned.find("]")
        if closing_idx == -1:
            break
        prefix = cleaned[: closing_idx + 1]
        if not prefix.startswith(
            (
                "[OWNERSHIP]",
                "[CIERRE",
                "[AUDIT]",
            )
        ):
            break
        cleaned = cleaned[closing_idx + 1 :].lstrip(" -:\u2014")
    return cleaned


def _build_ack_audit_message(user: str) -> str:
    return f"[AUDIT][OWNERSHIP] Caso tomado por {user}"


def _normalize_ack_note(comment_message: str | None) -> str | None:
    if not comment_message:
        return None
    cleaned = comment_message.strip()
    if cleaned.startswith(("[OWNERSHIP]", "[AUDIT][OWNERSHIP]")):
        return None
    normalized = _strip_known_audit_prefixes(cleaned)
    return normalized or None


def _build_close_audit_message(user: str, forced: bool, comment_message: str | None) -> str:
    detail = _strip_known_audit_prefixes(comment_message)
    if forced:
        lines = [f"[AUDIT][FORCED_CLOSE] Cierre forzado por {user}"]
        if detail:
            lines.append(detail)
        return "\n".join(lines)

    lines = [f"[AUDIT][CLOSE] Evento cerrado por {user}"]
    if detail:
        lines.append(detail)
    return "\n".join(lines)


def _optional_contract(payload: dict[str, Any], required_keys: set[str]) -> dict[str, Any] | None:
    cleaned = _clean_dict(payload)
    if not required_keys.issubset(cleaned):
        return None
    return cleaned


def _build_external_ticket_ref(event_data: dict[str, Any]) -> dict[str, Any] | None:
    system = event_data.get("external_ticket_system")
    key = event_data.get("external_ticket_key")
    if system not in {"Jira", "ServiceNow"} or not key:
        return None
    return _clean_dict(
        {
            "system": system,
            "key": key,
            "status": event_data.get("external_ticket_status"),
        }
    )


def _raise_event_not_found(event_id: str) -> None:
    raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")


def _build_event_summary(
    event_data: dict[str, Any], ci_data: dict[str, Any], metric_data: dict[str, Any]
) -> dict[str, Any]:
    summary = {key: _serialize_value(value) for key, value in event_data.items()}
    if summary.get("created_at") is None:
        summary["created_at"] = (
            summary.get("last_seen") or summary.get("recovered_at") or summary.get("closed_at")
        )
    summary["ci_node_id"] = ci_data.get("id")
    summary["ci_name"] = ci_data.get("name")
    summary["ci_hostname"] = ci_data.get("ip")
    summary["ci_location_name"] = ci_data.get("location_name")
    metric_name = (
        metric_data.get("name")
        or metric_data.get("id")
        or event_data.get("metric_name")
        or event_data.get("metric_id")
        or event_data.get("event_type")
    )
    metric_protocol = metric_data.get("protocol") or event_data.get("source_protocol")
    if metric_name:
        summary["metric_name"] = metric_name
    if metric_protocol:
        summary["metric_protocol"] = metric_protocol
    return summary


def _public_event_summary(summary: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "id",
        "ci_id",
        "metric_id",
        "status",
        "severity",
        "message",
        "created_at",
        "last_seen",
        "ack",
        "ack_at",
        "closed_at",
        "recovered_at",
        "ci_name",
        "ci_node_id",
        "ci_hostname",
        "ci_location_name",
        "metric_name",
        "metric_protocol",
        "propagated_from",
        "correlation_type",
        "root_cause_ci_id",
        "event_type",
        "source_protocol",
        # P2 REQ-001/002: expose the ROOT's affected-CI blast radius without
        # smuggling it through the `propagated` derived flag. Both fields are
        # dropped on the way back out when they are None/empty (the existing
        # `value is not None` filter handles that).
        "affected_ci_ids",
        "affected_count",
    }
    result = {
        key: value for key, value in summary.items() if key in allowed_keys and value is not None
    }
    # P2 REQ-001/002: normalize the Neo4j writer key `affected_ci_count` to
    # the public JSON key `affected_count` so the Pydantic surface stays
    # consistent with the spec.
    if "affected_ci_count" in summary and summary["affected_ci_count"] is not None:
        result["affected_count"] = summary["affected_ci_count"]
    # P2 REQ-001/010: drop the affected-CI fields when the legacy ROOT has
    # no dependents. Empty list / zero count collapse to "missing" so the
    # legacy JSON contract is preserved.
    if not result.get("affected_ci_ids"):
        result.pop("affected_ci_ids", None)
    if not result.get("affected_count"):
        result.pop("affected_count", None)
    # Add computed propagated flag only when correlation_type is PROPAGATED
    if summary.get("correlation_type") == "PROPAGATED":
        result["propagated"] = True
    return result


def _extract_structured_close_fields(comment_message: str | None) -> tuple[str, str]:
    detail = _strip_known_audit_prefixes(comment_message)
    root_cause = ""
    note_lines: list[str] = []
    collecting_note = False

    for raw_line in detail.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if lowered.startswith(("causa raíz:", "causa raiz:")):
            root_cause = line.split(":", 1)[1].strip()
            collecting_note = False
            continue
        if lowered.startswith("nota:"):
            note_lines = [line.split(":", 1)[1].strip()]
            collecting_note = True
            continue
        if collecting_note:
            note_lines.append(line)

    note = "\n".join(part for part in note_lines if part).strip()
    return root_cause, note


def _validate_close_request(forced: bool, comment_message: str | None) -> None:
    detail = _strip_known_audit_prefixes(comment_message)
    if forced:
        # Strip the "Motivo:" label the frontend adds before checking for content
        if detail and detail.lower().startswith("motivo:"):
            detail = detail.split(":", 1)[1].strip()
        if not detail:
            raise HTTPException(
                status_code=400,
                detail="Forced close requires a reason in comment_message",
            )
        return

    root_cause, note = _extract_structured_close_fields(comment_message)
    if not root_cause:
        raise HTTPException(
            status_code=400,
            detail="Normal close requires 'Causa raíz' in comment_message",
        )
    if len(note) < 20:
        raise HTTPException(
            status_code=400,
            detail="Normal close requires a 'Nota' of at least 20 characters",
        )


def _pick_value(snapshot_value: Any, resolved_value: Any) -> tuple[Any, str | None]:
    if snapshot_value is not None:
        return snapshot_value, "snapshot"
    if resolved_value is not None:
        return resolved_value, "resolved"
    return None, None


def _build_business_context(
    event_data: dict[str, Any],
    ci_data: dict[str, Any],
    business_service: dict[str, Any],
    service_catalog: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    business_service_id, bs_id_source = _pick_value(
        event_data.get("business_service_id"), business_service.get("id")
    )
    business_service_name, bs_name_source = _pick_value(
        event_data.get("business_service_name"), business_service.get("name")
    )
    business_service_tier, business_service_tier_source = _pick_value(
        event_data.get("business_service_tier"), business_service.get("tier")
    )
    owner_t1, owner_t1_source = _pick_value(
        event_data.get("owner_t1"), business_service.get("owner_t1")
    )
    owner_t2, owner_t2_source = _pick_value(
        event_data.get("owner_t2"), business_service.get("owner_t2")
    )
    owner_t3, owner_t3_source = _pick_value(
        event_data.get("owner_t3"), business_service.get("owner_t3")
    )
    impacted_users, impacted_users_source = _pick_value(
        event_data.get("impacted_users"), business_service.get("impacted_users_count")
    )
    site, site_source = _pick_value(event_data.get("site"), ci_data.get("location_name"))
    service_catalog_id, sc_id_source = _pick_value(
        event_data.get("service_catalog_id"), service_catalog.get("id")
    )
    category, category_source = _pick_value(
        event_data.get("service_category"), service_catalog.get("category")
    )
    catalog_tier, catalog_tier_source = _pick_value(
        event_data.get("service_tier"), service_catalog.get("service_tier")
    )
    sla_minutes, sla_source = _pick_value(
        event_data.get("sla_minutes"), service_catalog.get("sla_minutes")
    )

    sources = {
        source
        for source in [
            bs_id_source,
            bs_name_source,
            business_service_tier_source,
            owner_t1_source,
            owner_t2_source,
            owner_t3_source,
            impacted_users_source,
            site_source,
            sc_id_source,
            category_source,
            catalog_tier_source,
            sla_source,
        ]
        if source is not None
    }

    if not sources:
        source_state = "unavailable"
    elif sources == {"snapshot"}:
        source_state = "snapshot"
    elif sources == {"resolved"}:
        source_state = "resolved"
    else:
        source_state = "mixed"

    business_context = {
        "source": source_state,
        "business_service": _optional_contract(
            {
                "id": business_service_id,
                "name": business_service_name,
                "tier": business_service_tier,
                "owner_t1": owner_t1,
                "owner_t2": owner_t2,
                "owner_t3": owner_t3,
            },
            {"id", "name"},
        ),
        "service_catalog": _optional_contract(
            {
                "id": service_catalog_id,
                "category": category,
                "service_tier": catalog_tier,
                "sla_minutes": sla_minutes,
            },
            {"id", "category"},
        ),
        "impacted_users": impacted_users,
        "sla_remaining_minutes": _compute_sla_remaining_minutes(
            event_data.get("created_at"), sla_minutes, now=now
        ),
        "site": site,
    }
    return business_context


def build_event_detail_response(record: Any, now: datetime | None = None) -> dict[str, Any]:
    event_data = _node_to_dict(_record_value(record, "e"))
    ci_data = _node_to_dict(_record_value(record, "ci"))
    metric_data = _node_to_dict(_record_value(record, "m"))
    business_service = _node_to_dict(_record_value(record, "bs"))
    service_catalog = _node_to_dict(_record_value(record, "sc"))

    summary = _build_event_summary(event_data, ci_data, metric_data)
    business_context = _build_business_context(
        event_data, ci_data, business_service, service_catalog, now=now
    )
    business_service_context = business_context.get("business_service") or {}
    escalation_tier = event_data.get("escalation_tier") or business_service_context.get("tier")

    return {
        "event": {
            **summary,
            "ci_ref": {
                "id": ci_data.get("id") or summary.get("ci_id"),
                "label": ci_data.get("name"),
                "hostname": ci_data.get("ip"),
                "location_name": ci_data.get("location_name"),
            },
        },
        "business_context": business_context,
        "itsm_context": {
            "assignment_state": (
                "assigned" if event_data.get("ack") and event_data.get("ack_by") else "unassigned"
            ),
            "assigned_to": event_data.get("ack_by"),
            "opened_by": "system",
            "escalation_tier": escalation_tier if escalation_tier in {"T1", "T2", "T3"} else None,
            "external_ticket": _build_external_ticket_ref(event_data),
        },
    }


def _resolve_availability_window(
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime, datetime]:
    generated_at = now or datetime.now(UTC)
    window_end = end or generated_at
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=UTC)
    window_start = start or (window_end - timedelta(days=30))
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=UTC)
    if window_start > window_end:
        raise HTTPException(status_code=400, detail="start must be before end")
    return window_start, window_end, generated_at


_CI_CANONICAL_FIELDS = {
    "id",
    "name",
    "label",
    "category",
    "layer",
    "type",
    "status",
    "ip",
    "location_name",
    "owner",
    "brand",
    "model",
    "serialNumber",
    "firmwareVersion",
    "pollingInterval",
}

_SENSITIVE_CI_KEY_PARTS = (
    "credential",
    "password",
    "passphrase",
    "passwd",
    "pwd",
    "secret",
    "token",
    "snmp",
    "community",
    "auth",
    "priv",
    "username",
    "user_name",
    "login",
    "user",
)


def _is_authoritative_availability_event(event_data: dict[str, Any]) -> bool:
    event_type = str(event_data.get("event_type") or "").upper()
    availability_source = str(event_data.get("availability_source") or "").upper()
    correlation_type = str(event_data.get("correlation_type") or "ROOT").upper()
    return (
        event_type == "AVAILABILITY"
        and availability_source in {"PING", "ICMP"}
        and correlation_type != "PROPAGATED"
    )


def _availability_group_key(event_data: dict[str, Any]) -> tuple[str, str] | None:
    if not _is_authoritative_availability_event(event_data):
        return None
    ci_id = event_data.get("ci_id")
    event_type = event_data.get("event_type")
    if not ci_id or not event_type:
        return None
    return str(ci_id), str(event_type)


def _empty_snmp_coverage_summary() -> dict[str, Any]:
    return {
        "total_ci_with_snmp": 0,
        "functional_ci": 0,
        "failing_ci": 0,
        "no_response_ci": 0,
        "no_response_event_count": 0,
        "functional_percentage": None,
        "failing_percentage": None,
    }


def _build_snmp_coverage_summary(record: Any) -> dict[str, Any]:
    summary = _empty_snmp_coverage_summary()
    if record is None:
        return summary

    total = int(record.get("total_ci_with_snmp") or 0)
    functional = int(record.get("functional_ci") or 0)
    failing = int(record.get("failing_ci") or 0)
    no_response = int(record.get("no_response_ci") or 0)
    no_response_events = int(record.get("no_response_event_count") or 0)
    summary.update(
        {
            "total_ci_with_snmp": total,
            "functional_ci": functional,
            "failing_ci": failing,
            "no_response_ci": no_response,
            "no_response_event_count": no_response_events,
        }
    )
    if total > 0:
        summary["functional_percentage"] = round(functional / total * 100, 4)
        summary["failing_percentage"] = round(failing / total * 100, 4)
    return summary


def _isoformat_or_none(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.isoformat()
    if value is None:
        return None
    return str(value)


def _snmp_no_response_event_summary(event_data: dict[str, Any]) -> dict[str, Any]:
    return _clean_dict(
        {
            "id": event_data.get("id"),
            "message": event_data.get("message"),
            "status": event_data.get("status"),
            "created_at": _isoformat_or_none(event_data.get("created_at")),
            "last_seen": _isoformat_or_none(event_data.get("last_seen")),
        }
    )


def _is_sensitive_ci_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in _SENSITIVE_CI_KEY_PARTS)


def _json_safe_ci_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        safe_items = [_json_safe_ci_value(item) for item in value]
        return [item for item in safe_items if item is not None]
    if isinstance(value, dict):
        sanitized = _sanitize_ci_metadata(value)
        return sanitized or None
    return None


def _sanitize_ci_metadata(ci_data: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in ci_data.items():
        if key in _CI_CANONICAL_FIELDS or _is_sensitive_ci_key(key):
            continue
        safe_value = _json_safe_ci_value(value)
        if safe_value is not None:
            metadata[key] = safe_value
    return metadata


def _build_availability_ci_metadata(
    ci_data: dict[str, Any], category: str | None = None
) -> dict[str, Any] | None:
    if not ci_data:
        return None
    ci_type = category or ci_data.get("type") or ci_data.get("layer")
    metadata = _sanitize_ci_metadata(ci_data)
    payload = _clean_dict(
        {
            "id": ci_data.get("id"),
            "label": ci_data.get("name") or ci_data.get("label"),
            "category": category,
            "type": ci_type,
            "status": ci_data.get("status"),
            "ip": ci_data.get("ip"),
            "location_name": ci_data.get("location_name"),
            "owner": ci_data.get("owner"),
            "brand": ci_data.get("brand"),
            "model": ci_data.get("model"),
            "serialNumber": ci_data.get("serialNumber"),
            "firmwareVersion": ci_data.get("firmwareVersion"),
            "pollingInterval": ci_data.get("pollingInterval"),
            "metadata": metadata or None,
        }
    )
    return payload or None


def _merge_availability_ci_metadata(
    existing: dict[str, Any] | None, incoming: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not existing:
        return incoming
    if not incoming:
        return existing
    incoming_values = {key: value for key, value in incoming.items() if value is not None}
    merged = {**existing, **incoming_values}
    existing_raw_metadata = existing.get("metadata")
    incoming_raw_metadata = incoming.get("metadata")
    existing_metadata: dict[str, Any] = (
        existing_raw_metadata if isinstance(existing_raw_metadata, dict) else {}
    )
    incoming_metadata: dict[str, Any] = (
        incoming_raw_metadata if isinstance(incoming_raw_metadata, dict) else {}
    )
    metadata = {**existing_metadata, **incoming_metadata}
    if metadata:
        merged["metadata"] = metadata
    return merged


def get_availability_report(
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return MTTR/MTBF availability metrics grouped by CI + event type.

    MTTR uses technical recovery (`recovered_at - created_at`). MTBF uses the
    average completed operating interval: an eligible failure start minus the
    prior eligible failure's recovery. Active incidents never complete an interval.
        Incomplete legacy events
    are excluded from MTTR; active events are reported separately as current
    downtime where possible.
    """
    window_start, window_end, generated_at = _resolve_availability_window(
        start=start,
        end=end,
        now=now,
    )
    window_seconds = max((window_end - window_start).total_seconds(), 0)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    snmp_coverage = _empty_snmp_coverage_summary()

    def ensure_group(
        key: tuple[str, str],
        ci_name: str | None = None,
        ci_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = groups.setdefault(
            key,
            {
                "ci_id": key[0],
                "ci_name": ci_name,
                "event_type": key[1],
                "failure_starts": [],
                "completed_incidents": [],
                "repair_seconds": [],
                "downtime_seconds": 0.0,
                "active_events": 0,
                "active_downtime_seconds": 0.0,
                "ci": ci_metadata,
            },
        )
        if ci_name and not row.get("ci_name"):
            row["ci_name"] = ci_name
        row["ci"] = _merge_availability_ci_metadata(row.get("ci"), ci_metadata)
        return row

    driver = get_db()
    with driver.session() as session:
        recovered_result = session.run(
            """
            MATCH (e:Event)<-[:HAS_EVENT]-(ci:CI)
            WHERE e.created_at IS NOT NULL
              AND e.recovered_at IS NOT NULL
              AND e.event_type = 'AVAILABILITY'
              AND e.availability_source IN ['PING', 'ICMP']
              AND toUpper(coalesce(e.correlation_type, 'ROOT')) <> 'PROPAGATED'
              AND NOT e.status IN ['OPEN', 'ACK']
              AND e.created_at <= $window_end
              AND e.recovered_at <= $window_end
            OPTIONAL MATCH (ci)-[:CATEGORIZED_AS]->(cat:Category)
            WITH e, ci, head(collect(DISTINCT cat.name)) AS category
            RETURN e, ci, category
            ORDER BY e.created_at ASC
            """,
            window_start=window_start,
            window_end=window_end,
        )
        for record in recovered_result:
            event_data = _node_to_dict(_record_value(record, "e"))
            ci_data = _node_to_dict(_record_value(record, "ci"))
            key = _availability_group_key(event_data)
            if key is None:
                continue
            created_at = _parse_datetime(event_data.get("created_at"))
            recovered_at = _parse_datetime(event_data.get("recovered_at"))
            if created_at is None or recovered_at is None:
                continue
            if created_at > window_end:
                continue
            if recovered_at < created_at or recovered_at > window_end:
                continue

            ci_metadata = _build_availability_ci_metadata(
                ci_data, _record_value(record, "category")
            )
            row = ensure_group(key, ci_data.get("name"), ci_metadata)
            row["completed_incidents"].append((created_at, recovered_at))
            if created_at < window_start:
                continue
            repair_seconds = (recovered_at - created_at).total_seconds()
            row["failure_starts"].append(created_at)
            row["repair_seconds"].append(repair_seconds)
            clipped_start = max(created_at, window_start)
            clipped_end = min(recovered_at, window_end)
            row["downtime_seconds"] += max(0.0, (clipped_end - clipped_start).total_seconds())

        active_result = session.run(
            """
            MATCH (e:Event)<-[:HAS_EVENT]-(ci:CI)
            WHERE e.event_type = 'AVAILABILITY'
              AND e.availability_source IN ['PING', 'ICMP']
              AND toUpper(coalesce(e.correlation_type, 'ROOT')) <> 'PROPAGATED'
              AND e.status IN ['OPEN', 'ACK']
              AND e.created_at IS NOT NULL
              AND e.created_at <= $window_end
            OPTIONAL MATCH (ci)-[:CATEGORIZED_AS]->(cat:Category)
            WITH e, ci, head(collect(DISTINCT cat.name)) AS category
            RETURN e, ci, category
            ORDER BY e.created_at ASC
            """,
            window_end=window_end,
        )
        for record in active_result:
            event_data = _node_to_dict(_record_value(record, "e"))
            ci_data = _node_to_dict(_record_value(record, "ci"))
            key = _availability_group_key(event_data)
            if key is None:
                continue
            created_at = _parse_datetime(event_data.get("created_at"))
            if created_at is None or created_at > window_end:
                continue
            ci_metadata = _build_availability_ci_metadata(
                ci_data, _record_value(record, "category")
            )
            row = ensure_group(key, ci_data.get("name"), ci_metadata)
            row["active_events"] += 1
            if window_start <= created_at <= window_end:
                row["failure_starts"].append(created_at)
            clipped_start = max(created_at, window_start)
            row["active_downtime_seconds"] += max(0.0, (window_end - clipped_start).total_seconds())

        snmp_result = session.run(
            """
            MATCH (ci:CI)-[:HAS_METRIC]->(m:MetricDef)
            WHERE toUpper(coalesce(m.protocol, '')) = 'SNMP'
            WITH DISTINCT ci
            OPTIONAL MATCH (ci)-[:HAS_EVENT]->(e:Event)
            WHERE e.status IN ['OPEN', 'ACK']
              AND e.event_type = 'COLLECTION_FAILURE'
              AND toUpper(coalesce(e.source_protocol, '')) = 'SNMP'
              AND e.failure_family = 'SNMP_NO_RESPONSE'
            WITH ci, count(e) AS open_no_response_events
            RETURN count(ci) AS total_ci_with_snmp,
                   sum(CASE WHEN open_no_response_events = 0 THEN 1 ELSE 0 END) AS functional_ci,
                   sum(CASE WHEN open_no_response_events > 0 THEN 1 ELSE 0 END) AS failing_ci,
                   sum(CASE WHEN open_no_response_events > 0 THEN 1 ELSE 0 END) AS no_response_ci,
                   sum(open_no_response_events) AS no_response_event_count
            """
        )
        snmp_coverage = _build_snmp_coverage_summary(snmp_result.single())

    rows: list[dict[str, Any]] = []
    for row in groups.values():
        failure_starts = sorted(row["failure_starts"])
        repair_seconds = row["repair_seconds"]
        mttr_seconds = sum(repair_seconds) / len(repair_seconds) if repair_seconds else None
        intervals = []
        effective_outage_end = None
        seen_incidents = set()
        for created_at, recovered_at in sorted(row["completed_incidents"]):
            incident_key = (created_at, recovered_at)
            if incident_key in seen_incidents:
                continue
            seen_incidents.add(incident_key)
            if effective_outage_end is None:
                effective_outage_end = recovered_at
                continue
            if created_at < effective_outage_end:
                effective_outage_end = max(effective_outage_end, recovered_at)
                continue
            if created_at >= window_start:
                intervals.append((created_at - effective_outage_end).total_seconds())
            effective_outage_end = recovered_at
        mtbf_seconds = sum(intervals) / len(intervals) if intervals else None
        total_downtime = row["downtime_seconds"] + row["active_downtime_seconds"]
        availability_percentage = None
        if window_seconds > 0:
            availability_percentage = round(
                max(0.0, (window_seconds - total_downtime) / window_seconds * 100),
                4,
            )
        rows.append(
            {
                "ci_id": row["ci_id"],
                "ci_name": row.get("ci_name"),
                "event_type": row["event_type"],
                "recovered_incidents": len(repair_seconds),
                "mttr_seconds": mttr_seconds,
                "mtbf_seconds": mtbf_seconds,
                "downtime_seconds": row["downtime_seconds"],
                "active_events": row["active_events"],
                "active_downtime_seconds": row["active_downtime_seconds"],
                "availability_percentage": availability_percentage,
                "first_failure_at": failure_starts[0].isoformat() if failure_starts else None,
                "last_failure_at": failure_starts[-1].isoformat() if failure_starts else None,
                "ci": row.get("ci"),
            }
        )

    rows.sort(
        key=lambda item: (
            item["availability_percentage"] if item["availability_percentage"] is not None else 101,
            -(item["active_events"] or 0),
            -(item["recovered_incidents"] or 0),
            item["ci_name"] or item["ci_id"],
        )
    )
    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "generated_at": generated_at.isoformat(),
        "window_days": round(window_seconds / 86400, 4) if window_seconds else 0,
        "total_groups": len(rows),
        "snmp_coverage": snmp_coverage,
        "rows": rows,
    }


def get_availability_snmp_no_response_drilldown(
    limit: int = 25,
    offset: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return affected CIs with active SNMP no-response collection failures."""
    safe_limit = max(1, min(int(limit or 25), 100))
    safe_offset = max(0, int(offset or 0))
    generated_at = now or datetime.now(UTC)
    summary = {
        "total_ci_with_no_response": 0,
        "total_events_with_no_response": 0,
    }
    rows: list[dict[str, Any]] = []

    driver = get_db()
    with driver.session() as session:
        summary_record = session.run(
            """
            MATCH (ci:CI)-[:HAS_METRIC]->(m:MetricDef)
            WHERE toUpper(coalesce(m.protocol, '')) = 'SNMP'
            WITH DISTINCT ci
            MATCH (ci)-[:HAS_EVENT]->(e:Event)
            WHERE e.status IN ['OPEN', 'ACK']
              AND e.event_type = 'COLLECTION_FAILURE'
              AND toUpper(coalesce(e.source_protocol, '')) = 'SNMP'
              AND e.failure_family = 'SNMP_NO_RESPONSE'
            RETURN count(DISTINCT ci) AS total_ci_with_no_response,
                   count(e) AS total_events_with_no_response
            """
        ).single()
        if summary_record is not None:
            summary = {
                "total_ci_with_no_response": int(
                    summary_record.get("total_ci_with_no_response") or 0
                ),
                "total_events_with_no_response": int(
                    summary_record.get("total_events_with_no_response") or 0
                ),
            }

        result = session.run(
            """
            MATCH (ci:CI)-[:HAS_METRIC]->(m:MetricDef)
            WHERE toUpper(coalesce(m.protocol, '')) = 'SNMP'
            WITH DISTINCT ci
            MATCH (ci)-[:HAS_EVENT]->(e:Event)
            WHERE e.status IN ['OPEN', 'ACK']
              AND e.event_type = 'COLLECTION_FAILURE'
              AND toUpper(coalesce(e.source_protocol, '')) = 'SNMP'
              AND e.failure_family = 'SNMP_NO_RESPONSE'
            OPTIONAL MATCH (ci)-[:CATEGORIZED_AS]->(cat:Category)
            WITH ci, e, head(collect(DISTINCT cat.name)) AS category
            ORDER BY e.created_at DESC
            WITH ci,
                 category,
                 count(e) AS event_count,
                 max(e.created_at) AS latest_event_at,
                 collect(e) AS events
            ORDER BY event_count DESC,
                     latest_event_at DESC,
                     coalesce(ci.name, ci.label, ci.id) ASC
            SKIP $offset
            LIMIT $limit
            RETURN ci,
                   category,
                   event_count,
                   latest_event_at,
                   [event IN events[..5] | {
                       id: event.id,
                       message: event.message,
                       status: event.status,
                       created_at: event.created_at,
                       last_seen: event.last_seen
                   }] AS events
            """,
            limit=safe_limit,
            offset=safe_offset,
        )

        for record in result:
            ci_data = _node_to_dict(_record_value(record, "ci"))
            event_items = _record_value(record, "events") or []
            events = [
                _snmp_no_response_event_summary(_node_to_dict(event)) for event in event_items
            ]
            rows.append(
                _clean_dict(
                    {
                        "ci_id": ci_data.get("id"),
                        "ci_name": ci_data.get("name") or ci_data.get("label"),
                        "category": _record_value(record, "category"),
                        "status": ci_data.get("status"),
                        "ip": ci_data.get("ip"),
                        "owner": ci_data.get("owner"),
                        "brand": ci_data.get("brand"),
                        "model": ci_data.get("model"),
                        "event_count": int(_record_value(record, "event_count") or 0),
                        "latest_event_at": _isoformat_or_none(
                            _record_value(record, "latest_event_at")
                        ),
                        "events": events,
                    }
                )
            )

    return {
        "generated_at": generated_at.isoformat(),
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": summary,
        "rows": rows,
    }


def get_affected_siblings(event_id: str) -> list[dict[str, Any]]:
    """Return the list of CIs affected by the given ROOT event.

    P2 REQ-004: this is the operator-facing drill-down. The ROOT event is
    fetched first and validated as a ROOT (legacy PROPAGATED children are
    not drill-down targets). `affected_ci_ids` is the membership list that
    P0 writes onto the ROOT; the lookup is an `UNWIND` + `MATCH (:CI)` that
    preserves the original ordering and returns at least `{ci_id, ci_name,
    status}`. Empty membership returns `[]` (no 404).

    Unknown or non-ROOT ids raise `HTTPException(404, "Event not found: <id>")`.
    """
    driver = get_db()
    with driver.session() as session:
        lookup = session.run(
            """
            MATCH (e:Event {id: $event_id})
            RETURN e.correlation_type AS correlation_type,
                   e.affected_ci_ids AS affected_ci_ids
            """,
            event_id=event_id,
        ).single()

        if not lookup or lookup.get("correlation_type") != "ROOT":
            _raise_event_not_found(event_id)

        ci_ids = list(lookup.get("affected_ci_ids") or [])
        if not ci_ids:
            return []

        result = session.run(
            """
            UNWIND $ci_ids AS ci_id
            MATCH (ci:CI {id: ci_id})
            RETURN ci.id AS ci_id,
                   ci.name AS ci_name,
                   ci.status AS status,
                   ci.ip AS ci_hostname,
                   ci.location_name AS ci_location_name
            """,
            ci_ids=ci_ids,
        )

        rows_by_id = {
            record["ci_id"]: {
                "ci_id": record["ci_id"],
                "ci_name": record["ci_name"],
                "status": record["status"],
                "ci_hostname": record["ci_hostname"],
                "ci_location_name": record["ci_location_name"],
            }
            for record in result
        }

        # Preserve the original ordering of `affected_ci_ids` and drop any
        # ids Neo4j did not resolve (defensive — should not happen in
        # practice because the writer pins the relationship).
        return [rows_by_id[ci_id] for ci_id in ci_ids if ci_id in rows_by_id]


def get_events(
    status: str | None = None,
    include_children: bool = False,
) -> list[dict[str, Any]]:
    """Return the event feed scoped to the requested status.

    P2 REQ-003: when `include_children=False` (default), the query filters
    out legacy PROPAGATED events so the operator view stops double-counting
    the child rows P0 already collapsed into the ROOT. Pass
    `include_children=True` to retain the raw set (audit, AI chat context).
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event)<-[:HAS_EVENT]-(ci:CI)
            WITH e, ci
            WHERE (
                $status IS NULL
                OR ($status = 'ACTIVE' AND e.status IN ['OPEN', 'ACK'])
                OR ($status = 'CONSOLE' AND e.status IN ['OPEN', 'ACK', 'RECOVERED'])
                OR ($status <> 'ACTIVE' AND $status <> 'CONSOLE' AND e.status = $status)
            )
            AND (
                $include_children
                OR coalesce(e.correlation_type, 'ROOT') = 'ROOT'
            )
            OPTIONAL MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)
            RETURN e, ci, m
            ORDER BY e.created_at DESC
        """,
            status=status,
            include_children=include_children,
        )
        return [
            _public_event_summary(
                _build_event_summary(
                    _node_to_dict(record["e"]),
                    _node_to_dict(record["ci"]),
                    _node_to_dict(record["m"]),
                )
            )
            for record in result
        ]


def get_event_detail(event_id: str) -> dict[str, Any]:
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event {id: $event_id})<-[:HAS_EVENT]-(ci:CI)
            OPTIONAL MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)
            OPTIONAL MATCH (ci)-[:BELONGS_TO]->(bs:BusinessService)
            OPTIONAL MATCH (bs)-[:USES_SLA]->(sc:ServiceCatalog)
            WITH e, ci, m, bs, head([item IN collect(sc) WHERE item IS NOT NULL]) AS sc
            RETURN e, ci, m, bs, sc
        """,
            event_id=event_id,
        ).single()

        if not result:
            raise HTTPException(status_code=404, detail="Event not found")

        return build_event_detail_response(result)


def get_related_events(ci_id: str) -> list[dict[str, Any]]:
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE e.ci_id = $ci_id AND e.status IN ['OPEN', 'ACK']
            RETURN e, m
            ORDER BY
              CASE e.severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'WARNING' THEN 2
                WHEN 'INFO' THEN 3
                ELSE 4
              END ASC,
              e.created_at DESC
        """,
            ci_id=ci_id,
        )

        related = []
        for record in result:
            event_data = _node_to_dict(record["e"])
            metric_value = _record_value(record, "m")
            if metric_value is not None:
                metric_data = _node_to_dict(metric_value)
                event_data["metric_name"] = metric_data.get("name") or metric_data.get("id")
            else:
                event_data["metric_name"] = _record_value(record, "metric_name")
            related.append(_public_event_summary(event_data))

        return related


def ack_event(event_id: str, user: str, comment_message: str | None = None) -> dict[str, str]:
    driver = get_db()
    audit_message = _build_ack_audit_message(user)
    note_message = _normalize_ack_note(comment_message)
    with driver.session() as session:  # noqa: SIM117
        with session.begin_transaction() as tx:
            result = tx.run(
                """
                MATCH (e:Event {id: $eid})
                SET e.status = 'ACK', e.ack = true, e.ack_at = datetime(), e.ack_by = $user
                WITH e
                SET e.comments = coalesce(e.comments, []) + ($audit_message + ' (' + toString(datetime()) + ')')
                FOREACH (_ IN CASE WHEN $note_message IS NULL OR trim($note_message) = '' THEN [] ELSE [1] END |
                    SET e.comments = e.comments + ($user + ': ' + $note_message + ' (' + toString(datetime()) + ')')
                )
                RETURN e.id AS event_id
            """,
                eid=event_id,
                user=user,
                audit_message=audit_message,
                note_message=note_message,
            ).single()
            if not result:
                _raise_event_not_found(event_id)
    return {"message": "Event Acknowledged"}


def close_event(
    event_id: str,
    user: str,
    forced: bool = False,
    comment_message: str | None = None,
) -> dict[str, str]:
    # 1. Validate request content first (no DB hit)
    _validate_close_request(forced, comment_message)

    # 2. Build audit message
    audit_message = _build_close_audit_message(user, forced, comment_message)

    # 3. Perform atomic update with existence check
    driver = get_db()
    with driver.session() as session:
        # Check current status first to provide a better error message
        current = session.run(
            "MATCH (e:Event {id: $eid}) RETURN e.status as status", eid=event_id
        ).single()

        if not current:
            _raise_event_not_found(event_id)
        assert current is not None

        if current["status"] == "CLOSED":
            raise HTTPException(status_code=400, detail=f"Event {event_id} is already CLOSED")

        session.run(
            """
            MATCH (e:Event {id: $eid})
            SET e.status = 'CLOSED', e.closed_at = datetime(), e.closed_by = $user
            WITH e
            SET e.comments = coalesce(e.comments, []) + ($audit_message + ' (' + toString(datetime()) + ')')
            RETURN e.id AS event_id
            """,
            eid=event_id,
            user=user,
            audit_message=audit_message,
        ).single()

    return {"message": "Event Closed"}


def add_event_comment(event_id: str, user: str, message: str) -> dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event {id: $eid})
            SET e.comments = coalesce(e.comments, []) + ($user + ': ' + $msg + ' (' + toString(datetime()) + ')')
            RETURN e.id AS event_id
        """,
            eid=event_id,
            user=user,
            msg=message,
        ).single()
        if not result:
            _raise_event_not_found(event_id)
    return {"message": "Comment added"}


def prune_recovered_events(user: str) -> dict[str, Any]:
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event)
            WHERE e.status = 'RECOVERED'
              AND (e.ack IS NULL OR e.ack = false)
            SET e.status = 'CLOSED', e.closed_at = datetime(), e.closed_by = $user
            RETURN count(e) as closed_count
        """,
            user=user,
        ).single() or {"closed_count": 0}
    closed_count = _record_value(result, "closed_count") or 0
    return {
        "message": f"Cleaned up {closed_count} events",
        "count": closed_count,
    }


# ---------------------------------------------------------------------------
# Auto-prune scheduler entrypoint (fix-423 PR #2, AD-2/AD-5/AD-8)
# ---------------------------------------------------------------------------
#
# REQ-PRUNE-003 + REQ-OBS-PRUNE-002: this is the function that the
# ``backup_scheduler`` IntervalTrigger job invokes on every tick. It
# acquires the distributed ``prune_lock`` (Postgres row), runs the existing
# ``prune_recovered_events`` Cypher update, records the per-batch counter
# in ``event_prune_metrics``, and releases the lock.
#
# Behaviour:
# * If the lock is held (operator running the manual SSE prune), we log a
#   WARN and return 0 — APScheduler is not an HTTP caller, so there is no
#   409 to surface. The scheduler will try again on the next tick.
# * If ``prune_recovered_events`` raises, the lock is still released (try
#   / finally) so a transient Neo4j hiccup doesn't leave the lock held
#   until TTL expiry.


def run_prune_recovered_events_sync(user: str = "system-prune") -> int:
    """Sync scheduler entrypoint for the auto-prune job.

    Parameters
    ----------
    user:
        Audit-trail user recorded in ``closed_by``. Defaults to
        ``"system-prune"`` so it is obvious in event history that the
        closure was scheduler-driven rather than operator-driven.

    Returns
    -------
    int
        Number of RECOVERED events closed by this tick. ``0`` when the
        lock was contended (AD-8) or when no candidates exist.
    """
    # Import locally so module load doesn't require the prune-metrics
    # singleton to be importable in every test path that imports
    # ``event_service``.
    from services.event_prune_metrics import record_pruned

    if not acquire_prune_lock(owner="scheduler", ttl_seconds=300):
        logger.warning(
            "event_prune_skipped_lock_held",
            extra={"event_prune_owner": "scheduler"},
        )
        return 0

    try:
        result = prune_recovered_events(user)
        closed_count = int(result.get("count", 0) or 0)
        record_pruned(closed_count=closed_count)
        return closed_count
    finally:
        release_prune_lock(owner="scheduler")


# ---------------------------------------------------------------------------
# Distributed Prune Lock — prevents concurrent prune operations across operators
# ---------------------------------------------------------------------------

from postgres_db import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402


def acquire_prune_lock(owner: str, ttl_seconds: int = 300, max_attempts: int = 3) -> bool:
    """
    Atomically acquire the prune lock using INSERT ... ON CONFLICT DO NOTHING.
    Returns True only if we successfully acquired the lock.
    Uses bounded retry (max_attempts) to prevent stack overflow under contention.
    """
    db = SessionLocal()
    try:
        for _attempt in range(max_attempts):
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

            # Atomic: try to insert, if lock exists and not expired, conflict
            result = db.execute(
                text(
                    """
                    INSERT INTO prune_lock (lock_key, owner, acquired_at, expires_at)
                    VALUES ('prune', :owner, :acquired_at, :expires_at)
                    ON CONFLICT (lock_key) DO NOTHING
                    RETURNING id
                """
                ),
                {"owner": owner, "acquired_at": datetime.utcnow(), "expires_at": expires_at},
            )
            row = result.fetchone()

            if row is not None:
                # We acquired the lock
                db.commit()
                return True

            # Lock exists — check if it's ours or expired
            existing = db.execute(
                text("SELECT owner, expires_at FROM prune_lock WHERE lock_key = 'prune'")
            ).fetchone()

            if existing is None:
                # Lock doesn't exist (race with delete) — retry
                db.commit()
                continue

            existing_owner, existing_expires = existing

            if existing_owner == owner:
                # We already own it — extend TTL (re-acquire)
                db.execute(
                    text(
                        """
                        UPDATE prune_lock
                        SET expires_at = :expires_at
                        WHERE lock_key = 'prune' AND owner = :owner
                    """
                    ),
                    {"owner": owner, "expires_at": expires_at},
                )
                db.commit()
                return True

            if existing_expires < datetime.utcnow():
                # Expired — delete and retry
                db.execute(
                    text("DELETE FROM prune_lock WHERE lock_key = 'prune' AND expires_at < :now"),
                    {"now": datetime.utcnow()},
                )
                db.commit()
                continue

            # Lock held by another unexpired operator — give up
            return False

        # Exhausted all attempts
        return False
    finally:
        db.close()


def release_prune_lock(owner: str) -> bool:
    """Release prune lock if we own it."""
    db = SessionLocal()
    try:
        result = db.execute(
            text("DELETE FROM prune_lock WHERE lock_key = 'prune' AND owner = :owner RETURNING id"),
            {"owner": owner},
        )
        released = result.fetchone() is not None
        db.commit()
        return released
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Event Batch Pruner — async generator with chunking, TTL cache, timeout
# ---------------------------------------------------------------------------


import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

from config import get_event_batch_settings  # noqa: E402


async def event_batch_pruner(
    user: str,
    batch_size: int | None = None,
    batch_delay_ms: int | None = None,
    batch_timeout_s: int | None = None,
    _idempotency_cache: dict[str, float] | None = None,
    last_cursor: str | None = None,
    last_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Async generator that yields progress after each chunk.

    Uses a composite ``(created_at, id)`` cursor with NULL-safe tiebreak so it
    makes forward progress on legacy NULL-``created_at`` rows (70%+ of
    production rows pre-#279). Per-chunk transactions preserve atomicity.
    Idempotency is ensured via a request-scoped in-memory cache with TTL.
    Handles per-chunk timeout.

    Yields progress dicts with keys:
        - total: total events found to process
        - processed: events processed in this chunk
        - remaining: events still to process
        - batch: current batch number (1-indexed)
        - error: error message if chunk failed (optional)
    """
    settings = get_event_batch_settings()
    batch_size = batch_size if batch_size is not None else settings.batch_size
    batch_delay_ms = batch_delay_ms if batch_delay_ms is not None else settings.batch_delay_ms
    batch_timeout_s = batch_timeout_s if batch_timeout_s is not None else settings.batch_timeout_s

    # Request-scoped cache: each prune operation gets its own cache, preventing
    # cross-user contamination (CRITICAL #2 fix). Cache is isolated to this
    # generator's lifetime.
    if _idempotency_cache is None:
        _idempotency_cache = {}
    cache_ttl_s = 300  # 5 minutes — events processed within this window are cached

    # Lock ensures atomic cache operations (WARNING #7 fix)
    _cache_lock = threading.Lock()

    def _cache_has(event_id: str) -> bool:
        """Check if event_id is in cache and not expired."""
        now = time.monotonic()
        if event_id in _idempotency_cache:
            if _idempotency_cache[event_id] > now:
                return True
            # Expired — remove it
            del _idempotency_cache[event_id]
        return False

    def _cache_add(event_id: str) -> None:
        """Add event_id to cache with current TTL expiry."""
        _idempotency_cache[event_id] = time.monotonic() + cache_ttl_s

    def _cache_check_and_add(event_id: str) -> bool:
        """Atomically check if event_id is in cache and add if not. Returns True if added."""
        with _cache_lock:
            if _cache_has(event_id):
                return False
            _cache_add(event_id)
            return True

    driver = get_db()
    batch = 0
    total_processed = 0

    # First: get total count of recoverable events
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event)
            WHERE e.status = 'RECOVERED'
              AND (e.ack IS NULL OR e.ack = false)
            RETURN count(e) as total
            """
        ).single()
        total = _record_value(result, "total") or 0

    yield {"total": total, "processed": 0, "remaining": total, "batch": 0}

    if total == 0:
        return

    # Process batches until all events are handled
    while total_processed < total:
        batch += 1
        processed_in_chunk = 0
        # Composite (created_at, id) cursor with NULL-safe tiebreak — see
        # openspec/changes/fix-423-recovered-event-accumulation/design.md AD-1.
        # Legacy NULL `created_at` rows (pre-#279) would otherwise stop iter 2+
        # because `NULL > <anything>` evaluates to NULL.
        cursor_filter = ""
        cursor_params: dict[str, Any] = {"limit": batch_size}
        if last_cursor is not None:
            cursor_filter = (
                "AND (e.created_at > $last_cursor OR (e.created_at IS NULL AND e.id > $last_id))"
            )
            cursor_params["last_cursor"] = last_cursor
            cursor_params["last_id"] = last_id
        elif last_id is not None:
            # Cursor is at the tail of a NULL-bearing pass: only rows whose
            # created_at is still NULL AND whose id is strictly greater are
            # eligible. We deliberately avoid `> NULL` since that returns NULL
            # (which excludes every row in Cypher).
            cursor_filter = "AND (e.created_at IS NULL AND e.id > $last_id)"
            cursor_params["last_id"] = last_id

        with driver.session() as session:
            try:
                result = session.run(
                    f"""
                    MATCH (e:Event)
                    WHERE e.status = 'RECOVERED'
                      AND (e.ack IS NULL OR e.ack = false)
                      {cursor_filter}
                    RETURN e.id as event_id, e.status, e.created_at as created_at
                    ORDER BY e.created_at ASC NULLS LAST, e.id ASC
                    LIMIT $limit
                    """,
                    **cursor_params,
                )

                event_ids: set[str] = set()
                last_processed_cursor = None
                last_processed_id = None
                for record in result:
                    event_id = record.get("event_id")
                    created_at = record.get("created_at")
                    if event_id and not _cache_has(event_id):
                        event_ids.add(event_id)
                        last_processed_cursor = created_at
                        last_processed_id = event_id

                # Close each event in its own transaction for safety
                for event_id in event_ids:
                    # WARNING #7 fix: use atomic check-and-add to prevent race between
                    # _cache_has check and _cache_add call across concurrent operations
                    if not _cache_check_and_add(event_id):
                        continue
                    try:
                        with session.begin_transaction() as tx:
                            close_result = tx.run(
                                """
                                MATCH (e:Event {id: $eid})
                                WHERE e.status = 'RECOVERED'
                                  AND (e.ack IS NULL OR e.ack = false)
                                SET e.status = 'CLOSED', e.closed_at = datetime(), e.closed_by = $user
                                RETURN e.id AS closed_id
                                """,
                                eid=event_id,
                                user=user,
                            ).single()
                            tx.commit()
                        if close_result:
                            processed_in_chunk += 1
                    except Exception:
                        # Chunk timeout or other error — log and continue
                        continue

                total_processed += processed_in_chunk

                # Update cursor for next batch. The composite cursor needs both
                # the row's `created_at` (None when NULL) and its `id` so the
                # next iteration can place the boundary deterministically.
                if last_processed_id is not None:
                    last_cursor = last_processed_cursor
                    last_id = last_processed_id

                yield {
                    "total": total,
                    "processed": total_processed,
                    "remaining": max(0, total - total_processed),
                    "batch": batch,
                }

                # If the selected page was smaller than batch_size, there are no later
                # eligible rows. Use selected count instead of closed count because an
                # event can become ACKed/commented after selection and be skipped by
                # the guarded close recheck without meaning pagination is exhausted.
                if len(event_ids) < batch_size:
                    break

            except Exception as e:
                # Timeout or error on this chunk — yield error but continue
                yield {
                    "total": total,
                    "processed": total_processed,
                    "remaining": max(0, total - total_processed),
                    "batch": batch,
                    "error": str(e),
                }
                # Don't increment total_processed — chunk will be retried if not idempotent

        # Delay between chunks (with small jitter to avoid thundering herd)
        if batch_delay_ms > 0:
            jitter_ms = batch_delay_ms + int(batch_delay_ms * 0.1 * (hash(str(batch)) % 10 - 5) / 5)
            await asyncio.sleep(max(0, jitter_ms / 1000.0))


def run_event_diagnostic(event_id: str, user: str) -> dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event {id: $eid})<-[:HAS_EVENT]-(ci:CI)
            MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)
            RETURN ci, m
        """,
            eid=event_id,
        ).single()

        if not result:
            raise HTTPException(status_code=404, detail="Event not found")

        ci = _node_to_dict(result["ci"])
        metric = _node_to_dict(result["m"])
        diag_msg = run_diagnostic(ci, metric)
        final_msg = f"DIAGNOSTIC RUN BY {user}:\n{diag_msg}"

        session.run(
            """
            MATCH (e:Event {id: $eid})
            SET e.comments = coalesce(e.comments, []) + ($msg + ' (' + toString(datetime()) + ')')
        """,
            eid=event_id,
            msg=final_msg,
        )

    return {"message": "Diagnostic run", "result": diag_msg}
