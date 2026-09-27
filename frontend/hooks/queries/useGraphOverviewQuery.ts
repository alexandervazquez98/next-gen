// frontend/hooks/queries/useGraphOverviewQuery.ts — #392 PR4
//
// React Query hook for the LOD overview endpoint. Replaces the
// initial ``/graph/full`` fetch in ``GraphCMDB`` so the first paint
// only loads location-cluster aggregates, not every CI node
// (REQ-1, REQ-OVERVIEW-2).
//
// Mirrors the shape of ``useGraphTopologyQuery`` for drop-in
// compatibility with the GraphCMDB consumer, but returns
// ``OverviewResponse`` from the v1.18.0 backend runtime slice.

import { useQuery } from "@tanstack/react-query";
import { fetchGraphOverview, type OverviewFilters } from "../../services/graphLod";

export const useGraphOverviewQuery = (filters: OverviewFilters = {}) =>
  useQuery({
    queryKey: ["graphOverview", filters] as const,
    queryFn: ({ signal }) => fetchGraphOverview(filters, signal),
    // No polling on the overview endpoint — the cluster summary is
    // stable until the operator expands a detail or refreshes manually.
    refetchInterval: false,
    staleTime: 30_000,
  });
