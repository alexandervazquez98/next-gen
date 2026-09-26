import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProposalActions } from "../ProposalActions";

vi.mock("../../../../hooks/queries/useProposalsQuery", () => ({
  useApproveProposal: () => ({ mutate: vi.fn(), isLoading: false }),
  useRevokeProposal: () => ({ mutate: vi.fn(), isLoading: false }),
}));

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ProposalActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("hides the buttons when the user lacks CI_APPROVE_PROPOSAL", () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <ProposalActions proposalId="prop-1" version={1} ciId="CI-NEW" canApprove={false} />
      </QueryClientProvider>,
    );

    expect(screen.queryByTestId("proposal-action-approve")).not.toBeInTheDocument();
    expect(screen.queryByTestId("proposal-action-revoke")).not.toBeInTheDocument();
    expect(screen.getByTestId("proposal-actions-no-permission")).toBeInTheDocument();
  });

  it("shows the approve + revoke buttons when the user has CI_APPROVE_PROPOSAL", () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <ProposalActions proposalId="prop-1" version={1} ciId="CI-NEW" canApprove />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("proposal-action-approve")).toBeInTheDocument();
    expect(screen.getByTestId("proposal-action-revoke")).toBeInTheDocument();
  });

  it("hides the approve button when status is REVOKED", () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <ProposalActions proposalId="prop-1" version={1} ciId="CI-NEW" canApprove isRevoked />
      </QueryClientProvider>,
    );

    expect(screen.queryByTestId("proposal-action-approve")).not.toBeInTheDocument();
    expect(screen.getByTestId("proposal-actions-revoked")).toBeInTheDocument();
  });

  it("hides the approve button when status is APPROVED", () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <ProposalActions proposalId="prop-1" version={1} ciId="CI-NEW" canApprove isApproved />
      </QueryClientProvider>,
    );

    expect(screen.queryByTestId("proposal-action-approve")).not.toBeInTheDocument();
    expect(screen.getByTestId("proposal-action-revoke")).toBeInTheDocument();
  });
});
