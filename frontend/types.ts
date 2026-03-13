
export type NodeType = 'SERVICE' | 'INFRASTRUCTURE' | 'APPLICATION' | 'USER' | 'CLOUD_RESOURCE';

export interface SNMPConfig {
  version: 'v2c' | 'v3';
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
  status: string | null; // CRITICAL, WARNING, OK
  last_updated: string | null;
}

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  status: 'ACTIVE' | 'EXCEPTION' | 'MAINTENANCE' | 'OK';
  metadata: Record<string, any>;
  snmp?: SNMPConfig;
  pollingInterval?: number; // seconds
  thresholds?: MonitoringThresholds;
  metrics?: MetricValue[]; // Live metrics
  ip?: string;
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
  events?: Event[];
}

export interface GraphLink {
  id: string;
  source: string;
  target: string;
  relationship: 'DEPENDS_ON' | 'RUNS_ON' | 'PART_OF' | 'MANAGED_BY';
}

export interface Event {
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
  status: 'OPEN' | 'ACK' | 'CLOSED' | 'RECOVERED';
  severity: 'CRITICAL' | 'WARNING' | 'INFO';
  message: string;
  created_at: string;
  last_seen: string;
  ack: boolean;
  ack_at?: string;
  ack_by?: string;
  closed_at?: string;
  closed_by?: string;
  recovered_at?: string;
  comments?: string[];
}

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
}

export interface ApplicabilityCriteria {
  brands?: string[];
  models?: string[];
  layers?: string[];
  names?: string[];
  excluded_names?: string[];
}
