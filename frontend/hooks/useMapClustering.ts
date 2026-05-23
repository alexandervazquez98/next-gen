/**
 * useMapClustering
 *
 * Clustering hook for map visualization. Groups nodes by location name first,
 * then applies proximity-based clustering using Haversine distance for remaining nodes.
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { GraphNode, Event } from '../types';

export interface ClusterMember {
  node: GraphNode;
  events: Event[];
}

export interface Cluster {
  id: string;
  label: string;
  centroid: [number, number]; // [lat, long]
  members: ClusterMember[];
  count: number;
  worstSeverity: 'CRITICAL' | 'WARNING' | 'INFO' | 'OK';
  isExpanded: boolean;
}

export interface UseMapClusteringOptions {
  proximityThresholdMeters?: number; // default 500
}

const DEFAULT_PROXIMITY_THRESHOLD = 500;
const FEATURE_FLAG_KEY = 'geoview-clustering::enabled:v2';

// ─────────────────────────────────────────────────────────────────────────────
// Pure Functions (exported for unit testing)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Calculate the Haversine distance between two geographic coordinates.
 * Returns distance in meters.
 */
export function haversineDistance(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): number {
  const R = 6371000; // Earth's radius in meters
  const toRad = (deg: number) => (deg * Math.PI) / 180;

  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) *
      Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);

  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/**
 * Groups nodes by location_name (case-insensitive, trimmed).
 * Returns Map where key is normalized location_name.
 */
export function computeLocationNameGroups(
  nodes: GraphNode[]
): Map<string, ClusterMember[]> {
  const groups = new Map<string, ClusterMember[]>();

  for (const node of nodes) {
    const key = (node.location_name ?? '').trim().toLowerCase();
    const member: ClusterMember = { node, events: [] };

    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(member);
  }

  return groups;
}

/**
 * Returns worst severity from array.
 * Priority: CRITICAL > WARNING > INFO > OK
 */
export function getWorstSeverity(
  events: Event[]
): 'CRITICAL' | 'WARNING' | 'INFO' | 'OK' {
  const priority = { CRITICAL: 4, WARNING: 3, INFO: 2, OK: 1 } as const;

  if (events.length === 0) return 'OK';

  let worst: 'CRITICAL' | 'WARNING' | 'INFO' | 'OK' = 'OK';
  for (const event of events) {
    if (priority[event.severity] > priority[worst]) {
      worst = event.severity;
    }
  }
  return worst;
}

/**
 * Compute proximity-based clusters using Haversine distance.
 * Uses a greedy clustering algorithm: each unclustered member forms a new cluster,
 * then nearby members (within threshold) are added to it.
 * @param idCounter Shared counter object; IDs are globally unique across all calls within a single buildClusters invocation.
 */
export function computeProximityClusters(
  members: ClusterMember[],
  thresholdMeters: number,
  idCounter: { next: number } = { next: 1 }
): Cluster[] {
  if (members.length === 0) return [];

  const clusters: Cluster[] = [];
  const clustered = new Set<string>();

  for (const member of members) {
    if (clustered.has(member.node.id)) continue;

    // Start a new cluster with this member
    const clusterMembers: ClusterMember[] = [member];
    clustered.add(member.node.id);

    // Find all members within threshold of the first member
    for (const other of members) {
      if (clustered.has(other.node.id)) continue;

      const loc1 = member.node.location;
      const loc2 = other.node.location;

      if (!loc1 || !loc2) continue;

      const distance = haversineDistance(
        loc1.lat,
        loc1.long,
        loc2.lat,
        loc2.long
      );

      if (distance <= thresholdMeters) {
        clusterMembers.push(other);
        clustered.add(other.node.id);
      }
    }

    // Calculate centroid
    let latSum = 0;
    let lonSum = 0;
    let validCount = 0;
    for (const m of clusterMembers) {
      if (m.node.location) {
        latSum += m.node.location.lat;
        lonSum += m.node.location.long;
        validCount++;
      }
    }
    const centroid: [number, number] = validCount > 0
      ? [latSum / validCount, lonSum / validCount]
      : [0, 0];

    // Build label from location_name if all members share one
    const locationNames = clusterMembers
      .map(m => m.node.location_name)
      .filter(Boolean);
    const label = locationNames.length === clusterMembers.length && locationNames[0]
      ? locationNames[0]
      : `Cluster ${idCounter.next}`;

    const allEvents = clusterMembers.flatMap(m => m.events);

    clusters.push({
      id: `cluster-${idCounter.next++}`,
      label,
      centroid,
      members: clusterMembers,
      count: clusterMembers.length,
      worstSeverity: getWorstSeverity(allEvents),
      isExpanded: false,
    });
  }

  return clusters;
}

