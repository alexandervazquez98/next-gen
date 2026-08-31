"""Read-only detection + advisory renderer for stale Event reminders.

Issue #154 surfaces events that linger ``OPEN``/``ACK`` after their
condition changed. Operators see them via ``GET /api/events/recommendations``
and may record a decision via the three quick actions
(``dismiss``/``snooze``/``escalate``). This module owns the detection
Cypher and the schema-versioned payload; the router in
``backend/routers/event_recommendations.py`` wires it to HTTP.

Mirrors the precedent in ``legacy_event_discriminator_audit.py``:

- Frozen dataclasses with ``from_mapping`` + ``to_dict``.
- ``neo4j.READ_ACCESS`` (defensive fallback if neo4j is unavailable).
- Bounded LIMIT on the read query.
- Schema-versioned payload (``stale-event-reminder-recommendation.v1``).
- Markdown + JSON renderers share the same model.

This module NEVER mutates ``Event``, ``CI``, or ``MetricDef``. The Cypher
contains only ``MATCH`` / ``OPTIONAL MATCH`` / ``RETURN`` / ``WITH`` /
``ORDER BY`` / ``LIMIT``. A static RED test
(``test_stale_event_reminders.py::test_detection_cypher_contains_no_write_clauses``)
asserts no ``MERGE`` / ``SET`` / ``DELETE`` / ``CREATE`` / ``REMOVE``
token appears in the query string.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

try:
    from neo4j import READ_ACCESS as _NEO4J_READ_ACCESS
except ImportError:  # pragma: no cover - exercised only when neo4j is unavailable.
    _NEO4J_READ_ACCESS = None


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

RECOMMENDATION_SCHEMA_VERSION = "stale-event-reminder-recommendation.v1"

# Stable reason codes surfaced to operators and stored in audit context.
REASON_OLDER_THAN_THRESHOLD = "older_than_threshold"
REASON_NO_REFRESH_IN_WINDOW = "no_refresh_in_window"
REASON_LINK_MISSING = "link_missing"

REASON_CODES: tuple[str, ...] = (
    REASON_OLDER_THAN_THRESHOLD,
    REASON_NO_REFRESH_IN_WINDOW,
    REASON_LINK_MISSING,
)

# Refresh-status taxonomy used by the renderer.
REFRESH_NO_LINK = "no_link"
REFRESH_NEVER_REFRESHED = "never_refreshed"
REFRESH_STALE_REFRESH = "stale_refresh"
REFRESH_FRESH = "fresh"

REFRESH_STATUSES: tuple[str, ...] = (
    REFRESH_NO_LINK,
    REFRESH_NEVER_REFRESHED,
    REFRESH_STALE_REFRESH,
    REFRESH_FRESH,
)

# Quick actions surfaced for every recommendation.
QUICK_ACTIONS: tuple[str, ...] = ("dismiss", "snooze", "escalate")

# Bounded scan guards. Defaults match the spec
# (limit clamping at the router layer too).
DEFAULT_LIMIT = 100
MIN_LIMIT = 1
MAX_LIMIT = 500

# Detection filter constants — first slice targets SNMP no-response only.
TARGET_EVENT_TYPE = "COLLECTION_FAILURE"
TARGET_FAILURE_FAMILY = "SNMP_NO_RESPONSE"
TARGET_STATUSES: tuple[str, ...] = ("OPEN", "ACK")


class ReasonCode(str, Enum):  # noqa: UP042
    """Stable enumeration of stale-event reason codes.

    ``str`` mixin lets values serialize as plain JSON strings without
    a custom encoder. The string values match the public
    ``REASON_*`` constants above.
    """

    OLDER_THAN_THRESHOLD = REASON_OLDER_THAN_THRESHOLD
    NO_REFRESH_IN_WINDOW = REASON_NO_REFRESH_IN_WINDOW
    LINK_MISSING = REASON_LINK_MISSING


# ---------------------------------------------------------------------------
# Read-only Cypher
# ---------------------------------------------------------------------------

READ_ONLY_DETECTION_QUERY = """
MATCH (e:Event)
WHERE e.status IN $statuses
  AND e.event_type = $event_type
  AND e.failure_family = $failure_family
OPTIONAL MATCH (ci:CI)-[:HAS_EVENT]->(e)
OPTIONAL MATCH (md:MetricDef)-[:TRIGGERED_BY]->(e)
WITH e, ci, md,
     duration({hours: $age_hours}).seconds AS age_threshold_s,
     duration({hours: $refresh_window_hours}).seconds AS refresh_window_s,
     timestamp() AS now_ts
WITH e, ci, md, age_threshold_s, refresh_window_s, now_ts,
     (now_ts.epochSeconds - coalesce(e.last_seen.epochSeconds, e.created_at.epochSeconds)) AS age_seconds,
     CASE WHEN e.last_seen IS NOT NULL
          THEN (now_ts.epochSeconds - e.last_seen.epochSeconds)
          ELSE NULL
     END AS seconds_since_last_seen
