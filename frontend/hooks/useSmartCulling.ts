/**
 * useSmartCulling
 *
 * Smart culling hook that reduces the number of nodes shown on the map
 * when event count exceeds threshold. Uses localStorage to persist user preference.
 *
 * @param nodesWithEvents - array of nodes enriched with event data
 * @param events - full event array
 * @returns culled nodes based on smart mode state
 */

import { useState, useEffect, useMemo, useCallback } from "react";
import { rankCIs, SMART_CULL_THRESHOLD, TOP_N } from "../components/MonitoringConsole";

const STORAGE_KEY = "geoview-smart-culling::mode";

/**
 * Hard cap on rendered markers. When the topology has more than this many
 * nodes, smart culling is forced on regardless of the event threshold so the
 * map never tries to render thousands of CircleMarkers at once.
 */
export const HARD_CULL_NODE_THRESHOLD = 1000;

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

  const forced = nodesWithEvents.length > HARD_CULL_NODE_THRESHOLD;
  const effectiveSmartMode = forced || isSmartMode;

  const culledNodes = useMemo(() => {
    if (forced) {
      // Hard cap: always cull to TOP_N by severity rank.
      return rankCIs(nodesWithEvents, TOP_N);
    }
    if (events.length >= SMART_CULL_THRESHOLD && isSmartMode) {
      return rankCIs(nodesWithEvents, TOP_N);
    }
    return nodesWithEvents;
  }, [nodesWithEvents, events.length, isSmartMode, forced]);

  const toggle = useCallback(() => {
    if (forced) return; // Toggle disabled while hard cap is active.
    const newMode = !isSmartMode;
    setIsSmartMode(newMode);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newMode));
    } catch {
      // localStorage may be unavailable; ignore.
    }
  }, [isSmartMode, forced]);

  return { culledNodes, isActive: effectiveSmartMode, toggle, forced };
}
