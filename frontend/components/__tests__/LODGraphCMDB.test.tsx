// frontend/components/__tests__/LODGraphCMDB.test.tsx — #392 PR4
//
// Verifies the new LOD-aware CMDB view: initial mount uses the
// overview endpoint (not /graph/full), renders clusters as cards,
// and surfaces click events for the cluster that will hydrate detail
// in PR5.

import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LODGraphCMDB from "../LODGraphCMDB";

const mockUseGraphOverviewQuery = vi.fn();
const mockUseGraphTopologyQuery = vi.fn();
const mockUseGraphDetailQuery = vi.fn();
const mockUseCategoriesQuery = vi.fn();
const mockUseOwnersQuery = vi.fn();

const overviewSnapshot = {
  axis: "location",
  filters: {},
  generated_at: "2026-09-26T20:00:00Z",
  revision: "test-revision-0001",
  aggregate_policy: {
    minimum_count: 5,
    permission_required: "graph:aggregate_breakdown:read",
    safe_geo_precision: "city",
  },
  clusters: [
    {
      cluster_id: "location:HQ-Madrid",
      display_label: "HQ-Madrid",
      visible_node_count: 50,
      visible_link_count: 12,
      aggregate_redacted: false,
      suppression_reason: null,
    },
    {
      cluster_id: "location:DC-East",
      display_label: "DC-East",
      visible_node_count: 100,
      visible_link_count: 25,
      aggregate_redacted: false,
      suppression_reason: null,
    },
    {
      cluster_id: "location:Edge-DC",
      display_label: "Edge-DC",
      visible_node_count: 2, // below the minimum_count threshold -> redacted
      visible_link_count: 0,
      aggregate_redacted: true,
      suppression_reason: "low_cardinality",
    },
  ],
  inter_cluster_links: [],
  legend: { cards: [] },
  page: { next_cursor: null, has_more: false },
};

vi.mock("../../hooks/queries/useGraphOverviewQuery", () => ({
  useGraphOverviewQuery: () => mockUseGraphOverviewQuery(),
}));
vi.mock("../../hooks/queries/useGraphDetailQuery", () => ({
  useGraphDetailQuery: () => mockUseGraphDetailQuery(),
}));
vi.mock("../../hooks/queries/useGraphTopologyQuery", () => ({
  useGraphTopologyQuery: () => mockUseGraphTopologyQuery(),
}));

const createWrapper = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

