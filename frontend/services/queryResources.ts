import { api } from './api';
import type { Event, GraphLink, GraphNode } from '../types';

export interface SystemStatus {
  cpu: number;
  ram: number;
  disk: number;
  neo4j: 'CONNECTED' | 'DISCONNECTED' | 'UNKNOWN';
  collector: {
    status: string;
    last_run: string | null;
    stats: {
      cis_monitored: number;
      metrics_collected: number;
      metrics_failed: number;
      cycle_duration: number;
      jobs_per_min: number;
    };
  };
}

export interface CategoryRecord {
  name: string;
}

export interface GraphTopologyResponse {
  nodes: GraphNode[];
  links: GraphLink[];
}

export const fetchSystemStatus = ({ signal }: { signal?: AbortSignal } = {}) =>
  api.get<SystemStatus>('/system/status', { signal });

export const fetchNodes = ({ signal }: { signal?: AbortSignal } = {}) =>
  api.get<GraphNode[]>('/nodes', { signal });

export const fetchLinks = ({ signal }: { signal?: AbortSignal } = {}) =>
  api.get<GraphLink[]>('/links', { signal });

export const fetchCategories = ({ signal }: { signal?: AbortSignal } = {}) =>
  api.get<CategoryRecord[]>('/categories', { signal });

export const fetchActiveEvents = ({ signal }: { signal?: AbortSignal } = {}) =>
  api.get<Event[]>('/events?status=ACTIVE', { signal });

export const fetchRelatedEvents = (ciId: string, { signal }: { signal?: AbortSignal } = {}) =>
  api.get<Event[]>(`/events/related/${ciId}`, { signal });

export const fetchGraphTopology = ({ signal }: { signal?: AbortSignal } = {}) =>
  api.get<GraphTopologyResponse>('/graph/full', { signal });
