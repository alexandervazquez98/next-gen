from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_db
from fastapi import HTTPException
from services.snmp_service import run_diagnostic


def _serialize_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _node_to_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return {key: _serialize_value(value[key]) for key in value.keys()}


def _record_value(record: Any, key: str) -> Any:
    if record is None:
        return None
    try:
        return record[key]
    except Exception:
        return record.get(key) if hasattr(record, "get") else None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _compute_sla_remaining_minutes(
    created_at: Any, sla_minutes: Optional[int], now: Optional[datetime] = None
) -> Optional[int]:
    if sla_minutes is None:
        return None
    created_dt = _parse_datetime(created_at)
    if created_dt is None:
        return None
    reference = now or datetime.now(timezone.utc)
    age_minutes = int((reference - created_dt).total_seconds() // 60)
    return int(sla_minutes) - age_minutes


def _clean_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _strip_known_audit_prefixes(message: Optional[str]) -> str:
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


def _normalize_ack_note(comment_message: Optional[str]) -> Optional[str]:
    if not comment_message:
        return None
    cleaned = comment_message.strip()
    if cleaned.startswith(("[OWNERSHIP]", "[AUDIT][OWNERSHIP]")):
        return None
    normalized = _strip_known_audit_prefixes(cleaned)
    return normalized or None


def _build_close_audit_message(
    user: str, forced: bool, comment_message: Optional[str]
) -> str:
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


def _optional_contract(
    payload: Dict[str, Any], required_keys: set[str]
) -> Optional[Dict[str, Any]]:
    cleaned = _clean_dict(payload)
    if not required_keys.issubset(cleaned):
        return None
    return cleaned


def _build_external_ticket_ref(event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
    event_data: Dict[str, Any], ci_data: Dict[str, Any], metric_data: Dict[str, Any]
) -> Dict[str, Any]:
    summary = {key: _serialize_value(value) for key, value in event_data.items()}
    summary["ci_node_id"] = ci_data.get("id")
    summary["ci_name"] = ci_data.get("name")
    summary["ci_hostname"] = ci_data.get("ip")
    summary["ci_location_name"] = ci_data.get("location_name")
    summary["metric_name"] = metric_data.get("name") or metric_data.get("id")
    summary["metric_protocol"] = metric_data.get("protocol")
    return summary


def _public_event_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
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
    }
    return {
        key: value
        for key, value in summary.items()
        if key in allowed_keys and value is not None
    }


def _extract_structured_close_fields(comment_message: Optional[str]) -> tuple[str, str]:
    detail = _strip_known_audit_prefixes(comment_message)
    root_cause = ""
    note_lines: List[str] = []
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


def _validate_close_request(forced: bool, comment_message: Optional[str]) -> None:
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


def _pick_value(snapshot_value: Any, resolved_value: Any) -> tuple[Any, Optional[str]]:
    if snapshot_value is not None:
        return snapshot_value, "snapshot"
    if resolved_value is not None:
        return resolved_value, "resolved"
    return None, None


def _build_business_context(
    event_data: Dict[str, Any],
    ci_data: Dict[str, Any],
    business_service: Dict[str, Any],
    service_catalog: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
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
    site, site_source = _pick_value(event_data.get("site"), ci_data.get("locationName"))
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


def build_event_detail_response(
    record: Any, now: Optional[datetime] = None
) -> Dict[str, Any]:
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
    escalation_tier = event_data.get("escalation_tier") or business_service_context.get(
        "tier"
    )

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
            "assignment_state": "assigned"
            if event_data.get("ack") and event_data.get("ack_by")
            else "unassigned",
            "assigned_to": event_data.get("ack_by"),
            "opened_by": "system",
            "escalation_tier": escalation_tier
            if escalation_tier in {"T1", "T2", "T3"}
            else None,
            "external_ticket": _build_external_ticket_ref(event_data),
        },
    }


def get_events(status: Optional[str] = None) -> List[Dict[str, Any]]:
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event)<-[:HAS_EVENT]-(ci:CI)
            MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE ($status IS NULL OR e.status = $status OR ($status = 'ACTIVE' AND e.status IN ['OPEN', 'ACK', 'RECOVERED']))
            RETURN e, ci, m
            ORDER BY e.created_at DESC
            LIMIT 100
        """,
            status=status,
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


def get_event_detail(event_id: str) -> Dict[str, Any]:
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


def get_related_events(ci_id: str) -> List[Dict[str, Any]]:
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
                event_data["metric_name"] = metric_data.get("name") or metric_data.get(
                    "id"
                )
            else:
                event_data["metric_name"] = _record_value(record, "metric_name")
            related.append(_public_event_summary(event_data))

        return related


def ack_event(
    event_id: str, user: str, comment_message: Optional[str] = None
) -> Dict[str, str]:
    driver = get_db()
    audit_message = _build_ack_audit_message(user)
    note_message = _normalize_ack_note(comment_message)
    with driver.session() as session:
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
    comment_message: Optional[str] = None,
) -> Dict[str, str]:
    # 1. Validate request content first (no DB hit)
    _validate_close_request(forced, comment_message)

    # 2. Build audit message
    audit_message = _build_close_audit_message(user, forced, comment_message)

    # 3. Perform atomic update
    driver = get_db()
    with driver.session() as session:
        result = session.run(
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

        if not result:
            _raise_event_not_found(event_id)

    return {"message": "Event Closed"}


def add_event_comment(event_id: str, user: str, message: str) -> Dict[str, str]:
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


def prune_recovered_events(user: str) -> Dict[str, Any]:
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event)
            WHERE e.status = 'RECOVERED'
              AND (e.ack IS NULL OR e.ack = false)
              AND (e.comments IS NULL OR size(e.comments) = 0)
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


def run_event_diagnostic(event_id: str, user: str) -> Dict[str, str]:
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