describe("LODGraphCMDB (#392 PR4)", () => {
  beforeEach(() => {
    mockUseGraphOverviewQuery.mockReset();
    mockUseGraphTopologyQuery.mockReset();
    mockUseGraphDetailQuery.mockReset();
    mockUseCategoriesQuery.mockReset();
    mockUseOwnersQuery.mockReset();
    mockUseCategoriesQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseOwnersQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseGraphTopologyQuery.mockReturnValue({ data: { nodes: [], links: [] }, isLoading: false });
    mockUseGraphOverviewQuery.mockReturnValue({ data: overviewSnapshot, isLoading: false });
    mockUseGraphDetailQuery.mockReturnValue({ data: undefined, isFetching: false });
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders one card per cluster with visible_node_count", () => {
    render(<LODGraphCMDB />, { wrapper: createWrapper() });

    const grid = screen.getByTestId("cluster-grid");
    const cards = within(grid).getAllByRole("button");
    expect(cards).toHaveLength(3);

    expect(
      within(screen.getByTestId("cluster-card-location:HQ-Madrid")).getByText("HQ-Madrid"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("cluster-card-location:HQ-Madrid")).getByText("50"),
    ).toBeInTheDocument();
  });

  it("marks low-cardinality clusters as aggregate_redacted", () => {
    render(<LODGraphCMDB />, { wrapper: createWrapper() });

    const edgeCard = screen.getByTestId("cluster-card-location:Edge-DC");
    expect(within(edgeCard).getByText(/Aggregate Redacted/i)).toBeInTheDocument();
  });

  it("shows loading state when overview is loading", () => {
    mockUseGraphOverviewQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
    });
    render(<LODGraphCMDB />, { wrapper: createWrapper() });
    expect(screen.getByText(/Loading LOD overview/i)).toBeInTheDocument();
  });

  it("shows error state when overview fetch fails and topology fallback also fails", () => {
    mockUseGraphOverviewQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("network unreachable"),
    });
    mockUseGraphTopologyQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("topology also unreachable"),
    });
    render(<LODGraphCMDB />, { wrapper: createWrapper() });
    expect(screen.getByText(/LOD overview unavailable/i)).toBeInTheDocument();
  });

  it("falls back to /graph/full topology when overview fails", () => {
    mockUseGraphOverviewQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("overview endpoint down"),
    });
    mockUseGraphTopologyQuery.mockReturnValue({
      data: {
        nodes: [
          { id: "ci-1", label: "Router-1", location_name: "HQ" },
          { id: "ci-2", label: "Server-1", location_name: "HQ" },
        ],
        links: [],
      },
      isLoading: false,
    });
    render(<LODGraphCMDB />, { wrapper: createWrapper() });
    expect(screen.getByTestId("fallback-view")).toBeInTheDocument();
    expect(screen.getByTestId("fallback-banner")).toBeInTheDocument();
    expect(screen.getByText(/Fallback active/i)).toBeInTheDocument();
    // Topology nodes render as cluster cards in the fallback
    const grid = screen.getByTestId("cluster-grid");
    expect(within(grid).getByText("Router-1")).toBeInTheDocument();
    expect(within(grid).getByText("Server-1")).toBeInTheDocument();
  });

  it("forwards cluster click to the onClusterClick callback", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();
    render(<LODGraphCMDB onClusterClick={handleClick} />, { wrapper: createWrapper() });

    await user.click(screen.getByTestId("cluster-card-location:HQ-Madrid"));

    expect(handleClick).toHaveBeenCalledTimes(1);
    expect(handleClick).toHaveBeenCalledWith(
      expect.objectContaining({
        cluster_id: "location:HQ-Madrid",
        display_label: "HQ-Madrid",
        visible_node_count: 50,
      }),
    );
  });

  it("falls back to empty-state when overview has no clusters (hidden-absent parity)", () => {
    mockUseGraphOverviewQuery.mockReturnValue({
      data: { ...overviewSnapshot, clusters: [] },
      isLoading: false,
    });
    render(<LODGraphCMDB />, { wrapper: createWrapper() });
    expect(screen.getByText(/No visible clusters/i)).toBeInTheDocument();
  });
});

