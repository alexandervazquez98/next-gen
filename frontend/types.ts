export type NodeType = "SERVICE" | "INFRASTRUCTURE" | "APPLICATION" | "USER" | "CLOUD_RESOURCE";

export type CategoryIconKey =
  | "generic"
  | "switch_l2"
  | "switch_l3"
  | "router"
  | "server"
  | "saas"
  | "storage"
  | "camera"
  | "video_analytics"
  | "radio_telecom"
  | "trunk_link"
  | "access_ci"
  | "distribution_ci"
  | "vpn_tunnel"
  | "sd_wan_tunnel"
  | "satellite_link"
  | "vpn_hub";

export interface SNMPConfig {
  version: "v2c" | "v3";
  readCommunity?: string;
  writeCommunity?: string;
  authKey?: string;
  privKey?: string;
  port: number;
}

export interface MonitoringThresholds {
  cpu: number;
  memory: number;
  latency: number;
}

export interface MetricValue {
  name: string;
  protocol: string;
  oid: string;
  value: string | null;
  unit?: string;
  status: string | null; // CRITICAL, WARNING, OK
  last_updated: string | null;
}

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType | string;
  status: "ACTIVE" | "EXCEPTION" | "MAINTENANCE" | "OK";
  metadata: Record<string, unknown>;
  category_icon_key?: CategoryIconKey | null;
  snmp?: SNMPConfig;
  pollingInterval?: number; // seconds
  thresholds?: MonitoringThresholds;
  metrics?: MetricValue[]; // Live metrics
  ip?: string;
  public_ip?: string | null;
  location_name?: string;
  owner?: string; // Top-level owner group (matches backend Node.owner)
  category?: string; // Optional helper
  location?: { lat: number; long: number };
  serialNumber?: string;
  model?: string;
  brand?: string;
  firmwareVersion?: string;
  x?: number;
  y?: number;
  // UI Helpers (optional, added during runtime)
  hasCritical?: boolean;
  hasWarning?: boolean;
  events?: EventSummary[];
}

export interface IncidentEvent {
  id: string;
  timestamp: string;
  title: string;
  description: string;
  severity: "CRITICAL" | "WARNING" | "INFO" | string;
  status: string;
  affectedNodes: string[];
}

export interface AIAction {
  id: string;
  timestamp: string;
  incidentId: string;
  remedy: string;
  reasoning: string;
  confidence: number;
  executed: boolean;
}

export interface GraphLink {
  id: string;
  source: string;
  target: string;
  relationship:
    | "CONNECTS_TO"
    | "DEPENDS_ON"
    | "HOSTED_ON"
    | "MANAGES"
    | "USES"
    | "PROVIDES"
    | "RUNS_ON"
    | "HAS_METRIC"
    | "CATEGORIZED_AS";
  /**
   * Slice 1 (feat-324): tunnel medium for VPN / SD-WAN / satellite links.
   * Optional — legacy non-tunnel links stay shape-compatible.
   */
  medium?: "vpn" | "sd_wan" | "satellite";
}

export type TunnelMedium = NonNullable<GraphLink["medium"]>;
export type TunnelAuthorityStatus = "UP" | "DOWN" | "UNKNOWN";
export type TunnelVisualState = "up" | "down" | "unknown";
export type TunnelWarning = "icmp_failed" | "icmp_poor_rtt" | "missing_public_ip" | null;
export type TunnelHealthErrorKind = "bad_request" | "not_found" | "server" | "timeout" | "auth" | "network";

export interface TunnelAuthorityContext {
  state?: TunnelAuthorityStatus | null;
  source?: string | null;
  observed_at?: string | null;
  reason?: string | null;
}

export interface TunnelIcmpContext {
  available?: boolean | null;
  latency_ms?: number | null;
  error?: string | null;
  reason?: string | null;
}

export interface TunnelHealthResponse {
  link_id: string;
  source: string;
  target: string;
  relationship: GraphLink["relationship"] | string;
  medium: TunnelMedium;
  status: TunnelAuthorityStatus;
  authority: TunnelAuthorityContext;
  icmp: TunnelIcmpContext;
  observed_at?: string | null;
}

export interface TunnelTooltipRow {
  label: string;
  value: string;
}

export interface TunnelVisualModel {
  medium: TunnelMedium | null;
  mediumLabel: string;
  iconKey: CategoryIconKey;
  authorityText: TunnelAuthorityStatus;
  state: TunnelVisualState;
  warning: TunnelWarning;
  tooltipRows: TunnelTooltipRow[];
  healthAffectsIcon: false;
  stale: boolean;
  errorKind?: TunnelHealthErrorKind;
}

export interface TunnelHealthTelemetryPayload {
  window_seconds: 60;
  scheduled: number;
  skipped_over_cap: number;
  suppressed_cooldown: number;
  success: number;
  failure_by_kind: Partial<Record<TunnelHealthErrorKind, number>>;
  latency_bucket: Record<"lt_250" | "lt_1000" | "lt_5000" | "gte_5000", number>;
  kill_switch_enabled: boolean;
}

export interface AvailabilityReportCI {
  id?: string | null;
  label?: string | null;
  category?: string | null;
  type?: string | null;
  status?: string | null;
  ip?: string | null;
  location_name?: string | null;
  owner?: string | null;
  brand?: string | null;
  model?: string | null;
  serialNumber?: string | null;
  firmwareVersion?: string | null;
  pollingInterval?: number | null;
  metadata?: Record<string, unknown> | null;
}

