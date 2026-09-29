// frontend/hooks/useGeoViewLODData.ts — #524 Tier 2 hook
//
// Composes the three React Query hooks that drive the Geo View of
// MonitoringConsole after the LOD migration:
//
//   - useGraphOverviewQuery  → location-cluster aggregates
//   - useGraphDetailQuery    → nodes within a focused cluster
//   - useActiveEventsQuery   → severity colors via events feed
//
// Plus the joinEventsToNodes helper to merge events into detail nodes.
//
// The hook returns a discriminated union:
//
//   { kind: "overview", clusters, ... }
//   { kind: "detail",   enrichedNodes, ... }
//
// so the consumer (MonitoringConsole) can switch render paths based
// on a single check, with no conditional hooks. The detail query is
// only enabled when focusedClusterId is non-null (delegated to
// useGraphDetailQuery's `enabled` flag — it already short-circuits
// when clusterId is null).

import { useMemo } from "react";

import type { DetailResponse, OverviewResponse } from "../types/graph";
import type { EventSummary } from "../types";
import { useGraphOverviewQuery } from "./queries/useGraphOverviewQuery";
import { useGraphDetailQuery } from "./queries/useGraphDetailQuery";
import { useActiveEventsQuery } from "./queries/useActiveEventsQuery";
import { joinEventsToNodes, type GeoViewNode } from "./geoViewLODData";

export interface UseGeoViewLODArgs {
  /**
   * `null` → overview mode (render clusters).
   * non-null → detail mode (render nodes within the focused cluster).
   * The transition is driven by the consumer (e.g., zoom level + a
   * cluster click).
   */
  focusedClusterId: string | null;
}

export type GeoViewLODState =
  | {
      kind: "overview";
      overview: OverviewResponse | null;
      detail: null;
      clusters: OverviewResponse["clusters"];
      enrichedNodes: never[];
      events: EventSummary[];
      isLoading: boolean;
      error: Error | null;
    }
  | {
      kind: "detail";
      overview: OverviewResponse | null;
      detail: DetailResponse | null;
      clusters: never[];
      enrichedNodes: GeoViewNode[];
      events: EventSummary[];
      isLoading: boolean;
      error: Error | null;
    };

export function useGeoViewLODData({ focusedClusterId }: UseGeoViewLODArgs): GeoViewLODState {
  // Overview is always fetched — it's the fallback path while a detail
  // query is in flight, and it's the only data source at country zoom.
  const overviewQuery = useGraphOverviewQuery();
  // Detail query is enabled only when focusedClusterId is non-null.
  // useGraphDetailQuery already handles the `enabled: Boolean(clusterId)`
  // case internally — passing null is the documented "skip" sentinel.
  const detailQuery = useGraphDetailQuery(focusedClusterId);
  // The events feed is the Geo View's color source. Same hook as the
  // Dashboard view uses today; #524 doesn't change this contract.
  const eventsQuery = useActiveEventsQuery(false);

  return useMemo<GeoViewLODState>(() => {
    const events = eventsQuery.data ?? [];
    const isLoading = overviewQuery.isLoading || eventsQuery.isLoading || detailQuery.isLoading;
    const error =
      (overviewQuery.error as Error | null) ??
      (detailQuery.error as Error | null) ??
      (eventsQuery.error as Error | null) ??
      null;

    // Detail mode: we have a clusterId AND the detail query has resolved.
    if (focusedClusterId && detailQuery.data) {
      const enrichedNodes = joinEventsToNodes(detailQuery.data.nodes, events);
      return {
        kind: "detail",
        overview: overviewQuery.data ?? null,
        detail: detailQuery.data,
        clusters: [],
        enrichedNodes,
        events,
        isLoading,
        error,
      };
    }

    // Overview mode (default) — also the fallback while the detail
    // query is in flight, so the map never blanks out.
    return {
      kind: "overview",
      overview: overviewQuery.data ?? null,
      detail: detailQuery.data ?? null,
      clusters: overviewQuery.data?.clusters ?? [],
      enrichedNodes: [],
      events,
      isLoading,
      error,
    };
  }, [
    focusedClusterId,
    overviewQuery.data,
    overviewQuery.isLoading,
    overviewQuery.error,
    detailQuery.data,
    detailQuery.isLoading,
    detailQuery.error,
    eventsQuery.data,
    eventsQuery.isLoading,
    eventsQuery.error,
  ]);
}
