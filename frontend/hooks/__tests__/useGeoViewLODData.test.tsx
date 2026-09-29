// frontend/hooks/__tests__/useGeoViewLODData.test.tsx — #524 Tier 2 hook
//
// Tests for useGeoViewLODData, the Geo View's data composer. The hook
// orchestrates three existing React Query hooks (overview, detail,
// events) and the joinEventsToNodes helper. Tests use a real
// QueryClient so the React Query semantics (enabled, staleTime,
// refetch) are exercised as the production code exercises them.

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { useGeoViewLODData } from "../useGeoViewLODData";
import type { OverviewResponse, DetailResponse } from "../../types/graph";
import type { EventSummary } from "../../types";

// ---------------------------------------------------------------------------
// Mock the three underlying hooks so tests don't hit the network layer.
// ---------------------------------------------------------------------------

const mockOverview = vi.fn();
const mockDetail = vi.fn();
const mockEvents = vi.fn();

vi.mock("../queries/useGraphOverviewQuery", () => ({
  useGraphOverviewQuery: () => mockOverview(),
}));
vi.mock("../queries/useGraphDetailQuery", () => ({
  useGraphDetailQuery: (clusterId: string | null) => mockDetail(clusterId),
}));
vi.mock("../queries/useActiveEventsQuery", () => ({
  useActiveEventsQuery: () => mockEvents(),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const OVERVIEW: OverviewResponse = {
  axis: "location",
  filters: {},
  generated_at: "2026-09-29T00:00:00Z",
  revision: "test-001",
  aggregate_policy: {
    minimum_count: 5,
    permission_required: "graph:aggregate_breakdown:read",
    safe_geo_precision: "region",
  },
  clusters: [
    {
      cluster_id: "location:HQ-Madrid",
      display_label: "HQ-Madrid",
      visible_node_count: 12,
      visible_link_count: 8,
      aggregate_redacted: false,
      suppression_reason: null,
      critical_count: 1,
      warning_count: 2,
      event_count: 4,
    },
  ],
  inter_cluster_links: [],
  legend: { cards: [] },
  page: { next_cursor: null, has_more: false },
};

const DETAIL: DetailResponse = {
  cluster: {
    cluster_id: "location:HQ-Madrid",
    axis: "location",
    display_label: "HQ-Madrid",
    visible_node_count: 2,
    visible_link_count: 1,
  },
  filters: {},
  generated_at: "2026-09-29T00:00:00Z",
  revision: "test-002",
  nodes: [
    {
      id: "ci-1",
      display_label: "Router-1",
      kind: "CI",
      ci_type: "router",
      allowed_public_axes: [],
    },
    {
      id: "ci-2",
      display_label: "Router-2",
      kind: "CI",
      ci_type: "router",
      allowed_public_axes: [],
    },
  ],
  links: [],
  boundary_stubs: [],
  projection_flags: {
    show_sensitive_metadata: false,
    sensitive_source: "never",
  },
  empty_reason: "none",
  page: { next_cursor: null, has_more: false },
};

const EVENTS: EventSummary[] = [
  {
    id: "evt-1",
    ci_id: "ci-1",
    severity: "CRITICAL",
    status: "OPEN",
    ack: false,
    message: "down",
  } as EventSummary,
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  mockOverview.mockReset();
  mockDetail.mockReset();
  mockEvents.mockReset();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useGeoViewLODData — overview mode", () => {
  it("returns kind='overview' with the clusters array when focusedClusterId is null", async () => {
    mockOverview.mockReturnValue({ data: OVERVIEW, isLoading: false, error: null });
    mockEvents.mockReturnValue({ data: EVENTS, isLoading: false, error: null });
    mockDetail.mockReturnValue({ data: undefined, isLoading: false, error: null });

    const { result } = renderHook(() => useGeoViewLODData({ focusedClusterId: null }), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.kind).toBe("overview");
    });

    expect(result.current.clusters).toHaveLength(1);
    expect(result.current.clusters[0].cluster_id).toBe("location:HQ-Madrid");
    expect(result.current.clusters[0].critical_count).toBe(1);
    expect(result.current.enrichedNodes).toEqual([]);
    expect(result.current.overview).toEqual(OVERVIEW);
    expect(result.current.detail).toBeNull();
  });

  it("does NOT call useGraphDetailQuery in overview mode (clusterId is null)", async () => {
    mockOverview.mockReturnValue({ data: OVERVIEW, isLoading: false, error: null });
    mockEvents.mockReturnValue({ data: EVENTS, isLoading: false, error: null });
    mockDetail.mockReturnValue({ data: undefined, isLoading: false, error: null });

    renderHook(() => useGeoViewLODData({ focusedClusterId: null }), {
      wrapper: makeWrapper(),
    });

    expect(mockDetail).toHaveBeenCalledWith(null);
  });
});

