/**
 * useViewportCulling
 *
 * Returns the subset of nodes whose coordinates fall inside the current
 * Leaflet map viewport. Listens to `moveend` and `zoomend` and recomputes the
 * filter lazily. Used to cap the rendered marker count when the full topology
 * has thousands of CIs.
 *
 * The hook accepts the map instance via `useMap()` from react-leaflet. Callers
 * must invoke this inside a component that is a descendant of <MapContainer>.
 */

import { useEffect, useMemo, useState, useCallback } from 'react';
import { useMap } from 'react-leaflet';
import { GraphNode } from '../types';

interface LatLngBounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

function readBounds(map: L.Map): LatLngBounds {
  const b = map.getBounds();
  return {
    south: b.getSouth(),
    west: b.getWest(),
    north: b.getNorth(),
    east: b.getEast(),
  };
}

function nodeInBounds(node: GraphNode, bounds: LatLngBounds): boolean {
  const loc = node.location;
  if (!loc || loc.lat == null || loc.long == null) return false;
  // Antimeridian wrap: if west > east the viewport crosses the date line.
  if (bounds.west <= bounds.east) {
    return (
      loc.lat >= bounds.south &&
      loc.lat <= bounds.north &&
      loc.long >= bounds.west &&
      loc.long <= bounds.east
    );
  }
  return (
    loc.lat >= bounds.south &&
    loc.lat <= bounds.north &&
    (loc.long >= bounds.west || loc.long <= bounds.east)
  );
}

export function useViewportCulling(
  nodes: GraphNode[],
  options?: { includeUnlocated?: boolean }
): {
  visibleNodes: GraphNode[];
  bounds: LatLngBounds | null;
  zoom: number;
} {
  const map = useMap();
  const [bounds, setBounds] = useState<LatLngBounds | null>(() => readBounds(map));
  const [zoom, setZoom] = useState<number>(() => map.getZoom());

  const onChange = useCallback(() => {
    setBounds(readBounds(map));
    setZoom(map.getZoom());
  }, [map]);

  useEffect(() => {
    onChange();
    map.on('moveend', onChange);
    map.on('zoomend', onChange);
    return () => {
      map.off('moveend', onChange);
      map.off('zoomend', onChange);
    };
  }, [map, onChange]);

  const visibleNodes = useMemo(() => {
    if (!bounds) return nodes;
    const includeUnlocated = options?.includeUnlocated ?? true;
    return nodes.filter((n) => {
      if (!n.location || n.location.lat == null || n.location.long == null) {
        return includeUnlocated;
      }
      return nodeInBounds(n, bounds);
    });
  }, [nodes, bounds, options?.includeUnlocated]);

  return { visibleNodes, bounds, zoom };
}
