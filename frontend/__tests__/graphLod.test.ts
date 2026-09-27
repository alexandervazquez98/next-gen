// frontend/__tests__/graphLod.test.ts — #392 PR4
//
// Test the fetch helpers in ``frontend/services/graphLod.ts``.
// Asserts the URL composition + response narrowing.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchGraphDetail, fetchGraphOverview } from "../services/graphLod";

type FetchMock = ReturnType<typeof vi.fn>;

const mockFetch = (response: unknown, status = 200): FetchMock => {
  const fn = vi.fn(async () => {
    const headers = new Map<string, string>([["content-type", "application/json"]]);
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: (name: string) => headers.get(name.toLowerCase()) ?? null },
      json: async () => response,
      text: async () => JSON.stringify(response),
      blob: async () => new Blob([JSON.stringify(response)]),
    };
  });
  (globalThis as unknown as { fetch: FetchMock }).fetch = fn;
  return fn;
};

const validOverview = {
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
  ],
  inter_cluster_links: [],
  legend: { cards: [] },
  page: { next_cursor: null, has_more: false },
};

const validDetail = {
  cluster: {
    cluster_id: "location:HQ-Madrid",
    axis: "location",
    display_label: "HQ-Madrid",
    visible_node_count: 50,
    visible_link_count: 12,
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
  projection_flags: { show_sensitive_metadata: false, sensitive_source: "never" },
  empty_reason: "none",
  page: { next_cursor: null, has_more: false },
};

describe("fetchGraphOverview", () => {
  let fetchSpy: FetchMock;

  beforeEach(() => {
    fetchSpy = mockFetch(validOverview);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("hits /api/graph/overview with no filters", async () => {
    const resp = await fetchGraphOverview();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url] = fetchSpy.mock.calls[0];
    expect(url).toBe("/api/graph/overview");
    expect(resp.axis).toBe("location");
    expect(resp.clusters).toHaveLength(1);
  });

  it("forwards filters to the URL", async () => {
    await fetchGraphOverview({ ci_type: "Router", location: ["HQ-Madrid"] });
    const [url] = fetchSpy.mock.calls[0];
    expect(url).toContain("ci_type=Router");
    expect(url).toContain("location=HQ-Madrid");
  });

  it("rejects malformed response shape", async () => {
    mockFetch({ not_an_overview: true });
    await expect(fetchGraphOverview()).rejects.toThrow(/OverviewResponse shape/);
  });
});

describe("fetchGraphDetail", () => {
  let fetchSpy: FetchMock;

  beforeEach(() => {
    fetchSpy = mockFetch(validDetail);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("hits /api/graph/detail/{cluster_id}", async () => {
    const resp = await fetchGraphDetail("location:HQ-Madrid");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url] = fetchSpy.mock.calls[0];
    expect(url).toBe("/api/graph/detail/location%3AHQ-Madrid");
    expect(resp.cluster?.cluster_id).toBe("location:HQ-Madrid");
  });

  it("forwards cursor and limit filters", async () => {
    await fetchGraphDetail("location:HQ-Madrid", { cursor: "abc123", limit: 50 });
    const [url] = fetchSpy.mock.calls[0];
    expect(url).toContain("cursor=abc123");
    expect(url).toContain("limit=50");
  });

  it("validates cluster_id at build time (no network call)", async () => {
    await expect(fetchGraphDetail("invalid-format")).rejects.toThrow();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects malformed response shape", async () => {
    mockFetch({ not_a_detail: true });
    await expect(fetchGraphDetail("location:HQ-Madrid")).rejects.toThrow(/DetailResponse shape/);
  });
});
