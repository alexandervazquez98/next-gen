"""Read-only audit for legacy Event discriminator risks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

try:
    from neo4j import READ_ACCESS as _NEO4J_READ_ACCESS
except ImportError:  # pragma: no cover - exercised only when neo4j is unavailable.
    _NEO4J_READ_ACCESS = None

MISSING_FIELD_CODES = {
    "event_type": "missing_event_type",
    "failure_family": "missing_failure_family",
    "source_protocol": "missing_source_protocol",
}

READ_ONLY_AUDIT_QUERY = """
MATCH (e:Event)
OPTIONAL MATCH (ci)-[:HAS_EVENT]->(e)
RETURN
  coalesce(e.id, elementId(e)) AS event_id,
  coalesce(e.ci_id, ci.id) AS ci_id,
  e.metric_id AS metric_id,
  e.status AS status,
  e.severity AS severity,
  e.message AS message,
  e.event_type AS event_type,
  e.failure_family AS failure_family,
  e.source_protocol AS source_protocol,
  e.availability_source AS availability_source,
  e.created_at AS created_at,
  e.last_seen AS last_seen,
  ci.name AS ci_name,
  e.metric_name AS metric_name
ORDER BY ci_id, metric_id, event_id
LIMIT $limit
""".strip()


@dataclass(frozen=True)
class LegacyEventAuditRecord:
    event_id: str
    ci_id: str | None = None
    metric_id: str | None = None
    status: str | None = None
    severity: str | None = None
    message: str | None = None
    event_type: str | None = None
    failure_family: str | None = None
    source_protocol: str | None = None
    availability_source: str | None = None
    created_at: Any = None
    last_seen: Any = None
    ci_name: str | None = None
    metric_name: str | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> LegacyEventAuditRecord:
        return cls(
            event_id=str(row.get("event_id") or row.get("id") or "unknown-event"),
            ci_id=_optional_str(row.get("ci_id")),
            metric_id=_optional_str(row.get("metric_id")),
            status=_optional_str(row.get("status")),
            severity=_optional_str(row.get("severity")),
            message=_optional_str(row.get("message")),
            event_type=_normalized(row.get("event_type")),
            failure_family=_normalized(row.get("failure_family")),
            source_protocol=_normalized(row.get("source_protocol")),
            availability_source=_normalized(row.get("availability_source")),
            created_at=row.get("created_at"),
            last_seen=row.get("last_seen"),
            ci_name=_optional_str(row.get("ci_name")),
            metric_name=_optional_str(row.get("metric_name")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "ci_id": self.ci_id,
            "metric_id": self.metric_id,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
            "event_type": self.event_type,
            "failure_family": self.failure_family,
            "source_protocol": self.source_protocol,
            "availability_source": self.availability_source,
            "created_at": _json_value(self.created_at),
            "last_seen": _json_value(self.last_seen),
            "ci_name": self.ci_name,
            "metric_name": self.metric_name,
        }


@dataclass(frozen=True)
class LegacyEventAuditFinding:
    finding_id: str
    code: str
    severity: str
    field: str | None
    description: str
    record: LegacyEventAuditRecord
    recommended_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.finding_id,
            "code": self.code,
            "severity": self.severity,
            "field": self.field,
            "description": self.description,
            "recommended_value": self.recommended_value,
            "record": self.record.to_dict(),
        }


@dataclass(frozen=True)
class LegacyEventAuditSummary:
    total_records: int
    total_findings: int
    findings_by_code: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "total_findings": self.total_findings,
            "findings_by_code": dict(sorted(self.findings_by_code.items())),
        }


@dataclass(frozen=True)
class LegacyEventAuditResult:
    summary: LegacyEventAuditSummary
    findings: list[LegacyEventAuditFinding]


def classify_legacy_event_records(records: Iterable[Mapping[str, Any]]) -> LegacyEventAuditResult:
    """Classify legacy Event rows without mutating or inferring discriminator values."""
    audit_records = [LegacyEventAuditRecord.from_mapping(_as_mapping(record)) for record in records]
    findings: list[LegacyEventAuditFinding] = []

    for record in audit_records:
        findings.extend(_missing_discriminator_findings(record))
        findings.extend(_ambiguous_boundary_findings(record))

    ordered_findings = sorted(findings, key=_finding_sort_key)
    summary = LegacyEventAuditSummary(
        total_records=len(audit_records),
        total_findings=len(ordered_findings),
        findings_by_code=dict(Counter(finding.code for finding in ordered_findings)),
    )
    return LegacyEventAuditResult(summary=summary, findings=ordered_findings)


def result_to_json_dict(result: LegacyEventAuditResult) -> dict[str, Any]:
    return {
        "summary": result.summary.to_dict(),
        "findings": [finding.to_dict() for finding in result.findings],
    }


def result_to_markdown(result: LegacyEventAuditResult) -> str:
    lines = [
        "# Legacy Event Discriminator Audit",
        "",
        "## Summary",
        f"- Total records: {result.summary.total_records}",
        f"- Total findings: {result.summary.total_findings}",
        "",
        "### Findings by Code",
    ]
    if result.summary.findings_by_code:
        for code, count in sorted(result.summary.findings_by_code.items()):
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Findings",
        ]
    )
    if not result.findings:
        lines.append("No legacy discriminator risks found.")
    else:
        lines.extend(
            [
                "| ID | Code | Severity | Event | CI | Metric | Description |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for finding in result.findings:
            record = finding.record
            lines.append(
                f"| {_md(finding.finding_id)} | `{_md(finding.code)}` | {_md(finding.severity)} | {_md(record.event_id)} | {_md(record.ci_id)} | {_md(record.metric_id)} | {_md(finding.description)} |"
            )
    return "\n".join(lines) + "\n"


def run_legacy_event_discriminator_audit(
    driver: Any, *, limit: int | None = None
) -> LegacyEventAuditResult:
    """Run the read-only audit query and classify returned Event rows."""
    query_limit = limit if limit is not None else 10_000
    with _open_read_session(driver) as session:
        return _execute_read_query(session, query_limit)


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


def _execute_read_query(session: Any, query_limit: int) -> LegacyEventAuditResult:
    if hasattr(session, "execute_read"):
        return session.execute_read(lambda tx: _run_audit_query(tx, query_limit))
    if hasattr(session, "read_transaction"):
        return session.read_transaction(lambda tx: _run_audit_query(tx, query_limit))
    return _run_audit_query(session, query_limit)


def _run_audit_query(transaction: Any, query_limit: int) -> LegacyEventAuditResult:
    rows = transaction.run(READ_ONLY_AUDIT_QUERY, limit=query_limit)
    return classify_legacy_event_records(_as_mapping(row) for row in rows)


def _missing_discriminator_findings(
    record: LegacyEventAuditRecord,
) -> list[LegacyEventAuditFinding]:
    findings: list[LegacyEventAuditFinding] = []
    values = {
        "event_type": record.event_type,
        "failure_family": record.failure_family,
        "source_protocol": record.source_protocol,
    }
    for field, value in values.items():
        if _is_missing(value):
            code = MISSING_FIELD_CODES[field]
            findings.append(
                LegacyEventAuditFinding(
                    finding_id=_finding_id(record, code),
                    code=code,
                    severity="missing",
                    field=field,
                    description=f"Event is missing `{field}` and requires review before any backfill decision.",
                    record=record,
                )
            )
    return findings


def _ambiguous_boundary_findings(record: LegacyEventAuditRecord) -> list[LegacyEventAuditFinding]:
    findings: list[LegacyEventAuditFinding] = []
    if _may_be_collection_failure_boundary(record):
        code = "ambiguous_collection_failure_boundary"
        findings.append(
            LegacyEventAuditFinding(
                finding_id=_finding_id(record, code),
                code=code,
                severity="ambiguous",
                field=None,
                description="Legacy-null collection failure data could be generic collection failure or SNMP no-response; do not assign a definitive discriminator.",
                record=record,
            )
        )
    if _may_be_threshold_or_availability(record):
        code = "ambiguous_threshold_or_availability"
        findings.append(
            LegacyEventAuditFinding(
                finding_id=_finding_id(record, code),
                code=code,
                severity="ambiguous",
                field=None,
                description="Legacy-null non-collection data may represent threshold or availability semantics; keep it ambiguous for human review.",
                record=record,
            )
        )
    return findings


def _may_be_collection_failure_boundary(record: LegacyEventAuditRecord) -> bool:
    message = (record.message or "").lower()
    has_legacy_null = any(
        _is_missing(value)
        for value in (record.event_type, record.failure_family, record.source_protocol)
    )
    return has_legacy_null and (
        "collection failed" in message
        or "metric collection failed" in message
        or "timeout" in message
        or record.event_type == "COLLECTION_FAILURE"
    )


def _may_be_threshold_or_availability(record: LegacyEventAuditRecord) -> bool:
    message = (record.message or "").lower()
    has_legacy_event_null = _is_missing(record.event_type)
    availability_hint = record.source_protocol == "ICMP" or record.availability_source in {
        "PING",
        "ICMP",
    }
    threshold_hint = "threshold" in message or "breached" in message
    availability_text_hint = (
        "service/host down" in message or "host down" in message or "availability" in message
    )
    return has_legacy_event_null and (availability_hint or threshold_hint or availability_text_hint)


def _finding_sort_key(finding: LegacyEventAuditFinding) -> tuple[str, str, str, str]:
    record = finding.record
    return (
        record.ci_id or "",
        record.metric_id or "",
        record.event_id,
        finding.code,
    )


def _finding_id(record: LegacyEventAuditRecord, code: str) -> str:
    return f"{record.event_id}:{code}"


def _normalized(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip() == ""


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _as_mapping(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    if hasattr(row, "data"):
        return row.data()
    return dict(row)