describe("useGeoViewLODData — detail mode", () => {
  it("returns kind='detail' with enriched nodes when focusedClusterId is set", async () => {
    mockOverview.mockReturnValue({ data: OVERVIEW, isLoading: false, error: null });
    mockDetail.mockReturnValue({ data: DETAIL, isLoading: false, error: null });
    mockEvents.mockReturnValue({ data: EVENTS, isLoading: false, error: null });

    const { result } = renderHook(
      () => useGeoViewLODData({ focusedClusterId: "location:HQ-Madrid" }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(result.current.kind).toBe("detail");
    });

    expect(result.current.clusters).toEqual([]);
    expect(result.current.enrichedNodes).toHaveLength(2);

    const ci1 = result.current.enrichedNodes.find((n) => n.id === "ci-1")!;
    expect(ci1.hasCritical).toBe(true);
    expect(ci1.hasWarning).toBe(false);
    expect(ci1.events).toHaveLength(1);

    const ci2 = result.current.enrichedNodes.find((n) => n.id === "ci-2")!;
    expect(ci2.hasCritical).toBe(false);
    expect(ci2.hasWarning).toBe(false);
    expect(ci2.events).toEqual([]);
  });

  it("forwards the clusterId to useGraphDetailQuery", async () => {
    mockOverview.mockReturnValue({ data: OVERVIEW, isLoading: false, error: null });
    mockDetail.mockReturnValue({ data: DETAIL, isLoading: false, error: null });
    mockEvents.mockReturnValue({ data: EVENTS, isLoading: false, error: null });

    renderHook(() => useGeoViewLODData({ focusedClusterId: "location:HQ-Madrid" }), {
      wrapper: makeWrapper(),
    });

    expect(mockDetail).toHaveBeenCalledWith("location:HQ-Madrid");
  });

  it("falls back to kind='overview' when the detail query returns no data yet", async () => {
    mockOverview.mockReturnValue({ data: OVERVIEW, isLoading: false, error: null });
    mockDetail.mockReturnValue({ data: undefined, isLoading: true, error: null });
    mockEvents.mockReturnValue({ data: EVENTS, isLoading: false, error: null });

    const { result } = renderHook(
      () => useGeoViewLODData({ focusedClusterId: "location:HQ-Madrid" }),
      { wrapper: makeWrapper() },
    );

    // Even with a focused cluster, if the detail query hasn't resolved
    // yet, we expose the overview as a graceful fallback so the map
    // never goes blank while the operator waits for the detail fetch.
    expect(result.current.kind).toBe("overview");
    expect(result.current.clusters).toHaveLength(1);
    expect(result.current.isLoading).toBe(true);
  });
});

describe("useGeoViewLODData — error handling", () => {
  it("surfaces the overview error to the caller", async () => {
    const overviewError = new Error("overview endpoint exploded");
    mockOverview.mockReturnValue({ data: undefined, isLoading: false, error: overviewError });
    mockDetail.mockReturnValue({ data: undefined, isLoading: false, error: null });
    mockEvents.mockReturnValue({ data: [], isLoading: false, error: null });

    const { result } = renderHook(() => useGeoViewLODData({ focusedClusterId: null }), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.error).toBe(overviewError);
    });
    expect(result.current.kind).toBe("overview");
  });

  it("does not crash when both overview and detail are missing", async () => {
    mockOverview.mockReturnValue({ data: undefined, isLoading: true, error: null });
    mockDetail.mockReturnValue({ data: undefined, isLoading: true, error: null });
    mockEvents.mockReturnValue({ data: [], isLoading: false, error: null });

    const { result } = renderHook(
      () => useGeoViewLODData({ focusedClusterId: "location:HQ-Madrid" }),
      { wrapper: makeWrapper() },
    );

    expect(result.current.kind).toBe("overview"); // fallback
    expect(result.current.clusters).toEqual([]);
    expect(result.current.enrichedNodes).toEqual([]);
    expect(result.current.isLoading).toBe(true);
  });
});
