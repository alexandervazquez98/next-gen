/**
 * useSmartCulling
 *
 * Smart culling hook that reduces the number of nodes shown on the map
 * when event count exceeds threshold. Uses localStorage to persist user preference.
 *
 * @param nodesWithEvents - array of nodes enriched with event data
 * @param events - full event array
 * @returns culled nodes based on smart mode state
 *
 * #524 (Tier 2 LOD migration): the legacy hard cap at
 * ``HARD_CULL_NODE_THRESHOLD`` (1000 nodes) was removed. The Geo View
 * now sources its render data from the v1.18.0 LOD endpoints
 * (``useGeoViewLODData``), which means the backend handles culling
 * via server-side aggregation. The frontend smart-culling hook is now
 * strictly user-toggled and only kicks in when ``events.length >=
 * SMART_CULL_THRESHOLD``. The hook is retained because it still
 * governs the legacy individual-markers path (when clustering is OFF
 * and the operator wants every visible CI), but the forced lockout is
 * gone.
 */

import { useState, useEffect, useMemo, useCallback } from "react";
import { rankCIs, SMART_CULL_THRESHOLD, TOP_N } from "../components/MonitoringConsole";

const STORAGE_KEY = "geoview-smart-culling::mode";

export function useSmartCulling<T extends { events?: { severity: string }[] }>(
  nodesWithEvents: T[],
  events: { severity: string }[],
): {
  culledNodes: T[];
  isActive: boolean;
  toggle: () => void;
  forced: boolean;
} {
  const [isSmartMode, setIsSmartMode] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        return stored === "true";
      }
    } catch {
      // ignore
    }
    return events.length >= SMART_CULL_THRESHOLD;
  });

  useEffect(() => {
    // Sync with localStorage on mount (handles external changes)
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        setIsSmartMode(stored === "true");
      }
    } catch {
      // ignore
    }
  }, []);

  const culledNodes = useMemo(() => {
    if (events.length >= SMART_CULL_THRESHOLD && isSmartMode) {
      return rankCIs(nodesWithEvents, TOP_N);
    }
    return nodesWithEvents;
  }, [nodesWithEvents, events.length, isSmartMode]);

  const toggle = useCallback(() => {
    const newMode = !isSmartMode;
    setIsSmartMode(newMode);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newMode));
    } catch {
      // localStorage may be unavailable; ignore.
    }
  }, [isSmartMode]);

  return { culledNodes, isActive: isSmartMode, toggle, forced: false };
}
