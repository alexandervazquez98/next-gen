/**
 * usePhysicalLinkMutations.test.tsx
 *
 * Slice 2/4 of feat-444 (closes #444): React Query mutation hook tests for
 * the PhysicalLink CRUD API. Mirrors the precedent set by
 * `useEventMutations.test.tsx` and `useProposalsQuery.test.tsx` — the
 * mutations are tested through the React Query layer with the underlying
 * service stubbed.
 *
 * Coverage map:
 *   - `useCreatePhysicalLink` POSTs to /cmdb/physical-links with the
 *     supplied payload and invalidates the `cmdb-physical-links` cache on
 *     success.
 *   - `useUpdatePhysicalLinkStatus` PATCHes /cmdb/physical-links/{id}/status
 *     with `{ status }` and invalidates BOTH the list cache and the detail
 *     cache (so the table re-renders AND the detail panel reflects the new
 *     status).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as service from "../../../services/physicalLinks";
import { useCreatePhysicalLink, useUpdatePhysicalLinkStatus } from "../usePhysicalLinkMutations";

vi.mock("../../../services/physicalLinks", () => ({
  createPhysicalLink: vi.fn(),
  updatePhysicalLinkStatus: vi.fn(),
}));

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function withClient(node: React.ReactNode, client: QueryClient) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("usePhysicalLinkMutations hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("useCreatePhysicalLink POSTs the payload and invalidates the cache", async () => {
    (service.createPhysicalLink as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "pl-new",
      type: "fiber",
      endpoints: ["ci-a", "ci-b"],
      status: "UP",
      capacity_gbps: 10,
      install_date: null,
    });

    const client = makeClient();
    client.setQueryData(
      ["cmdb-physical-links", {}],
      [
        {
          id: "pl-1",
          type: "fiber",
          endpoints: ["ci-a", "ci-b"],
          status: "UNKNOWN",
          capacity_gbps: null,
          install_date: null,
        },
      ],
    );

    function Probe() {
      const m = useCreatePhysicalLink();
      return (
        <button
          onClick={() =>
            m.mutate({
              id: "pl-new",
              type: "fiber",
              endpoints: ["ci-a", "ci-b"],
              status: "UP",
              capacity_gbps: 10,
              install_date: null,
            })
          }
        >
          create
        </button>
      );
    }
    withClient(<Probe />, client);
    fireEvent.click(screen.getByText("create"));

    await waitFor(() => {
      expect(service.createPhysicalLink).toHaveBeenCalled();
    });
    expect(service.createPhysicalLink).toHaveBeenCalledWith({
      id: "pl-new",
      type: "fiber",
      endpoints: ["ci-a", "ci-b"],
      status: "UP",
      capacity_gbps: 10,
      install_date: null,
    });

    // The list cache MUST be invalidated so the next read refetches.
    await waitFor(() => {
      const entry = client.getQueryCache().find({ queryKey: ["cmdb-physical-links", {}] });
      expect(entry?.state.isInvalidated).toBe(true);
    });
  });

  it("useUpdatePhysicalLinkStatus PATCHes the correct path with the new status", async () => {
    (service.updatePhysicalLinkStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "pl-1",
      type: "fiber",
      endpoints: ["ci-a", "ci-b"],
      status: "UP",
      capacity_gbps: 10,
      install_date: null,
    });

    const client = makeClient();
    client.setQueryData(["cmdb-physical-links", {}], []);
    client.setQueryData(["cmdb-physical-links", "detail", "pl-1"], {
      id: "pl-1",
      type: "fiber",
      endpoints: ["ci-a", "ci-b"],
      status: "DOWN",
      capacity_gbps: 10,
      install_date: null,
    });

    function Probe() {
      const m = useUpdatePhysicalLinkStatus();
      return <button onClick={() => m.mutate({ id: "pl-1", status: "UP" })}>update</button>;
    }
    withClient(<Probe />, client);
    fireEvent.click(screen.getByText("update"));

    await waitFor(() => {
      expect(service.updatePhysicalLinkStatus).toHaveBeenCalled();
    });
    expect(service.updatePhysicalLinkStatus).toHaveBeenCalledWith("pl-1", "UP");

    // The list cache and detail cache MUST both be invalidated.
    await waitFor(() => {
      const listEntry = client.getQueryCache().find({ queryKey: ["cmdb-physical-links", {}] });
      const detailEntry = client
        .getQueryCache()
        .find({ queryKey: ["cmdb-physical-links", "detail", "pl-1"] });
      expect(listEntry?.state.isInvalidated).toBe(true);
      expect(detailEntry?.state.isInvalidated).toBe(true);
    });
  });
});
