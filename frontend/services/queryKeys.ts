export const queryKeys = {
  systemStatus: () => ['system-status'] as const,
  nodes: () => ['nodes'] as const,
  links: () => ['links'] as const,
  categories: () => ['categories'] as const,
  activeEvents: () => ['events', 'ACTIVE'] as const,
  graphTopology: () => ['graph-topology'] as const,
  relatedEvents: (ciId: string) => ['events', 'related', ciId] as const,
};
