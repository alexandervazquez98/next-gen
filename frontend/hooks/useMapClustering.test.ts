import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useMapClustering } from './useMapClustering';
import {
  haversineDistance,
  computeLocationNameGroups,
  computeProximityClusters,
  getWorstSeverity,
  buildClusters,
  ClusterMember,
} from './useMapClustering';
import { GraphNode, Event } from '../types';

const makeNode = (overrides: Partial<GraphNode>): GraphNode => ({
  id: 'node-1',
  label: 'Node 1',
  type: 'SERVICE',
  status: 'OK',
  metadata: {},
  location: { lat: 0, long: 0 },
  ...overrides,
});

const makeEvent = (overrides: Partial<Event>): Event => ({
  id: 'evt-1',
  ci_id: 'ci-1',
  metric_id: 'metric-1',
  status: 'OPEN',
  severity: 'INFO',
  message: 'Test',
  created_at: '2024-01-01T00:00:00Z',
  last_seen: '2024-01-01T00:00:00Z',
  ack: false,
  ...overrides,
});

describe('haversineDistance', () => {
  it('returns approximately 505km between Madrid and Barcelona', () => {
    // Madrid: 40.4168, -3.7038
    // Barcelona: 41.3851, 2.1734
    // Expected: ~505 km
    const distance = haversineDistance(40.4168, -3.7038, 41.3851, 2.1734);
    expect(distance).toBeCloseTo(505000, -3); // 505km ±500m
  });

  it('returns 0 for same coordinates', () => {
    const distance = haversineDistance(40.4168, -3.7038, 40.4168, -3.7038);
    expect(distance).toBe(0);
  });

  it('returns correct distance for known points', () => {
    // New York: 40.7128, -74.0060
    // Los Angeles: 34.0522, -118.2437
    const distance = haversineDistance(40.7128, -74.0060, 34.0522, -118.2437);
    expect(distance).toBeCloseTo(3935746, -2); // ~3936km
  });
});

describe('computeLocationNameGroups', () => {
  it('groups nodes by normalized location_name', () => {
    const nodes: GraphNode[] = [
      makeNode({ id: 'n1', location_name: 'Madrid' }),
      makeNode({ id: 'n2', location_name: 'madrid' }),
      makeNode({ id: 'n3', location_name: 'Barcelona' }),
    ];
    const result = computeLocationNameGroups(nodes);

    expect(result.get('madrid')).toHaveLength(2);
    expect(result.get('barcelona')).toHaveLength(1);
  });

  it('trims whitespace from location names', () => {
    const nodes: GraphNode[] = [
      makeNode({ id: 'n1', location_name: ' Madrid ' }),
      makeNode({ id: 'n2', location_name: 'Madrid' }),
    ];
    const result = computeLocationNameGroups(nodes);
    expect(result.get('madrid')).toHaveLength(2);
  });

  it('handles undefined location_name', () => {
    const nodes: GraphNode[] = [
      makeNode({ id: 'n1', location_name: undefined }),
      makeNode({ id: 'n2', location_name: undefined }),
    ];
    const result = computeLocationNameGroups(nodes);
    expect(result.get('')).toHaveLength(2);
  });

  it('returns empty map for empty array', () => {
    const result = computeLocationNameGroups([]);
    expect(result.size).toBe(0);
  });
});

