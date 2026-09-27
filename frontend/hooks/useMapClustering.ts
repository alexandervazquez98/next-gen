/**
 * useMapClustering
 *
 * Clustering hook for map visualization. Groups nodes by location_name first,
 * then applies proximity-based clustering using supercluster (O(n log n)) for
 * remaining nodes.
 */

import { useState, useEffect, useMemo, useCallback } from "react";
import Supercluster from "supercluster";
import type { ClusterProperties as SuperclusterClusterProperties } from "supercluster";
import { GraphNode, Event } from "../types";

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
  worstSeverity: "CRITICAL" | "WARNING" | "INFO" | "OK";
  isExpanded: boolean;
}

export interface UseMapClusteringOptions {
  /** Legacy proximity threshold in meters (used by `computeProximityClusters`).
   *  Kept for backward compatibility; ignored by the default supercluster path. */
  proximityThresholdMeters?: number;
  /** Supercluster radius in pixels. Default 80. */
  proximityRadiusPx?: number;
  /** Max zoom at which clustering applies. Beyond this, points render individually. Default 16. */
  maxZoom?: number;
  /** Zoom level used to query clusters. Default maxZoom (most disaggregated). */
  queryZoom?: number;
}

const DEFAULT_PROXIMITY_RADIUS_PX = 80;
const DEFAULT_MAX_ZOOM = 16;
const FEATURE_FLAG_KEY = "geoview-clustering::enabled:v2";

// ─────────────────────────────────────────────────────────────────────────────
// Pure Functions (exported for unit testing)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Calculate the Haversine distance between two geographic coordinates.
 * Returns distance in meters. Kept as a public utility for callers that
 * need distance computations outside of clustering (e.g. diagnostics).
 */
export function haversineDistance(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000; // Earth's radius in meters
  const toRad = (deg: number) => (deg * Math.PI) / 180;

  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) * Math.sin(dLon / 2);

  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/**
 * Legacy O(n²) proximity clustering using a greedy algorithm. Kept exported
 * for tests and for callers that explicitly want a static threshold-based
 * clustering. The default `buildClusters` now uses `supercluster` instead.
 */
