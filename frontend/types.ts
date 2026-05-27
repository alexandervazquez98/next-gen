export type NodeType =
	| "SERVICE"
	| "INFRASTRUCTURE"
	| "APPLICATION"
	| "USER"
	| "CLOUD_RESOURCE";

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
	type: NodeType;
	status: "ACTIVE" | "EXCEPTION" | "MAINTENANCE" | "OK";
	metadata: Record<string, any>;
	snmp?: SNMPConfig;
	pollingInterval?: number; // seconds
	thresholds?: MonitoringThresholds;
	metrics?: MetricValue[]; // Live metrics
	ip?: string;
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

export interface GraphLink {
	id: string;
	source: string;
	target: string;
	relationship: "DEPENDS_ON" | "RUNS_ON" | "PART_OF" | "MANAGED_BY";
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
}

export interface AvailabilityReportResponse {
	window_start: string;
	window_end: string;
	generated_at: string;
	window_days: number;
	total_groups: number;
	rows: AvailabilityReportRow[];
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
	created_at: string;
	last_seen: string;
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
