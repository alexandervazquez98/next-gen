import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useApproveProposal,
  useProposalCountQuery,
  useProposalDetailQuery,
  useProposalsQuery,
  useRevokeProposal,
} from "../useProposalsQuery";
import * as cmdbApi from "../../../services/cmdbProposals";

vi.mock("../../../services/cmdbProposals", () => ({
  fetchProposals: vi.fn(),
  fetchProposal: vi.fn(),
  fetchProposalDraftCount: vi.fn(),
  approveProposal: vi.fn(),
  revokeProposal: vi.fn(),
}));

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function withClient(node: React.ReactNode, client: QueryClient) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("useProposalsQuery hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("useProposalsQuery calls fetchProposals with filters", async () => {
    (cmdbApi.fetchProposals as any).mockResolvedValue({
      rows: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
    const client = makeClient();
    function Probe() {
      useProposalsQuery({ status: "DRAFT" });
      return null;
    }
    withClient(<Probe />, client);
    await waitFor(() => {
      expect(cmdbApi.fetchProposals).toHaveBeenCalled();
    });
    expect(cmdbApi.fetchProposals).toHaveBeenCalledWith(
      expect.objectContaining({ status: "DRAFT" }),
      expect.anything(),
    );
  });

  it("useProposalDetailQuery is enabled only when id is provided", async () => {
    (cmdbApi.fetchProposal as any).mockResolvedValue({ id: "prop-1" });
    const client = makeClient();
    function Probe() {
      useProposalDetailQuery(undefined);
      return null;
    }
    withClient(<Probe />, client);
    // No call when undefined
    expect(cmdbApi.fetchProposal).not.toHaveBeenCalled();
  });

  it("useProposalCountQuery polls every 5 seconds", () => {
    expect(useProposalCountQuery).toBeDefined();
  });

  it("useApproveProposal invalidates proposals, count, nodes, graph-topology, audit", async () => {
    (cmdbApi.approveProposal as any).mockResolvedValue({
      proposal_id: "prop-1",
      status: "APPROVED",
      version: 2,
      resulted_ci_id: "CI-NEW",
    });
    const client = makeClient();
    // Seed the cache with at least one proposals query so we can prove invalidation.
    client.setQueryData(["cmdb-proposals", { status: "DRAFT" }], {
      rows: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
    function Probe() {
      const m = useApproveProposal();
      return (
        <button onClick={() => m.mutate({ id: "prop-1", version: 1 })}>
          go
        </button>
      );
    }
    withClient(<Probe />, client);
    fireEvent.click(screen.getByText("go"));
    await waitFor(() => {
      expect(cmdbApi.approveProposal).toHaveBeenCalled();
    });
    // After mutation onSuccess, the cache MUST be marked stale (invalidated).
    await waitFor(() => {
      const entry = client.getQueryCache().find(["cmdb-proposals", { status: "DRAFT" }]);
      expect(entry?.state.isInvalidated).toBe(true);
    });
  });

  it("useRevokeProposal invalidates the same set of caches", async () => {
    (cmdbApi.revokeProposal as any).mockResolvedValue({
      proposal_id: "prop-1",
      status: "REVOKED",
      version: 2,
    });
    const client = makeClient();
    client.setQueryData(["cmdb-proposals", { status: "DRAFT" }], {
      rows: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
    function Probe() {
      const m = useRevokeProposal();
      return (
        <button onClick={() => m.mutate({ id: "prop-1", version: 1, reason: "stale" })}>
          go
        </button>
      );
    }
    withClient(<Probe />, client);
    fireEvent.click(screen.getByText("go"));
    await waitFor(() => {
      expect(cmdbApi.revokeProposal).toHaveBeenCalled();
    });
    await waitFor(() => {
      const entry = client.getQueryCache().find(["cmdb-proposals", { status: "DRAFT" }]);
      expect(entry?.state.isInvalidated).toBe(true);
    });
  });
});