describe("LODGraphCMDB detail hydration (#392 PR5)", () => {
  beforeEach(() => {
    mockUseGraphOverviewQuery.mockReset();
    mockUseGraphTopologyQuery.mockReset();
    mockUseGraphDetailQuery.mockReset();
    mockUseCategoriesQuery.mockReset();
    mockUseOwnersQuery.mockReset();
    mockUseCategoriesQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseOwnersQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseGraphTopologyQuery.mockReturnValue({ data: { nodes: [], links: [] }, isLoading: false });
    mockUseGraphOverviewQuery.mockReturnValue({ data: overviewSnapshot, isLoading: false });
    // Default detail mock returns a snapshot with two nodes so the
    // detail panel renders content. Tests that need different data
    // override via mockReturnValueOnce.
    mockUseGraphDetailQuery.mockReturnValue({
      data: {
        cluster: {
          cluster_id: "location:HQ-Madrid",
          axis: "location",
          display_label: "HQ-Madrid",
          visible_node_count: 2,
          visible_link_count: 1,
        },
        filters: {},
        generated_at: "2026-09-26T20:00:00Z",
        revision: "test-revision-0001",
        nodes: [
          {
            id: "ci-1",
            display_label: "Router-1",
            kind: "Router",
            ci_type: "Router",
            allowed_public_axes: [],
          },
          {
            id: "ci-2",
            display_label: "Server-1",
            kind: "Server",
            ci_type: "Server",
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
      },
      isFetching: false,
    });
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("opens the detail panel on cluster click and closes on close button", async () => {
    const user = userEvent.setup();
    // First call (clusterId=null): no detail data.
    // Second call (clusterId="location:HQ-Madrid"): detail data.
    mockUseGraphDetailQuery.mockReturnValueOnce({ data: undefined, isFetching: false });
    mockUseGraphDetailQuery.mockReturnValue({
      data: {
        cluster: {
          cluster_id: "location:HQ-Madrid",
          axis: "location",
          display_label: "HQ-Madrid",
          visible_node_count: 2,
          visible_link_count: 1,
        },
        filters: {},
        generated_at: "2026-09-26T20:00:00Z",
        revision: "test-revision-0001",
        nodes: [
          {
            id: "ci-1",
            display_label: "Router-1",
            kind: "Router",
            ci_type: "Router",
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
      },
      isFetching: false,
    });

    render(<LODGraphCMDB />, { wrapper: createWrapper() });
    expect(screen.queryByTestId("detail-panel")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("cluster-card-location:HQ-Madrid"));

    expect(screen.getByTestId("detail-panel")).toBeInTheDocument();
    expect(screen.getByText(/Detail: location:HQ-Madrid/i)).toBeInTheDocument();

    await user.click(screen.getByTestId("detail-close"));

    expect(screen.queryByTestId("detail-panel")).not.toBeInTheDocument();
  });

  it("renders detail nodes when the query returns data", async () => {
    const user = userEvent.setup();
    mockUseGraphDetailQuery.mockReturnValue({
      data: {
        cluster: {
          cluster_id: "location:HQ-Madrid",
          axis: "location",
          display_label: "HQ-Madrid",
          visible_node_count: 2,
          visible_link_count: 1,
        },
        filters: {},
        generated_at: "2026-09-26T20:00:00Z",
        revision: "test-revision-0001",
        nodes: [
          {
            id: "ci-1",
            display_label: "Router-1",
            kind: "Router",
            ci_type: "Router",
            allowed_public_axes: [],
          },
          {
            id: "ci-2",
            display_label: "Server-1",
            kind: "Server",
            ci_type: "Server",
            allowed_public_axes: [],
          },
        ],
        links: [],
        boundary_stubs: [],
        projection_flags: { show_sensitive_metadata: false, sensitive_source: "never" },
        empty_reason: "none",
        page: { next_cursor: null, has_more: false },
      },
      isFetching: false,
    });
    render(<LODGraphCMDB />, { wrapper: createWrapper() });
    await user.click(screen.getByTestId("cluster-card-location:HQ-Madrid"));

    const nodeList = screen.getByTestId("detail-nodes");
    expect(within(nodeList).getByText(/ci-1 — Router-1/)).toBeInTheDocument();
    expect(within(nodeList).getByText(/ci-2 — Server-1/)).toBeInTheDocument();
  });

  it("shows the hidden-absent copy when detail is hidden", async () => {
    const user = userEvent.setup();
    mockUseGraphDetailQuery.mockReturnValue({
      data: {
        cluster: null,
        filters: {},
        generated_at: "2026-09-26T20:00:00Z",
        revision: "test-revision-0001",
        nodes: [],
        links: [],
        boundary_stubs: [],
        projection_flags: { show_sensitive_metadata: false, sensitive_source: "never" },
        empty_reason: "hidden_absent",
        page: { next_cursor: null, has_more: false },
      },
      isFetching: false,
    });
    render(<LODGraphCMDB />, { wrapper: createWrapper() });
    await user.click(screen.getByTestId("cluster-card-location:HQ-Madrid"));

    expect(screen.getByText(/Hidden — externally indistinguishable/i)).toBeInTheDocument();
  });
});
