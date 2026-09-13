import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { ProposalBadge } from "../ProposalBadge";

// We override the mock per-test using vi.mocked(...) because vi.doMock is
// not honored after the test module has already imported the mocked module.

vi.mock("../../../../hooks/queries/useProposalsQuery", () => ({
  useProposalCountQuery: () => ({ data: { count: 3 } }),
}));

function renderWithProviders(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProposalBadge", () => {
  it("hides the badge when the user cannot review proposals", () => {
    renderWithProviders(<ProposalBadge canReview={false} />);
    expect(screen.queryByTestId("proposal-badge")).not.toBeInTheDocument();
  });

  it("renders the badge when the count > 0 and the user can review", () => {
    renderWithProviders(<ProposalBadge canReview />);
    expect(screen.getByTestId("proposal-badge")).toBeInTheDocument();
    expect(screen.getByText("3 pending")).toBeInTheDocument();
  });
});