describe('computeProximityClusters', () => {
  it('groups nodes within proximity threshold', () => {
    const members: ClusterMember[] = [
      { node: makeNode({ id: 'n1', location: { lat: 40.4168, long: -3.7038 } }), events: [] },
      { node: makeNode({ id: 'n2', location: { lat: 40.4170, long: -3.7035 } }), events: [] }, // ~30m away
    ];
    const clusters = computeProximityClusters(members, 500); // 500m threshold
    expect(clusters).toHaveLength(1);
    expect(clusters[0].members).toHaveLength(2);
  });

  it('separates nodes beyond threshold', () => {
    const members: ClusterMember[] = [
      { node: makeNode({ id: 'n1', location: { lat: 40.4168, long: -3.7038 } }), events: [] },
      { node: makeNode({ id: 'n2', location: { lat: 41.3851, long: 2.1734 } }), events: [] }, // Madrid vs Barcelona ~505km
    ];
    const clusters = computeProximityClusters(members, 500);
    expect(clusters).toHaveLength(2);
  });

  it('handles empty members array', () => {
    const clusters = computeProximityClusters([], 500);
    expect(clusters).toHaveLength(0);
  });

  it('assigns correct cluster ids', () => {
    const members: ClusterMember[] = [
      { node: makeNode({ id: 'n1', location: { lat: 40.4168, long: -3.7038 } }), events: [] },
      { node: makeNode({ id: 'n2', location: { lat: 40.4170, long: -3.7035 } }), events: [] },
    ];
    const clusters = computeProximityClusters(members, 500);
    expect(clusters[0].id).toBeDefined();
    expect(clusters[0].id.length).toBeGreaterThan(0);
  });
});

describe('getWorstSeverity', () => {
  it('returns CRITICAL when present', () => {
    const events = [
      makeEvent({ severity: 'INFO' }),
      makeEvent({ severity: 'CRITICAL' }),
      makeEvent({ severity: 'WARNING' }),
    ];
    expect(getWorstSeverity(events)).toBe('CRITICAL');
  });

  it('returns WARNING when no CRITICAL but WARNING present', () => {
    const events = [
      makeEvent({ severity: 'INFO' }),
      makeEvent({ severity: 'WARNING' }),
    ];
    expect(getWorstSeverity(events)).toBe('WARNING');
  });

  it('returns INFO when only INFO present', () => {
    const events = [
      makeEvent({ severity: 'INFO' }),
    ];
    expect(getWorstSeverity(events)).toBe('INFO');
  });

  it('returns OK for empty array', () => {
    expect(getWorstSeverity([])).toBe('OK');
  });

  it('handles mixed severity order', () => {
    const events = [
      makeEvent({ severity: 'OK' as any }), // Should not happen but test robustness
      makeEvent({ severity: 'WARNING' }),
      makeEvent({ severity: 'CRITICAL' }),
    ];
    expect(getWorstSeverity(events)).toBe('CRITICAL');
  });
});

describe('buildClusters', () => {
  it('groups by location_name first', () => {
    const nodes: GraphNode[] = [
      makeNode({ id: 'n1', location_name: 'Madrid', location: { lat: 40.4168, long: -3.7038 } }),
      makeNode({ id: 'n2', location_name: 'Madrid', location: { lat: 40.4170, long: -3.7035 } }),
    ];
    const events: Event[] = [];
    const clusters = buildClusters(nodes, events);
    expect(clusters).toHaveLength(1);
    expect(clusters[0].count).toBe(2);
  });

  it('uses proximity clustering for same location_name nodes far apart', () => {
    // Two nodes with same location_name but geographically distant
    const nodes: GraphNode[] = [
      makeNode({ id: 'n1', location_name: 'DC1', location: { lat: 40.4168, long: -3.7038 } }),
      makeNode({ id: 'n2', location_name: 'DC1', location: { lat: 41.3851, long: 2.1734 } }), // ~505km
    ];
    const events: Event[] = [];
    const clusters = buildClusters(nodes, events, { proximityThresholdMeters: 500 });
    expect(clusters).toHaveLength(2);
  });

  it('includes events in severity calculation', () => {
    const nodes: GraphNode[] = [
      makeNode({ id: 'n1', location_name: 'Madrid', location: { lat: 40.4168, long: -3.7038 } }),
    ];
    const events: Event[] = [
      makeEvent({ ci_id: 'n1', severity: 'WARNING' }),
      makeEvent({ ci_id: 'n1', severity: 'CRITICAL' }),
    ];
    const clusters = buildClusters(nodes, events);
    expect(clusters[0].worstSeverity).toBe('CRITICAL');
  });

  it('calculates centroid correctly', () => {
    // Use same location_name so they get proximity-clustered
    const nodes: GraphNode[] = [
      makeNode({ id: 'n1', location_name: 'Zone', location: { lat: 40.0, long: -3.0 } }),
      makeNode({ id: 'n2', location_name: 'Zone', location: { lat: 41.0, long: -4.0 } }),
    ];
    const clusters = buildClusters(nodes, [], { proximityThresholdMeters: 200000 }); // 200km threshold
    expect(clusters).toHaveLength(1);
    expect(clusters[0].centroid[0]).toBeCloseTo(40.5, 4);
    expect(clusters[0].centroid[1]).toBeCloseTo(-3.5, 4);
  });

  it('returns empty array for empty nodes', () => {
    const clusters = buildClusters([], []);
    expect(clusters).toHaveLength(0);
  });
});