export interface AvailabilityReportRow {
  ci_id: string;
  ci_name?: string | null;
  event_type: string;
  recovered_incidents: number;
  mttr_seconds?: number | null;
  mtbf_seconds?: number | null;
  downtime_seconds: number;
  active_events: number;
  active_downtime_seconds: number;
  availability_percentage?: number | null;
  first_failure_at?: string | null;
  last_failure_at?: string | null;
  ci?: AvailabilityReportCI | null;
}

export interface SnmpCoverageSummary {
  total_ci_with_snmp: number;
  functional_ci: number;
  failing_ci: number;
  no_response_ci: number;
  no_response_event_count: number;
  functional_percentage?: number | null;
  failing_percentage?: number | null;
}

export interface AvailabilityReportResponse {
  window_start: string;
  window_end: string;
  generated_at: string;
  window_days: number;
  total_groups: number;
  snmp_coverage?: SnmpCoverageSummary | null;
  rows: AvailabilityReportRow[];
}

export interface AvailabilitySnmpNoResponseSummary {
  total_ci_with_no_response: number;
  total_events_with_no_response: number;
}

export interface AvailabilitySnmpNoResponseEvent {
  id?: string | null;
  message?: string | null;
  status?: string | null;
  created_at?: string | null;
  last_seen?: string | null;
}

export interface AvailabilitySnmpNoResponseCI {
  ci_id: string;
  ci_name?: string | null;
  category?: string | null;
  status?: string | null;
  ip?: string | null;
  owner?: string | null;
  brand?: string | null;
  model?: string | null;
  event_count: number;
  latest_event_at?: string | null;
  events: AvailabilitySnmpNoResponseEvent[];
}

export interface AvailabilitySnmpNoResponseResponse {
  generated_at: string;
  limit: number;
  offset: number;
  summary: AvailabilitySnmpNoResponseSummary;
  rows: AvailabilitySnmpNoResponseCI[];
}

export interface EventSummary {
  id: string;
  ci_id: string;
  ci_name?: string;
  /** Real Neo4j node ID of the CI — populated by backend (ci.id) */
  ci_node_id?: string;
  /** IP address or hostname of the CI — populated by backend (ci.ip) */
  ci_hostname?: string;
  /** Human-readable location name — populated by backend (ci.locationName) */
  ci_location_name?: string;
  metric_id: string;
  metric_name?: string;
  metric_protocol?: string;
  status: "OPEN" | "ACK" | "CLOSED" | "RECOVERED";
  severity: "CRITICAL" | "WARNING" | "INFO";
  message: string;
  created_at?: string | null;
  last_seen?: string | null;
  ack: boolean;
  ack_at?: string;
  closed_at?: string;
  closed_by?: string;
  recovered_at?: string;
  event_type?: string;
  source_protocol?: string;
  relatedEvents?: EventSummary[];
}

export interface CIRef {
  id: string;
  label?: string | null;
  hostname?: string | null;
  location_name?: string | null;
}

export interface BusinessServiceRef {
  id: string;
  name: string;
  tier?: string | null;
  owner_t1?: string | null;
  owner_t2?: string | null;
  owner_t3?: string | null;
}

export interface ServiceCatalogRef {
  id: string;
  category: string;
  service_tier?: string | null;
  sla_minutes?: number | null;
}

export interface BusinessContext {
  source: "snapshot" | "resolved" | "mixed" | "unavailable";
  business_service?: BusinessServiceRef | null;
  service_catalog?: ServiceCatalogRef | null;
  impacted_users?: number | null;
  sla_remaining_minutes?: number | null;
  site?: string | null;
}

export interface ExternalTicketRef {
  system: "Jira" | "ServiceNow";
  key: string;
  status?: string | null;
}

export interface ItsmContext {
  assignment_state: "unassigned" | "assigned";
  assigned_to?: string | null;
  opened_by: "system";
  escalation_tier?: "T1" | "T2" | "T3" | null;
  external_ticket?: ExternalTicketRef | null;
}

export interface EventDetailEvent extends EventSummary {
  ci_ref: CIRef;
  comments?: string[];
  ack_by?: string | null;
}

export interface EventDetail {
  event: EventDetailEvent;
  business_context: BusinessContext;
  itsm_context: ItsmContext;
}

export type Event = EventSummary;

export interface MetricDef {
  id: string;
  protocol?: string;
  oid?: string;
  warning?: number | null;
  critical?: number | null;
  dataType?: string;
  unit?: string;
  description?: string;
  criticality?: 1 | 2 | 3; // 1: Info, 2: Warning, 3: Exception (Critical)
  operator?: string; // >=, <=, ==, !=
  applicable_to?: ApplicabilityCriteria;
  polling_interval?: number;
  // CLI-specific fields (present when protocol === "CLI")
  cli_command?: string;
  cli_target?: string;
  cli_value_extractor?: string;
  cli_credential_ref?: string;
  cli_escalation_script?: string;
  cli_protocol?: "SSH" | "Telnet";
  cli_timeout?: number;
}

export interface ApplicabilityCriteria {
  brands?: string[];
  models?: string[];
  layers?: string[];
  names?: string[];
  excluded_names?: string[];
}

// =============================================================================
// Multi-CI Metric Analytics Types
// =============================================================================

export interface DataPoint {
  time: string;
  value: number;
}

export interface NodeMetricData {
  node_id: string;
  label: string;
  metricName?: string;
  unit?: string;
  data: DataPoint[];
}

export interface MultiMetricHistoryRequest {
  nodeIds: string[];
  metricId: string;
  hours?: number;
  startTime?: string;
  endTime?: string;
  limit?: number;
}

export interface MultiMetricHistoryResponse {
  nodes: NodeMetricData[];
}
