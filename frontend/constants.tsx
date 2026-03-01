
import React from 'react';
import { GraphNode, GraphLink, IncidentEvent } from './types';

export const INITIAL_NODES: GraphNode[] = [
  { 
    id: 'payment-gateway', 
    label: 'Payment Gateway', 
    type: 'SERVICE', 
    status: 'HEALTHY', 
    metadata: { version: '2.4.0' },
    pollingInterval: 30,
    snmp: { version: 'v2c', community: 'pub-serv-01', port: 161 },
    thresholds: { cpu: 70, memory: 80, latency: 50 }
  },
  { 
    id: 'auth-api', 
    label: 'Auth API', 
    type: 'APPLICATION', 
    status: 'WARNING', 
    metadata: { uptime: '99.2%' },
    pollingInterval: 15,
    snmp: { version: 'v3', authKey: 'auth_v3_secure', port: 161 },
    thresholds: { cpu: 85, memory: 90, latency: 120 }
  },
  { 
    id: 'db-prod-01', 
    label: 'DB Cluster 01', 
    type: 'INFRASTRUCTURE', 
    status: 'HEALTHY', 
    metadata: { provider: 'AWS' },
    pollingInterval: 60,
    snmp: { version: 'v2c', community: 'read_db', port: 161 },
    thresholds: { cpu: 80, memory: 85, latency: 10 }
  },
  { 
    id: 'redis-cache', 
    label: 'Redis L1', 
    type: 'CLOUD_RESOURCE', 
    status: 'CRITICAL', 
    metadata: { latency: '240ms' },
    pollingInterval: 10,
    snmp: { version: 'v2c', community: 'public', port: 161 },
    thresholds: { cpu: 90, memory: 95, latency: 200 }
  },
];

export const INITIAL_LINKS: GraphLink[] = [
  { id: 'l1', source: 'auth-api', target: 'db-prod-01', relationship: 'RUNS_ON' },
  { id: 'l2', source: 'payment-gateway', target: 'auth-api', relationship: 'DEPENDS_ON' },
  { id: 'l3', source: 'payment-gateway', target: 'redis-cache', relationship: 'DEPENDS_ON' },
];

export const MOCK_INCIDENTS: IncidentEvent[] = [
  {
    id: 'INC-2024-001',
    timestamp: new Date().toISOString(),
    title: 'Redis Latency Spike',
    description: 'Redis L1 cache in region us-east-1 showing high memory pressure and latency > 200ms.',
    severity: 'CRITICAL',
    status: 'ANALYZING',
    affectedNodes: ['redis-cache']
  }
];

export const ICONS = {
  SERVICE: <span className="material-symbols-outlined">settings_input_component</span>,
  INFRASTRUCTURE: <span className="material-symbols-outlined">dns</span>,
  APPLICATION: <span className="material-symbols-outlined">layers</span>,
  USER: <span className="material-symbols-outlined">person</span>,
  CLOUD_RESOURCE: <span className="material-symbols-outlined">cloud</span>,
};
