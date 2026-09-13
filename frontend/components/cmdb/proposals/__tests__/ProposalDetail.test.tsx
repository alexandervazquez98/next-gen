import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProposalDetail } from "../ProposalDetail";

vi.mock("../../../../hooks/queries/useProposalsQuery", () => ({
  useProposalDetailQuery: vi.fn(),
  useApproveProposal: () => ({ mutate: vi.fn(), isLoading: false }),
  useRevokeProposal: () => ({ mutate: vi.fn(), isLoading: false }),
}));

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ProposalDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the manifest view, diff view, and audit timeline", async () => {
    const useProposalDetailQuery = (await import("../../../../hooks/queries/useProposalsQuery"))
      .useProposalDetailQuery;
    vi.mocked(useProposalDetailQuery).mockReturnValue({
      data: {
        id: "prop-1",
        status: "DRAFT",
        version: 1,
        manifest_json: JSON.stringify({
          ci: { id: "CI-NEW", label: "Core Router", category: "Router" },
        }),
        applied_manifest_json: null,
        proposed_by: "ai-bot",
        proposed_role: "AI_OPERATOR",
        reviewed_by: null,
        reviewed_at: null,
        created_at: "2026-09-13T00:00:00Z",
        updated_at: "2026-09-13T00:00:00Z",
        resulted_ci_id: null,
        revoke_reason: null,
        proposed_category: "Router",
        ci_id: "CI-NEW",
      },
      isLoading: false,
      error: null,
    } as any);

    const client = makeClient();
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <ProposalDetail
            proposalId="prop-1"
            canApprove
            canViewAudit
            auditEntries={[
              {
                event_type: "CI_PROPOSAL_CREATE",
                actor_username: "ai-bot",
                actor_role: "AI_OPERATOR",
                previous_state: null,
                next_state: "DRAFT",
                version: 1,
                created_at: "2026-09-13T00:00:00Z",
              },
            ]}
            auditLoading={false}
          />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("proposal-detail")).toBeInTheDocument();
    });
    expect(screen.getByTestId("proposal-diff-view")).toBeInTheDocument();
    expect(screen.getByTestId("proposal-audit-timeline")).toBeInTheDocument();
  });

  it("renders an error state when the query fails", async () => {
    const useProposalDetailQuery = (await import("../../../../hooks/queries/useProposalsQuery"))
      .useProposalDetailQuery;
    vi.mocked(useProposalDetailQuery).mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error("HTTP 404"),
    } as any);

    const client = makeClient();
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <ProposalDetail
            proposalId="missing"
            canApprove
            canViewAudit={false}
            auditEntries={[]}
            auditLoading={false}
          />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("proposal-detail-error")).toBeInTheDocument();
  });
});
