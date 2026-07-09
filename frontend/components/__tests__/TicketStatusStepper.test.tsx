import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TicketStatusStepper from "../TicketStatusStepper";

describe("TicketStatusStepper", () => {
  it("shows only the next linear transition", () => {
    render(<TicketStatusStepper ticketId="TK-001" status="in_progress" onTransition={vi.fn()} />);

    expect(screen.getByRole("button", { name: /move TK-001 to in_validation/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /move TK-001 to resolved/i })).not.toBeInTheDocument();
  });

  it("makes closed tickets read-only", () => {
    render(<TicketStatusStepper ticketId="TK-002" status="closed" onTransition={vi.fn()} />);

    expect(screen.getByText(/closed/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /move/i })).not.toBeInTheDocument();
  });
});