describe('useMapClustering hook', () => {
  const nodes: GraphNode[] = [
    makeNode({ id: 'n1', location_name: 'Madrid', location: { lat: 40.4168, long: -3.7038 } }),
    makeNode({ id: 'n2', location_name: 'Madrid', location: { lat: 40.4170, long: -3.7035 } }),
    makeNode({ id: 'n3', location_name: 'Barcelona', location: { lat: 41.3851, long: 2.1734 } }),
  ];
  const events: Event[] = [];

  beforeEach(() => {
    localStorage.removeItem('geoview-clustering::enabled:v2');
  });

  describe('toggleClustering', () => {
    it('should toggle enabled from true to false', () => {
      localStorage.setItem('geoview-clustering::enabled:v2', 'true');
      const { result } = renderHook(() => useMapClustering(nodes, events));
      expect(result.current.enabled).toBe(true);

      act(() => {
        result.current.toggleClustering();
      });

      expect(result.current.enabled).toBe(false);
    });

    it('should toggle enabled from false to true', () => {
      localStorage.setItem('geoview-clustering::enabled:v2', 'false');
      const { result } = renderHook(() => useMapClustering(nodes, events));
      expect(result.current.enabled).toBe(false);

      act(() => {
        result.current.toggleClustering();
      });

      expect(result.current.enabled).toBe(true);
    });
  });

  describe('expandCluster', () => {
    it('should set expandedClusterId when called', () => {
      const { result } = renderHook(() => useMapClustering(nodes, events));

      act(() => {
        result.current.expandCluster('cluster-1');
      });

      expect(result.current.expandedClusterId).toBe('cluster-1');
    });

    it('should update expandedClusterId when called with different id', () => {
      const { result } = renderHook(() => useMapClustering(nodes, events));

      act(() => {
        result.current.expandCluster('cluster-1');
      });
      expect(result.current.expandedClusterId).toBe('cluster-1');

      act(() => {
        result.current.expandCluster('cluster-2');
      });

      expect(result.current.expandedClusterId).toBe('cluster-2');
    });
  });

  describe('collapseCluster', () => {
    it('should clear expandedClusterId', () => {
      const { result } = renderHook(() => useMapClustering(nodes, events));

      act(() => {
        result.current.expandCluster('some-id');
      });
      expect(result.current.expandedClusterId).toBe('some-id');

      act(() => {
        result.current.collapseCluster();
      });

      expect(result.current.expandedClusterId).toBeNull();
    });

    it('should handle collapse when no cluster is expanded', () => {
      const { result } = renderHook(() => useMapClustering(nodes, events));

      act(() => {
        result.current.collapseCluster();
      });

      expect(result.current.expandedClusterId).toBeNull();
    });
  });

  describe('feature flag default', () => {
    it('should default to true when localStorage key not set', () => {
      const { result } = renderHook(() => useMapClustering(nodes, events));
      expect(result.current.enabled).toBe(true);
    });
  });

  describe('isClustered', () => {
    it('should return true when clusters contain multiple nodes', () => {
      const { result } = renderHook(() => useMapClustering(nodes, events));
      expect(result.current.isClustered).toBe(true);
    });

    it('should return false when clustering is disabled', () => {
      localStorage.setItem('geoview-clustering::enabled:v2', 'false');
      const { result } = renderHook(() => useMapClustering(nodes, events));
      expect(result.current.enabled).toBe(false);
      expect(result.current.isClustered).toBe(false);
    });
  });
});
