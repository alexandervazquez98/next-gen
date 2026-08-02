import ipaddress
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, field_validator

# --- Models -->


class Node(BaseModel):
    """Pydantic model representing a Configuration Item (CI) Node."""

    id: str
    label: str
    type: str
    status: str | None = "OK"
    ip: str | None = None
    # Slice 1 (feat-324): VPN tunnel relations need a routable, externally
    # reachable address to drive ICMP degradation probes. The CI `ip` field
    # is intentionally kept untouched; `public_ip` is opt-in and validated as
    # any IP address (v4 or v6). No backfill — CIs without an explicit
    # public_ip keep public_ip = None.
    public_ip: str | None = None
    location: dict | None = None
    metadata: dict | None = {}
    # Flattened Fields (Optional)
    owner: str | None = None
    location_name: str | None = None
    pollingInterval: int | None = 60  # noqa: N815
    snmp: dict | str | None = None  # Can be dict or JSON string
    brand: str | None = None
    model: str | None = None
    serialNumber: str | None = None  # noqa: N815
    firmwareVersion: str | None = None  # noqa: N815
    metrics: list[dict[str, Any]] | None = []

    @field_validator("public_ip")
    @classmethod
    def _validate_public_ip(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        try:
            ipaddress.ip_address(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"public_ip is not a valid IP address: {value!r}") from exc
        return value


class Link(BaseModel):
    """Pydantic model representing a Relationship Link between CIs."""

    source: str
    target: str
    relationship: str
    id: str | None = None
    source_label: str | None = None
    target_label: str | None = None
    # Slice 1 (feat-324): tunnel relation medium. Optional — legacy
    # non-tunnel links stay medium=None. Only the three documented values
    # are accepted; link_service validates the hub-obligatorio rule.
    medium: Literal["vpn", "sd_wan", "satellite"] | None = None

    @field_validator("medium")
    @classmethod
    def _validate_medium(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in ("vpn", "sd_wan", "satellite"):
            raise ValueError(f"medium must be one of 'vpn', 'sd_wan', 'satellite': {value!r}")
        return value


class Category(BaseModel):
    name: str
    icon_key: str | None = None


class MetricDef(BaseModel):
    """Definition of a monitored metric."""

    id: str
    protocol: Literal["SNMP", "ICMP", "CLI"] = "SNMP"
    oid: str | None = None
    warning: float | None = None
    critical: float | None = None
    dataType: str | None = "INTEGER"  # noqa: N815
    unit: str | None = None
    description: str | None = None
    operator: str | None = ">="
    criticality: int | None = 1  # 1: Info, 2: Warning, 3: Exception
    applicable_to: dict[str, list[str]] | None = None
    polling_interval: int | None = 60
    can_propagate: bool = True
    availability_source: Literal["PING", "ICMP"] | None = None
    # CLI-specific fields (optional, validated only when protocol == "CLI")
    cli_command: str | None = None
    cli_target: str | None = None
    cli_value_extractor: str | None = None
    cli_credential_ref: str | None = None
    cli_escalation_script: str | None = None
    cli_protocol: Literal["SSH", "Telnet"] | None = "SSH"
    cli_timeout: int | None = 30


class HardwareModel(BaseModel):
    brand: str
    model: str
    category: str | None = None
    owner: str | None = None


class OwnerGroup(BaseModel):
    name: str
    users: list[dict] | None = []


class BusinessService(BaseModel):
    id: str
    name: str
    tier: str | None = None
    owner_t1: str | None = None
    owner_t2: str | None = None
    owner_t3: str | None = None
    impacted_users_count: int | None = None


class ServiceCatalog(BaseModel):
    id: str
    category: str
    service_tier: str | None = None
    sla_minutes: int | None = None


class CIRef(BaseModel):
    id: str
    label: str | None = None
    hostname: str | None = None
    location_name: str | None = None


class EventFeedSummary(BaseModel):
    id: str
    ci_id: str
    metric_id: str | None = None
    status: Literal["OPEN", "ACK", "CLOSED", "RECOVERED"]
    severity: Literal["CRITICAL", "WARNING", "INFO"]
    message: str
    created_at: str | None = None
    last_seen: str | None = None
    ack: bool = False
    ack_at: str | None = None
    closed_at: str | None = None
    recovered_at: str | None = None
    ci_name: str | None = None
    ci_node_id: str | None = None
    ci_hostname: str | None = None
    ci_location_name: str | None = None
    metric_name: str | None = None
    metric_protocol: str | None = None
    event_type: str | None = None
    source_protocol: str | None = None
    propagated_from: str | None = None
    correlation_type: Literal["ROOT", "PROPAGATED"] | None = None
    root_cause_ci_id: str | None = None
    # P2: additive visible COUNT of affected CIs (mapped from Neo4j
    # `affected_ci_count`). `affected_ci_ids` is the membership list. Both
    # fields are dropped from the JSON payload when empty/None to preserve
    # the legacy contract for pre-P0 ROOT events.
    affected_ci_ids: list[str] | None = None
    affected_count: int | None = None


class AffectedCI(BaseModel):
    """Public response shape for `GET /api/events/{id}/affected`."""

    ci_id: str
    ci_name: str | None = None
    status: str | None = None
    ci_hostname: str | None = None
    ci_location_name: str | None = None


class EventDetailEvent(EventFeedSummary):
    ack_by: str | None = None
    closed_by: str | None = None
    comments: list[str] | None = None
    ci_ref: CIRef


class BusinessContextService(BaseModel):
    id: str
    name: str
    tier: str | None = None
    owner_t1: str | None = None
    owner_t2: str | None = None
    owner_t3: str | None = None


class BusinessContextCatalog(BaseModel):
    id: str
    category: str
    service_tier: str | None = None
    sla_minutes: int | None = None


class BusinessContext(BaseModel):
    source: Literal["snapshot", "resolved", "mixed", "unavailable"]
    business_service: BusinessContextService | None = None
    service_catalog: BusinessContextCatalog | None = None
    impacted_users: int | None = None
    sla_remaining_minutes: int | None = None
    site: str | None = None


class ExternalTicketRef(BaseModel):
    system: Literal["Jira", "ServiceNow"]
    key: str
    status: str | None = None


class ItsmContext(BaseModel):
    assignment_state: Literal["unassigned", "assigned"]
    assigned_to: str | None = None
    opened_by: Literal["system"] = "system"
    escalation_tier: Literal["T1", "T2", "T3"] | None = None
    external_ticket: ExternalTicketRef | None = None


class EventDetailResponse(BaseModel):
    event: EventDetailEvent
    business_context: BusinessContext
    itsm_context: ItsmContext


class AvailabilityReportCI(BaseModel):
    id: str | None = None
    label: str | None = None
    category: str | None = None
    type: str | None = None
    status: str | None = None
    ip: str | None = None
    location_name: str | None = None
    owner: str | None = None
    brand: str | None = None
    model: str | None = None
    serialNumber: str | None = None  # noqa: N815
    firmwareVersion: str | None = None  # noqa: N815
    pollingInterval: int | None = None  # noqa: N815
    metadata: dict[str, Any] | None = None


class AvailabilityReportRow(BaseModel):
    ci_id: str
    ci_name: str | None = None
    event_type: str
    recovered_incidents: int
    mttr_seconds: float | None = None
    mtbf_seconds: float | None = None
    downtime_seconds: float
    active_events: int = 0
    active_downtime_seconds: float = 0
    availability_percentage: float | None = None
    first_failure_at: str | None = None
    last_failure_at: str | None = None
    ci: AvailabilityReportCI | None = None


class SnmpCoverageSummary(BaseModel):
    total_ci_with_snmp: int = 0
    functional_ci: int = 0
    failing_ci: int = 0
    no_response_ci: int = 0
    no_response_event_count: int = 0
    functional_percentage: float | None = None
    failing_percentage: float | None = None


class AvailabilityReportResponse(BaseModel):
    window_start: str
    window_end: str
    generated_at: str
    window_days: float
    total_groups: int
    snmp_coverage: SnmpCoverageSummary | None = None
    rows: list[AvailabilityReportRow]


class AvailabilitySnmpNoResponseSummary(BaseModel):
    total_ci_with_no_response: int = 0
    total_events_with_no_response: int = 0


class AvailabilitySnmpNoResponseEvent(BaseModel):
    id: str | None = None
    message: str | None = None
    status: str | None = None
    created_at: str | None = None
    last_seen: str | None = None


class AvailabilitySnmpNoResponseCI(BaseModel):
    ci_id: str
    ci_name: str | None = None
    category: str | None = None
    status: str | None = None
    ip: str | None = None
    owner: str | None = None
    brand: str | None = None
    model: str | None = None
    event_count: int
    latest_event_at: str | None = None
    events: list[AvailabilitySnmpNoResponseEvent] = []


class AvailabilitySnmpNoResponseResponse(BaseModel):
    generated_at: str
    limit: int
    offset: int
    summary: AvailabilitySnmpNoResponseSummary
    rows: list[AvailabilitySnmpNoResponseCI]


class MetricDictionary(BaseModel):
    """A reusable OID bundle for a specific brand+model combination."""

    id: str
    name: str
    brand: str  # MANDATORY, exact match
    model: str  # MANDATORY, exact match
    metric_ids: list[str] = []
    polling_interval: int = 60
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AppliedDictionary(BaseModel):
    """Overlay node linking a CI to a dictionary with per-CI exclusions/extras."""

    id: str
    ci_id: str
    dictionary_id: str
    excluded_metrics: list[str] = []
    extra_metrics: list[str] = []
    applied_at: datetime | None = None


class DictionaryCreate(BaseModel):
    id: str
    name: str
    brand: str
    model: str
    metric_ids: list[str] = []
    polling_interval: int = 60


class DictionaryUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    metric_ids: list[str] | None = None
    polling_interval: int | None = None
