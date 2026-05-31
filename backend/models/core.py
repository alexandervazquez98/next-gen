from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel
from datetime import datetime

# --- Models -->


class Node(BaseModel):
    """Pydantic model representing a Configuration Item (CI) Node."""

    id: str
    label: str
    type: str
    status: Optional[str] = "OK"
    ip: Optional[str] = None
    location: Optional[dict] = None
    metadata: Optional[dict] = {}
    # Flattened Fields (Optional)
    owner: Optional[str] = None
    location_name: Optional[str] = None
    pollingInterval: Optional[int] = 60
    snmp: Optional[Union[dict, str]] = None  # Can be dict or JSON string
    brand: Optional[str] = None
    model: Optional[str] = None
    serialNumber: Optional[str] = None
    firmwareVersion: Optional[str] = None
    metrics: Optional[List[Dict[str, Any]]] = []


class Link(BaseModel):
    """Pydantic model representing a Relationship Link between CIs."""

    source: str
    target: str
    relationship: str
    id: Optional[str] = None
    source_label: Optional[str] = None
    target_label: Optional[str] = None


class Category(BaseModel):
    name: str


class MetricDef(BaseModel):
    """Definition of a monitored metric."""

    id: str
    protocol: Literal["SNMP", "ICMP", "CLI"] = "SNMP"
    oid: Optional[str] = None
    warning: Optional[float] = None
    critical: Optional[float] = None
    dataType: Optional[str] = "INTEGER"
    unit: Optional[str] = None
    description: Optional[str] = None
    operator: Optional[str] = ">="
    criticality: Optional[int] = 1  # 1: Info, 2: Warning, 3: Exception
    applicable_to: Optional[Dict[str, List[str]]] = None
    polling_interval: Optional[int] = 60
    can_propagate: bool = True
    availability_source: Optional[Literal["PING", "ICMP"]] = None
    # CLI-specific fields (optional, validated only when protocol == "CLI")
    cli_command: Optional[str] = None
    cli_target: Optional[str] = None
    cli_value_extractor: Optional[str] = None
    cli_credential_ref: Optional[str] = None
    cli_escalation_script: Optional[str] = None
    cli_protocol: Optional[Literal["SSH", "Telnet"]] = "SSH"
    cli_timeout: Optional[int] = 30


class HardwareModel(BaseModel):
    brand: str
    model: str
    category: Optional[str] = None
    owner: Optional[str] = None


class OwnerGroup(BaseModel):
    name: str
    users: Optional[List[dict]] = []


class BusinessService(BaseModel):
    id: str
    name: str
    tier: Optional[str] = None
    owner_t1: Optional[str] = None
    owner_t2: Optional[str] = None
    owner_t3: Optional[str] = None
    impacted_users_count: Optional[int] = None


class ServiceCatalog(BaseModel):
    id: str
    category: str
    service_tier: Optional[str] = None
    sla_minutes: Optional[int] = None


class CIRef(BaseModel):
    id: str
    label: Optional[str] = None
    hostname: Optional[str] = None
    location_name: Optional[str] = None


class EventFeedSummary(BaseModel):
    id: str
    ci_id: str
    metric_id: Optional[str] = None
    status: Literal["OPEN", "ACK", "CLOSED", "RECOVERED"]
    severity: Literal["CRITICAL", "WARNING", "INFO"]
    message: str
    created_at: Optional[str] = None
    last_seen: Optional[str] = None
    ack: bool = False
    ack_at: Optional[str] = None
    closed_at: Optional[str] = None
    recovered_at: Optional[str] = None
    ci_name: Optional[str] = None
    ci_node_id: Optional[str] = None
    ci_hostname: Optional[str] = None
    ci_location_name: Optional[str] = None
    metric_name: Optional[str] = None
    metric_protocol: Optional[str] = None
    event_type: Optional[str] = None
    source_protocol: Optional[str] = None
    propagated_from: Optional[str] = None
    correlation_type: Optional[Literal["ROOT", "PROPAGATED"]] = None
    root_cause_ci_id: Optional[str] = None


class EventDetailEvent(EventFeedSummary):
    ack_by: Optional[str] = None
    closed_by: Optional[str] = None
    comments: Optional[List[str]] = None
    ci_ref: CIRef


class BusinessContextService(BaseModel):
    id: str
    name: str
    tier: Optional[str] = None
    owner_t1: Optional[str] = None
    owner_t2: Optional[str] = None
    owner_t3: Optional[str] = None


class BusinessContextCatalog(BaseModel):
    id: str
    category: str
    service_tier: Optional[str] = None
    sla_minutes: Optional[int] = None


class BusinessContext(BaseModel):
    source: Literal["snapshot", "resolved", "mixed", "unavailable"]
    business_service: Optional[BusinessContextService] = None
    service_catalog: Optional[BusinessContextCatalog] = None
    impacted_users: Optional[int] = None
    sla_remaining_minutes: Optional[int] = None
    site: Optional[str] = None


class ExternalTicketRef(BaseModel):
    system: Literal["Jira", "ServiceNow"]
    key: str
    status: Optional[str] = None


class ItsmContext(BaseModel):
    assignment_state: Literal["unassigned", "assigned"]
    assigned_to: Optional[str] = None
    opened_by: Literal["system"] = "system"
    escalation_tier: Optional[Literal["T1", "T2", "T3"]] = None
    external_ticket: Optional[ExternalTicketRef] = None


class EventDetailResponse(BaseModel):
    event: EventDetailEvent
    business_context: BusinessContext
    itsm_context: ItsmContext


class AvailabilityReportCI(BaseModel):
    id: Optional[str] = None
    label: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    ip: Optional[str] = None
    location_name: Optional[str] = None
    owner: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    serialNumber: Optional[str] = None
    firmwareVersion: Optional[str] = None
    pollingInterval: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class AvailabilityReportRow(BaseModel):
    ci_id: str
    ci_name: Optional[str] = None
    event_type: str
    recovered_incidents: int
    mttr_seconds: Optional[float] = None
    mtbf_seconds: Optional[float] = None
    downtime_seconds: float
    active_events: int = 0
    active_downtime_seconds: float = 0
    availability_percentage: Optional[float] = None
    first_failure_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    ci: Optional[AvailabilityReportCI] = None


class AvailabilityReportResponse(BaseModel):
    window_start: str
    window_end: str
    generated_at: str
    window_days: float
    total_groups: int
    rows: List[AvailabilityReportRow]


class MetricDictionary(BaseModel):
    """A reusable OID bundle for a specific brand+model combination."""
    id: str
    name: str
    brand: str  # MANDATORY, exact match
    model: str  # MANDATORY, exact match
    metric_ids: list[str] = []
    polling_interval: int = 60
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AppliedDictionary(BaseModel):
    """Overlay node linking a CI to a dictionary with per-CI exclusions/extras."""
    id: str
    ci_id: str
    dictionary_id: str
    excluded_metrics: list[str] = []
    extra_metrics: list[str] = []
    applied_at: Optional[datetime] = None


class DictionaryCreate(BaseModel):
    id: str
    name: str
    brand: str
    model: str
    metric_ids: list[str] = []
    polling_interval: int = 60


class DictionaryUpdate(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    metric_ids: Optional[list[str]] = None
    polling_interval: Optional[int] = None
