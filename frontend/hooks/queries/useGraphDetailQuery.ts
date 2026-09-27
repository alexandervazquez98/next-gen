// frontend/hooks/queries/useGraphDetailQuery.ts — #392 PR5
//
// React Query hook for the LOD detail endpoint. Replaces the legacy
// /graph/full payload when the operator expands a single cluster
// from the LOD overview (REQ-DETAIL-1, REQ-DETAIL-2).
//
// The hook is enabled only when ``clusterId`` is non-null. Zoom events
// (REQ-DETAIL-4) NEVER trigger a fetch — only explicit click or a
// committed search/filter target do.

import { useQuery } from "@tanstack/react-query";
import { fetchGraphDetail, type DetailFilters } from "../../services/graphLod";

export const useGraphDetailQuery = (clusterId: string | null, filters: DetailFilters = {}) =>
  useQuery({
    queryKey: ["graphDetail", clusterId, filters] as const,
    queryFn: ({ signal }) => {
      if (!clusterId) {
        // Defensive: the query is disabled when clusterId is null.
        // Returning a stable promise keeps the queryFn reference stable.
        return Promise.reject(new Error("graphDetail: clusterId is required"));
      }
      return fetchGraphDetail(clusterId, filters, signal);
    },
    enabled: Boolean(clusterId),
    // Zoom-triggered re-fetches are explicitly forbidden by the spec;
    // we only refetch on clusterId change or manual invalidation.
    refetchInterval: false,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });
