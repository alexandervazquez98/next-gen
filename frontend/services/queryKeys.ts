export const queryKeys = {
  systemStatus: () => ["system-status"] as const,
  systemStatusHistory: (params: { hours?: number; limit?: number } = {}) =>
    [
      "system-status",
      "history",
      { hours: params.hours ?? 168, limit: params.limit ?? 24 },
    ] as const,
  nodes: () => ["nodes"] as const,
  links: () => ["links"] as const,
  tunnelHealth: (linkId: string) => ["tunnels", "health", linkId] as const,
  categories: () => ["categories"] as const,
  owners: () => ["owners"] as const,
  // P2 REQ-006: the `includeChildren` boolean is part of the cache key so
  // root-only and raw-mode polls never overwrite each other.
  activeEvents: (options: { includeChildren: boolean } = { includeChildren: false }) =>
    ["events", "CONSOLE", { includeChildren: options.includeChildren }] as const,
  affectedCIs: (eventId: string) => ["events", "affected", eventId] as const,
  availabilityReport: () => ["events", "availability-report"] as const,
  availabilitySnmpNoResponse: (params?: { limit?: number; offset?: number }) =>
    ["events", "availability-report", "snmp-no-response", params ?? {}] as const,
  eventDetail: (eventId: string) => ["events", "detail", eventId] as const,
  graphTopologyRoot: () => ["graph-topology"] as const,
  graphTopology: (filters?: {
    layer?: string | string[];
    location?: string | string[];
    owner?: string | string[];
  }) => ["graph-topology", filters ?? {}] as const,
  relatedEvents: (ciId: string) => ["events", "related", ciId] as const,
  // MQTT Monitoring Frontend (Issue #385) — PR1 keys.
  // Keep these aligned with `openspec/changes/feat-mqtt-385-frontend-ux/design.md`
  // so cache invalidation in `useMqttMutations` matches what the spec mandates.
  mqttDevices: () => ["mqtt", "devices"] as const,
  mqttDeviceMetrics: (deviceId: string | null) =>
    ["mqtt", "devices", deviceId ?? null, "metrics"] as const,
  mqttReadings: (params: { limit?: number } = {}) =>
    ["mqtt", "readings", { limit: params.limit ?? 100 }] as const,
  mqttStatus: () => ["mqtt", "status"] as const,
  mqttMappings: (params: { status?: string } = {}) =>
    ["mqtt", "mappings", { status: params.status ?? null }] as const,
  mqttMappingThresholds: (mappingId: string | null) =>
    ["mqtt", "mappings", mappingId ?? null, "thresholds"] as const,
};
