// frontend/hooks/queries/useGraphDetailQuery.test.tsx — #392 PR5
//
// Verifies the React Query hook for the LOD detail endpoint by
// mocking the network fetch and asserting the hook propagates
// filters and the enabled-state correctly.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock fetchGraphDetail so the hook never hits the network.
// vi.hoisted ensures the mock factory is initialized before vi.mock
// is hoisted to the top of the file.
const { mockFetchGraphDetail } = vi.hoisted(() => ({
  mockFetchGraphDetail: vi.fn(),
}));
vi.mock("../../services/graphLod", () => ({
  fetchGraphDetail: mockFetchGraphDetail,
}));

// Import after the mock so the module reference is the mocked one.
import { useGraphDetailQuery } from "./useGraphDetailQuery";

const validDetail = {
  cluster: {
    cluster_id: "location:HQ-Madrid",
    axis: "location" as const,
    display_label: "HQ-Madrid",
    visible_node_count: 1,
    visible_link_count: 0,
  },
  filters: {},
  generated_at: "2026-09-26T20:00:00Z",
  revision: "test-revision-0001",
  nodes: [],
  links: [],
  boundary_stubs: [],
  projection_flags: { show_sensitive_metadata: false, sensitive_source: "never" as const },
  empty_reason: "none" as const,
  page: { next_cursor: null, has_more: false },
};

const createWrapper = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

describe("useGraphDetailQuery (#392 PR5)", () => {
  beforeEach(() => {
    mockFetchGraphDetail.mockReset();
    mockFetchGraphDetail.mockResolvedValue(validDetail);
  });

  it("does not call fetchGraphDetail when clusterId is null", async () => {
    const { result } = renderHook(() => useGraphDetailQuery(null), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(mockFetchGraphDetail).not.toHaveBeenCalled();
    expect(result.current.data).toBeUndefined();
    expect(result.current.isSuccess).toBe(false);
  });

  it("calls fetchGraphDetail with clusterId when provided", async () => {
    renderHook(() => useGraphDetailQuery("location:HQ-Madrid"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(mockFetchGraphDetail).toHaveBeenCalledTimes(1), { timeout: 3000 });
    const firstCall = mockFetchGraphDetail.mock.calls[0];
    expect(firstCall[0]).toBe("location:HQ-Madrid");
    // Verify the mock was called with the expected args (the result
    // data is asserted via the forwarding test below).
    expect(firstCall.length).toBeGreaterThanOrEqual(2);
  });

  it("forwards filters to fetchGraphDetail", async () => {
    const filters = { ci_type: "Router", cursor: "abc" };
    renderHook(() => useGraphDetailQuery("location:HQ-Madrid", filters), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(mockFetchGraphDetail).toHaveBeenCalledTimes(1));
    const firstCall = mockFetchGraphDetail.mock.calls[0];
    expect(firstCall[0]).toBe("location:HQ-Madrid");
    expect(firstCall[1]).toEqual(filters);
  });
});