export function computeProximityClusters(
  members: ClusterMember[],
  thresholdMeters: number,
  idCounter: { next: number } = { next: 1 },
): Cluster[] {
  if (members.length === 0) return [];

  const clusters: Cluster[] = [];
  const clustered = new Set<string>();

  for (const member of members) {
    if (clustered.has(member.node.id)) continue;

    const clusterMembers: ClusterMember[] = [member];
    clustered.add(member.node.id);

    for (const other of members) {
      if (clustered.has(other.node.id)) continue;

      const loc1 = member.node.location;
      const loc2 = other.node.location;
      if (!loc1 || !loc2) continue;

      const distance = haversineDistance(loc1.lat, loc1.long, loc2.lat, loc2.long);

      if (distance <= thresholdMeters) {
        clusterMembers.push(other);
        clustered.add(other.node.id);
      }
    }

    let latSum = 0;
    let lonSum = 0;
    let validCount = 0;
    for (const m of clusterMembers) {
      if (m.node.location) {
        latSum += m.node.location.lat;
        lonSum += m.node.location.long;
        validCount += 1;
      }
    }
    const centroid: [number, number] =
      validCount > 0 ? [latSum / validCount, lonSum / validCount] : [0, 0];

    const locationNames = clusterMembers.map((m) => m.node.location_name).filter(Boolean);
    const label =
      locationNames.length === clusterMembers.length && locationNames[0]
        ? locationNames[0]
        : `Cluster ${idCounter.next}`;

    const allEvents = clusterMembers.flatMap((m) => m.events);
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
 * Groups nodes by location_name (case-insensitive, trimmed).
 * Returns Map where key is normalized location_name.
 */
export function computeLocationNameGroups(nodes: GraphNode[]): Map<string, GraphNode[]> {
  const groups = new Map<string, GraphNode[]>();

  for (const node of nodes) {
    const key = (node.location_name ?? "").trim().toLowerCase();
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(node);
  }

  return groups;
}

/**
 * Returns worst severity from array.
 * Priority: CRITICAL > WARNING > INFO > OK
 */
export function getWorstSeverity(events: Event[]): "CRITICAL" | "WARNING" | "INFO" | "OK" {
  const priority = { CRITICAL: 4, WARNING: 3, INFO: 2, OK: 1 } as const;

  if (events.length === 0) return "OK";

  let worst: "CRITICAL" | "WARNING" | "INFO" | "OK" = "OK";
  for (const event of events) {
    if (priority[event.severity] > priority[worst]) {
      worst = event.severity;
    }
  }
  return worst;
}

/**
 * Build a supercluster index from a node list. The index is O(n log n) for
 * query vs the previous O(n²) Haversine-based proximity clustering.
 *
 * Properties carry the node + events so that getClusters(...) returns objects
 * that map 1:1 to ClusterMember[].
 */
export function buildSuperclusterIndex(
  members: ClusterMember[],
  options?: Pick<UseMapClusteringOptions, "maxZoom" | "proximityRadiusPx">,
): Supercluster<ClusterMember & { node: GraphNode; events: Event[] }, ClusterMember> {
  const features = members
    .filter((m) => m.node.location?.lat !== undefined && m.node.location?.long !== undefined)
    .map((m) => ({
      type: "Feature",
      properties: m,
      geometry: {
        type: "Point",
        // supercluster expects [longitude, latitude]
        coordinates: [m.node.location!.long, m.node.location!.lat],
      },
    }));

  const index = new Supercluster<ClusterMember, ClusterMember>({
    radius: options?.proximityRadiusPx ?? DEFAULT_PROXIMITY_RADIUS_PX,
    maxZoom: options?.maxZoom ?? DEFAULT_MAX_ZOOM,
  });
  index.load(features);
  return index;
}

/**
 * Query supercluster for clusters at a given zoom covering the world bounds.
 * Returns Cluster[] in the existing API shape.
 */
export function queryClusters(
  index: Supercluster<ClusterMember, ClusterMember>,
  _members: ClusterMember[],
  zoom: number,
  locationName: string,
): Cluster[] {
  // World bounds in [west, south, east, north] order.
  const clusters = index.getClusters([-180, -85, 180, 85], zoom);

  return clusters.map((c, idx): Cluster => {
    const [lng, lat] = c.geometry.coordinates as [number, number];
    const props = c.properties as Partial<SuperclusterClusterProperties> & ClusterMember;
    if (props.cluster === true) {
      // Aggregated cluster — leaves are retrieved via getLeaves(cluster_id, Infinity).
      const clusterId = props.cluster_id as number;
      const leaves = index.getLeaves(clusterId, Infinity);
      const clusterMembers: ClusterMember[] = leaves.map(
        (l) => l.properties as unknown as ClusterMember,
      );
      const allEvents = clusterMembers.flatMap((m) => m.events);
      return {
        id: `cluster-sc-${clusterId}`,
        label: locationName || `Cluster ${clusterId}`,
        centroid: [lat, lng],
        members: clusterMembers,
        count: clusterMembers.length,
        worstSeverity: getWorstSeverity(allEvents),
        isExpanded: false,
      };
    }
    // Leaf cluster — a single member
    const member = props as ClusterMember;
    return {
      id: `cluster-sc-${idx}`,
      label: member.node.location_name || member.node.label,
      centroid: [lat, lng],
      members: [member],
      count: 1,
      worstSeverity: getWorstSeverity(member.events),
      isExpanded: false,
    };
  });
}

/**
 * Main entry point: first groups by location_name, then supercluster for each
 * location group. Drop-in replacement for the previous O(n²) buildClusters.
 */
export function buildClusters(
  nodes: GraphNode[],
  events: Event[],
  options?: UseMapClusteringOptions,
): Cluster[] {
  if (nodes.length === 0) return [];

  // DEFENSIVE: only process nodes with valid location
  const validNodes = nodes.filter(
    (n) => n.location?.lat !== undefined && n.location?.long !== undefined,
  );
  if (validNodes.length === 0) return [];

  const queryZoom = options?.queryZoom ?? options?.maxZoom ?? DEFAULT_MAX_ZOOM;

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

  const out: Cluster[] = [];

  // Process each location group
  for (const [locationName, nodesInGroup] of locationGroups) {
    const members: ClusterMember[] = nodesInGroup.map((node) => ({
      node,
      events: eventsByNode.get(node.id) ?? [],
    }));

    if (members.length === 1) {
      const member = members[0];
      const loc = member.node.location;
      out.push({
        id: `cluster-sc-${out.length}`,
        label: locationName || member.node.label,
        centroid: loc ? [loc.lat, loc.long] : [0, 0],
        members: [member],
        count: 1,
        worstSeverity: getWorstSeverity(member.events),
        isExpanded: false,
      });
    } else {
      const index = buildSuperclusterIndex(members, options);
      const clusters = queryClusters(index, members, queryZoom, locationName);
      out.push(...clusters);
    }
  }

  // DEFENSIVE: filter out clusters with invalid centroids
  return out.filter((c) => Number.isFinite(c.centroid[0]) && Number.isFinite(c.centroid[1]));
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useMapClustering(
  nodes: GraphNode[],
  events: Event[],
  options?: UseMapClusteringOptions,
): {
  clusters: Cluster[];
  isClustered: boolean;
  enabled: boolean;
  toggleClustering: () => void;
  expandedClusterId: string | null;
  expandCluster: (_clusterId: string) => void;
  collapseCluster: () => void;
} {
  const [enabled, setEnabled] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(FEATURE_FLAG_KEY);
      if (stored !== null) {
        return stored === "true";
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
        setEnabled(stored === "true");
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
    return clusters.some((c) => c.count > 1);
  }, [clusters]);

  const toggleClustering = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(FEATURE_FLAG_KEY, String(next));
      } catch {
        // localStorage may be unavailable (private mode, quota); ignore.
      }
      return next;
    });
  }, []);

  const expandCluster = useCallback((_clusterId: string) => {
    setExpandedClusterId((prev) => (prev === _clusterId ? null : _clusterId));
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
