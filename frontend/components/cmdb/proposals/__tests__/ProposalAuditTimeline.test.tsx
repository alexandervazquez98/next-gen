import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProposalAuditTimeline, AuditTimelineEntry } from "../ProposalAuditTimeline";

const ENTRIES: AuditTimelineEntry[] = [
  {
    event_type: "CI_PROPOSAL_CREATE",
    actor_username: "ai-bot",
    actor_role: "AI_OPERATOR",
    previous_state: null,
    next_state: "DRAFT",
    version: 1,
    created_at: "2026-09-13T10:00:00Z",
  },
  {
    event_type: "CI_PROPOSAL_APPROVE",
    actor_username: "alice",
    actor_role: "OPERATOR",
    previous_state: "DRAFT",
    next_state: "APPROVED",
    version: 2,
    created_at: "2026-09-13T11:00:00Z",
  },
  {
    event_type: "CI_PROPOSAL_REVOKE",
    actor_username: "SYSTEM",
    actor_role: "SYSTEM",
    previous_state: "APPROVED",
    next_state: "REVOKED",
    version: 3,
    created_at: "2026-09-13T12:00:00Z",
    reason: "ttl_expired",
  },
];

describe("ProposalAuditTimeline", () => {
  it("renders create, approve, revoke rows chronologically", () => {
    render(<ProposalAuditTimeline entries={ENTRIES} loading={false} />);
    const timeline = screen.getByTestId("proposal-audit-timeline");
    expect(timeline).toHaveTextContent("CI_PROPOSAL_CREATE");
    expect(timeline).toHaveTextContent("CI_PROPOSAL_APPROVE");
    expect(timeline).toHaveTextContent("CI_PROPOSAL_REVOKE");
    expect(timeline).toHaveTextContent("ttl_expired");
  });

  it("renders the loading skeleton when fetching", () => {
    render(<ProposalAuditTimeline entries={[]} loading />);
    expect(screen.getByTestId("proposal-audit-loading")).toBeInTheDocument();
  });
});