RETURN
  coalesce(e.id, elementId(e)) AS event_id,
  coalesce(e.title, e.message) AS title,
  e.severity AS severity,
  e.status AS status,
  ci.id AS ci_id,
  ci.name AS ci_name,
  md.id AS metricdef_id,
  md.name AS metricdef_name,
  age_seconds / 3600.0 AS age_hours,
  e.last_seen AS last_seen,
  CASE
    WHEN ci IS NULL OR md IS NULL THEN 'link_missing'
    WHEN age_seconds > age_threshold_s THEN 'older_than_threshold'
    WHEN seconds_since_last_seen IS NOT NULL AND seconds_since_last_seen > refresh_window_s
      THEN 'no_refresh_in_window'
    ELSE NULL
  END AS reason_code,
  CASE
    WHEN ci IS NULL OR md IS NULL THEN 'no_link'
    WHEN e.last_seen IS NULL THEN 'never_refreshed'
    WHEN seconds_since_last_seen IS NOT NULL AND seconds_since_last_seen > refresh_window_s
      THEN 'stale_refresh'
    ELSE 'fresh'
  END AS refresh_status
ORDER BY age_seconds DESC
LIMIT $limit
""".strip()


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StaleEventRecommendation:
    """One stale-event advisory row.

    Mirrors the JSON contract in
    ``openspec/changes/feat-154-stale-event-reminders/design.md``
    (Interfaces / Contracts → Backend JSON response shape). Fields are
    nullable to support ``link_missing`` rows where the upstream CI /
    MetricDef has been deleted.
    """

    event_id: str
    title: str | None = None
    severity: str | None = None
    status: str | None = None
    ci_id: str | None = None
    ci_name: str | None = None
    metricdef_id: str | None = None
    metricdef_name: str | None = None
    age_hours: float | None = None
    last_seen: Any = None
    refresh_status: str | None = None
    reason_code: str | None = None
    quick_actions: tuple[str, ...] = field(default_factory=lambda: QUICK_ACTIONS)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> StaleEventRecommendation:
        """Build a row from a Neo4j record mapping.

        Drops rows whose ``reason_code`` is NULL — only events with at
        least one stale reason code appear in the advisory list.
        """
        reason_code = _optional_str(row.get("reason_code"))
        if reason_code not in REASON_CODES:
            raise ValueError(
                "stale_event_recommendation.reason_code must be one of "
                f"{REASON_CODES!r}, got {reason_code!r}"
            )
        refresh_status = _optional_str(row.get("refresh_status"))
        if refresh_status not in REFRESH_STATUSES:
            raise ValueError(
                "stale_event_recommendation.refresh_status must be one of "
                f"{REFRESH_STATUSES!r}, got {refresh_status!r}"
            )
        event_id = _optional_str(row.get("event_id")) or "unknown-event"
        return cls(
            event_id=event_id,
            title=_optional_str(row.get("title")),
            severity=_optional_str(row.get("severity")),
            status=_optional_str(row.get("status")),
            ci_id=_optional_str(row.get("ci_id")),
            ci_name=_optional_str(row.get("ci_name")),
            metricdef_id=_optional_str(row.get("metricdef_id")),
            metricdef_name=_optional_str(row.get("metricdef_name")),
            age_hours=_optional_float(row.get("age_hours")),
            last_seen=row.get("last_seen"),
            refresh_status=refresh_status,
            reason_code=reason_code,
            quick_actions=QUICK_ACTIONS,
        )

    def to_dict(self) -> dict[str, Any]:
        """Render the row as JSON-compatible data."""
        return {
            "event_id": self.event_id,
            "title": self.title,
            "severity": self.severity,
            "status": self.status,
            "ci_id": self.ci_id,
            "ci_name": self.ci_name,
            "metricdef_id": self.metricdef_id,
            "metricdef_name": self.metricdef_name,
            "age_hours": self.age_hours,
            "last_seen": _json_value(self.last_seen),
            "refresh_status": self.refresh_status,
            "reason_code": self.reason_code,
            "quick_actions": list(self.quick_actions),
        }


@dataclass(frozen=True)
class StaleEventRecommendationsResponse:
    """Schema-versioned envelope for the recommendations endpoint.

    Mirrors ``LegacyEventBackfillRecommendation`` shape but flattened —
    the response is a snapshot of detection results, not a rollup
    recommendation. ``settings_snapshot`` records the runtime thresholds
    used for this response so downstream consumers can reproduce the
    classification.
    """

    schema_version: str
    generated_at: str
    settings_snapshot: Mapping[str, Any]
    rows: list[StaleEventRecommendation]
    total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "settings": dict(self.settings_snapshot),
            "rows": [row.to_dict() for row in self.rows],
            "total": self.total,
        }


# ---------------------------------------------------------------------------
# Detection entry point + helpers
# ---------------------------------------------------------------------------


def build_stale_event_recommendations(
    driver: Any,
    *,
    age_hours: int,
    refresh_window_hours: int,
    limit: int = DEFAULT_LIMIT,
) -> StaleEventRecommendationsResponse:
    """Run the read-only detection query and wrap the rows.

    Parameters mirror the runtime settings in
    ``StaleEventReminderSettings`` (``config.py``). The router is
    responsible for short-circuiting when ``enabled`` is False — this
    function assumes the surface is active.

    No mutation is possible from this path: the session opens with
    ``READ_ACCESS`` (or no access hint when neo4j is unavailable) and
    the Cypher string contains only ``MATCH`` / ``OPTIONAL MATCH`` /
    ``WITH`` / ``RETURN`` / ``ORDER BY`` / ``LIMIT`` keywords.
    """
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ValueError(f"limit must be within [{MIN_LIMIT}, {MAX_LIMIT}], got {limit}")
    parameters = {
        "statuses": list(TARGET_STATUSES),
        "event_type": TARGET_EVENT_TYPE,
        "failure_family": TARGET_FAILURE_FAMILY,
        "age_hours": int(age_hours),
        "refresh_window_hours": int(refresh_window_hours),
        "limit": int(limit),
    }

    rows: list[StaleEventRecommendation] = []
    with _open_read_session(driver) as session:
        results = _execute_read_query(session, parameters)
        for raw in results:
            record = _as_mapping(raw)
            # Neo4j returns NULL for the CASE ELSE branch — skip those rows.
            if record.get("reason_code") is None:
                continue
            try:
                rows.append(StaleEventRecommendation.from_mapping(record))
            except ValueError:
                # Defensive: an unexpected reason_code from the driver is
                # surfaced in logs but never crashes the endpoint.
                continue

    generated_at = _utcnow_iso()
    settings_snapshot = {
        "age_hours": int(age_hours),
        "refresh_window_hours": int(refresh_window_hours),
        "limit": int(limit),
    }
    return StaleEventRecommendationsResponse(
        schema_version=RECOMMENDATION_SCHEMA_VERSION,
        generated_at=generated_at,
        settings_snapshot=settings_snapshot,
        rows=rows,
        total=len(rows),
    )


def recommendation_to_json_dict(
    response: StaleEventRecommendationsResponse,
) -> dict[str, Any]:
    """Render the envelope as deterministic JSON-compatible data."""
    return response.to_dict()


def recommendation_to_markdown(response: StaleEventRecommendationsResponse) -> str:
    """Render the envelope as deterministic reviewer-facing Markdown.

    Same model as ``recommendation_to_json_dict`` — they MUST stay in
    parity (count + per-row fields). Markdown is suitable for clipboard
    review and incident handoff.
    """
    lines = [
        "# Stale Event Reminder Recommendation",
        "",
        f"- Schema version: `{response.schema_version}`",
        f"- Generated at: {response.generated_at}",
        f"- Total rows: {response.total}",
        "",
        "## Settings Snapshot",
        f"- Age threshold (hours): {response.settings_snapshot.get('age_hours')}",
        f"- Refresh window (hours): {response.settings_snapshot.get('refresh_window_hours')}",
        f"- Inspection limit: {response.settings_snapshot.get('limit')}",
        "",
        "Advisory only — does not close events. Mutation is impossible from this surface.",
        "",
        "## Rows",
    ]
    if not response.rows:
        lines.append("No stale events detected.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Event ID | Title | Severity | Status | Reason | Age (h) | CI | MetricDef | Quick actions |",
            "|---|---|---|---|---|---:|---|---|---|",
        ]
    )
    for row in response.rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.event_id),
                    _md(row.title or "—"),
                    _md(row.severity or "—"),
                    _md(row.status or "—"),
                    f"`{_md(row.reason_code or '—')}`",
                    f"{row.age_hours:.2f}" if row.age_hours is not None else "—",
                    _md(row.ci_name or row.ci_id or "—"),
                    _md(row.metricdef_name or row.metricdef_id or "—"),
                    ", ".join(f"`{action}`" for action in row.quick_actions),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Internal helpers — mirror legacy_event_discriminator_audit.py
# ---------------------------------------------------------------------------


def _open_read_session(driver: Any) -> Any:
    session_kwargs = _read_session_kwargs()
    try:
        return driver.session(**session_kwargs)
    except TypeError:
        if session_kwargs:
            return driver.session()
        raise


def _read_session_kwargs() -> dict[str, Any]:
    if _NEO4J_READ_ACCESS is None:
        return {}
    return {"default_access_mode": _NEO4J_READ_ACCESS}


def _execute_read_query(session: Any, parameters: Mapping[str, Any]) -> Iterable[Any]:
    if hasattr(session, "execute_read"):
        return session.execute_read(lambda tx: _run_detection_query(tx, parameters))
    if hasattr(session, "read_transaction"):
        return session.read_transaction(lambda tx: _run_detection_query(tx, parameters))
    return _run_detection_query(session, parameters)


def _run_detection_query(transaction: Any, parameters: Mapping[str, Any]) -> Iterable[Any]:
    result = transaction.run(READ_ONLY_DETECTION_QUERY, **parameters)
    if hasattr(result, "data"):
        try:
            return list(result)
        except Exception:
            return list(result)
    return list(result)


def _as_mapping(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    if hasattr(row, "data"):
        return row.data()
    return dict(row)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()
