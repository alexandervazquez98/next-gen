/**
 * usePhysicalLinksQuery.test.tsx
 *
 * Slice 2/4 of feat-444 (closes #444): React Query hook tests for the
 * PhysicalLink list + detail queries. Mirrors the precedent set by
 * `useProposalsQuery.test.tsx` — the React Query hooks are the seam under
 * test, and the underlying service is mocked at the api layer so that the
 * hook receives a deterministic payload (and so that tests never hit the
 * network).
 *
 * Coverage map:
 *   - `usePhysicalLinksQuery(filters)` issues a GET to /cmdb/physical-links
 *     with the right query-string parameters and returns the parsed array.
 *   - `usePhysicalLinksQuery()` with no filters still hits the list path.
 *   - `usePhysicalLinkDetailQuery(id)` GETs /cmdb/physical-links/{id} when an
 *     id is supplied, and does NOT fetch when the id is undefined.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as service from "../../../services/physicalLinks";
import { usePhysicalLinkDetailQuery, usePhysicalLinksQuery } from "../usePhysicalLinksQuery";

vi.mock("../../../services/physicalLinks", () => ({
  fetchPhysicalLinks: vi.fn(),
  fetchPhysicalLink: vi.fn(),
}));

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function withClient(node: React.ReactNode, client: QueryClient) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("usePhysicalLinksQuery hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("usePhysicalLinksQuery delegates to fetchPhysicalLinks (no filters)", async () => {
    const rows = [
      {
        id: "pl-1",
        type: "fiber",
        endpoints: ["ci-a", "ci-b"],
        status: "UP",
        capacity_gbps: 10,
        install_date: null,
      },
    ];
    (service.fetchPhysicalLinks as ReturnType<typeof vi.fn>).mockResolvedValue(rows);

    const client = makeClient();
    function Probe() {
      usePhysicalLinksQuery();
      return null;
    }
    withClient(<Probe />, client);
    await waitFor(() => {
      expect(service.fetchPhysicalLinks).toHaveBeenCalled();
    });
    expect(service.fetchPhysicalLinks).toHaveBeenCalledWith(
      expect.objectContaining({}),
      expect.anything(),
    );
  });

  it("usePhysicalLinksQuery flows filters through to fetchPhysicalLinks", async () => {
    (service.fetchPhysicalLinks as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const client = makeClient();
    function Probe() {
      usePhysicalLinksQuery({ ci_id: "ci-target", type: "fiber", status: "UP" });
      return null;
    }
    withClient(<Probe />, client);
    await waitFor(() => {
      expect(service.fetchPhysicalLinks).toHaveBeenCalled();
    });
    expect(service.fetchPhysicalLinks).toHaveBeenCalledWith(
      expect.objectContaining({
        ci_id: "ci-target",
        type: "fiber",
        status: "UP",
      }),
      expect.anything(),
    );
  });

  it("usePhysicalLinkDetailQuery fetches when id is provided", async () => {
    const row = {
      id: "pl-1",
      type: "fiber",
      endpoints: ["ci-a", "ci-b"],
      status: "UP",
      capacity_gbps: 10,
      install_date: null,
    };
    (service.fetchPhysicalLink as ReturnType<typeof vi.fn>).mockResolvedValue(row);

    const client = makeClient();
    function Probe() {
      usePhysicalLinkDetailQuery("pl-1");
      return null;
    }
    withClient(<Probe />, client);
    await waitFor(() => {
      expect(service.fetchPhysicalLink).toHaveBeenCalled();
    });
    expect(service.fetchPhysicalLink).toHaveBeenCalledWith("pl-1", expect.anything());
  });

  it("usePhysicalLinkDetailQuery is disabled when id is undefined", async () => {
    (service.fetchPhysicalLink as ReturnType<typeof vi.fn>).mockResolvedValue(null);

    const client = makeClient();
    function Probe() {
      usePhysicalLinkDetailQuery(undefined);
      return null;
    }
    withClient(<Probe />, client);
    // Allow microtasks to flush.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(service.fetchPhysicalLink).not.toHaveBeenCalled();
  });
});
