import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProposalList } from "../ProposalList";

vi.mock("../../../services/cmdbProposals", () => ({
  fetchProposals: vi.fn(),
}));

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ProposalList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders rows for each proposal", async () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <ProposalList
          rows={[
            {
              id: "prop-1",
              status: "DRAFT",
              version: 1,
              manifest_json: "{}",
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
          ]}
          loading={false}
          error={null}
          filters={{ status: "", category: "", proposed_by: "" }}
          onFiltersChange={() => undefined}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("proposal-row-prop-1")).toBeInTheDocument();
    expect(screen.getByText("prop-1")).toBeInTheDocument();
    expect(screen.getByText("ai-bot")).toBeInTheDocument();
    expect(screen.getByTestId("proposal-row-prop-1")).toHaveTextContent("DRAFT");
  });

  it("renders the empty state when zero rows", () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <ProposalList
          rows={[]}
          loading={false}
          error={null}
          filters={{ status: "DRAFT", category: "", proposed_by: "" }}
          onFiltersChange={() => undefined}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("proposal-list-empty")).toBeInTheDocument();
  });

  it("renders the loading skeleton while fetching", () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <ProposalList
          rows={[]}
          loading
          error={null}
          filters={{ status: "", category: "", proposed_by: "" }}
          onFiltersChange={() => undefined}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("proposal-list-skeleton")).toBeInTheDocument();
  });

  it("renders a 5xx-style error banner with the error message", () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <ProposalList
          rows={[]}
          loading={false}
          error={new Error("HTTP 503 — Neo4j unavailable")}
          filters={{ status: "", category: "", proposed_by: "" }}
          onFiltersChange={() => undefined}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("proposal-list-error")).toBeInTheDocument();
    expect(screen.getByText(/HTTP 503/)).toBeInTheDocument();
  });

  it("filter changes forward to onFiltersChange", async () => {
    const client = makeClient();
    const onFiltersChange = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <ProposalList
          rows={[
            {
              id: "prop-1",
              status: "DRAFT",
              version: 1,
              manifest_json: "{}",
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
          ]}
          loading={false}
          error={null}
          filters={{ status: "", category: "", proposed_by: "" }}
          onFiltersChange={onFiltersChange}
        />
      </QueryClientProvider>,
    );

    // Use the aria-label wired to the select to drive a React change event.
    const select = screen.getByLabelText("Filter by status") as HTMLSelectElement;
    select.value = "APPROVED";
    select.dispatchEvent(new Event("input", { bubbles: true }));
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await waitFor(() => expect(onFiltersChange).toHaveBeenCalled());
  });
});