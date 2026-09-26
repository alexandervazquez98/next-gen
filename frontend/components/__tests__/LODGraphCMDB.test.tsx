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
vi.mock("../../hooks/queries/useGraphTopologyQuery", () => ({
  useGraphTopologyQuery: () => mockUseGraphTopologyQuery(),
}));
vi.mock("../../hooks/queries/useCategoriesQuery", () => ({
  useCategoriesQuery: () => mockUseCategoriesQuery(),
}));
vi.mock("../../hooks/queries/useOwnersQuery", () => ({
  useOwnersQuery: () => mockUseOwnersQuery(),
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
    mockUseCategoriesQuery.mockReset();
    mockUseOwnersQuery.mockReset();
    mockUseCategoriesQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseOwnersQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseGraphTopologyQuery.mockReturnValue({ data: { nodes: [], links: [] }, isLoading: false });
    mockUseGraphOverviewQuery.mockReturnValue({ data: overviewSnapshot, isLoading: false });
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

  it("shows error state when overview fetch fails (PR6 will add fallback)", () => {
    mockUseGraphOverviewQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("network unreachable"),
    });
    render(<LODGraphCMDB />, { wrapper: createWrapper() });
    expect(screen.getByText(/LOD overview unavailable/i)).toBeInTheDocument();
  });

  it("forwards cluster click to the onClusterClick callback", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();
    render(<LODGraphCMDB onClusterClick={handleClick} />, { wrapper: createWrapper() });

    await user.click(screen.getByTestId("cluster-card-location:HQ-Madrid"));

    expect(handleClick).toHaveBeenCalledTimes(1);
    expect(handleClick).toHaveBeenCalledWith(
      "location:HQ-Madrid",
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