/**
 * Main entry point: first groups by location_name, then proximity for leftovers.
 * Returns fully-formed Cluster[]
 */
export function buildClusters(
  nodes: GraphNode[],
  events: Event[],
  options?: UseMapClusteringOptions
): Cluster[] {
  if (nodes.length === 0) return [];

  // DEFENSIVE: only process nodes with valid location
  const validNodes = nodes.filter(n => n.location?.lat != null && n.location?.long != null);
  if (validNodes.length === 0) return [];

  const threshold = options?.proximityThresholdMeters ?? DEFAULT_PROXIMITY_THRESHOLD;

  // Group by location_name - use validNodes only
  const locationGroups = computeLocationNameGroups(validNodes);

  // Events indexed by ci_id for quick lookup
  const eventsByNode = new Map<string, Event[]>();
  for (const event of events) {
    if (!eventsByNode.has(event.ci_id)) {
      eventsByNode.set(event.ci_id, []);
    }
    eventsByNode.get(event.ci_id)!.push(event);
  }

  const clusters: Cluster[] = [];
  const idCounter = { next: 1 };

  // Process each location group
  for (const [locationName, members] of locationGroups) {
    // Enrich members with their events
    const enrichedMembers = members.map(m => ({
      node: m.node,
      events: eventsByNode.get(m.node.id) ?? [],
    }));

    if (enrichedMembers.length === 1) {
      // Single node at location — create cluster directly
      const member = enrichedMembers[0];
      const loc = member.node.location;
      clusters.push({
        id: `cluster-${idCounter.next++}`,
        label: locationName || member.node.label,
        centroid: loc ? [loc.lat, loc.long] : [0, 0],
        members: [member],
        count: 1,
        worstSeverity: getWorstSeverity(member.events),
        isExpanded: false,
      });
    } else {
      // Multiple nodes at same location — cluster by proximity
      const proximityClusters = computeProximityClusters(enrichedMembers, threshold, idCounter);
      clusters.push(...proximityClusters);
    }
  }

  // DEFENSIVE: filter out clusters with invalid centroids
  const filtered = clusters.filter(c =>
    Number.isFinite(c.centroid[0]) && Number.isFinite(c.centroid[1])
  );

  return filtered;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useMapClustering(
  nodes: GraphNode[],
  events: Event[],
  options?: UseMapClusteringOptions
): {
  clusters: Cluster[];
  isClustered: boolean;
  enabled: boolean;
  toggleClustering: () => void;
  expandedClusterId: string | null;
  expandCluster: (clusterId: string) => void;
  collapseCluster: () => void;
} {
  const [enabled, setEnabled] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(FEATURE_FLAG_KEY);
      if (stored !== null) {
        return stored === 'true';
      }
    } catch {
      // ignore
    }
    return true; // default to enabled
  });

  useEffect(() => {
    try {
      const stored = localStorage.getItem(FEATURE_FLAG_KEY);
      if (stored !== null) {
        setEnabled(stored === 'true');
      }
    } catch {
      // ignore
    }
  }, []);

  const [expandedClusterId, setExpandedClusterId] = useState<string | null>(null);

  const clusters = useMemo(() => {
    if (!enabled) return [];
    return buildClusters(nodes, events, options);
  }, [nodes, events, enabled, options]);

  const isClustered = useMemo(() => {
    return clusters.some(c => c.count > 1);
  }, [clusters]);

  const toggleClustering = useCallback(() => {
    setEnabled(prev => {
      const next = !prev;
      try {
        localStorage.setItem(FEATURE_FLAG_KEY, String(next));
      } catch {}
      return next;
    });
  }, []);

  const expandCluster = useCallback((clusterId: string) => {
    setExpandedClusterId(prev => prev === clusterId ? null : clusterId);
  }, []);

  const collapseCluster = useCallback(() => {
    setExpandedClusterId(null);
  }, []);

  return {
    clusters,
    isClustered,
    enabled,
    toggleClustering,
    expandedClusterId,
    expandCluster,
    collapseCluster,
  };
}
