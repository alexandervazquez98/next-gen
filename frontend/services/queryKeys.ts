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
  activeEvents: () => ["events", "CONSOLE"] as const,
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
};
