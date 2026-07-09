import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ItsmTicketFolioPage from "../ItsmTicketFolioPage";

const mocks = vi.hoisted(() => ({
  listTicketFolios: vi.fn(),
  createTicketFolio: vi.fn(),
  updateTicketFolio: vi.fn(),
  transitionTicketFolio: vi.fn(),
}));

vi.mock("../../services/itsm", () => ({
  listTicketFolios: (...args: unknown[]) => mocks.listTicketFolios(...args),
  createTicketFolio: (...args: unknown[]) => mocks.createTicketFolio(...args),
  updateTicketFolio: (...args: unknown[]) => mocks.updateTicketFolio(...args),
  transitionTicketFolio: (...args: unknown[]) => mocks.transitionTicketFolio(...args),
}));

const sampleTickets = [
  {
    ticket_id: "TK-001",
    type: "request",
    title: "Access request",
    description: "Grant VPN access",
    service_catalog_id: "svc-auth",
    status: "open",
    closed_reason: null,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    updated_by: "admin",
  },
  {
    ticket_id: "TK-002",
    type: "incident",
    title: "API outage",
    description: null,
    service_catalog_id: null,
    status: "in_validation",
    closed_reason: null,
    created_at: "2025-01-02T00:00:00Z",
    updated_at: "2025-01-02T00:00:00Z",
    updated_by: "admin",
  },
];

describe("ItsmTicketFolioPage", () => {
  beforeEach(() => {
    mocks.listTicketFolios.mockReset();
    mocks.createTicketFolio.mockReset();
    mocks.updateTicketFolio.mockReset();
    mocks.transitionTicketFolio.mockReset();
  });

  it("lists ticket folios and keeps UI independent from event endpoints", async () => {
    mocks.listTicketFolios.mockResolvedValueOnce(sampleTickets);

    render(<ItsmTicketFolioPage />);

    expect(screen.getByRole("heading", { name: /itsm tickets/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());
    expect(screen.getByText("API outage")).toBeInTheDocument();
    expect(mocks.listTicketFolios).toHaveBeenCalledWith({});
  });

  it("creates request and incident folios", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios
      .mockResolvedValueOnce(sampleTickets)
      .mockResolvedValueOnce([...sampleTickets, { ...sampleTickets[0], ticket_id: "TK-003", title: "New request" }]);
    mocks.createTicketFolio.mockResolvedValueOnce({ ...sampleTickets[0], ticket_id: "TK-003", title: "New request" });

    render(<ItsmTicketFolioPage />);
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /new ticket/i }));
    await user.type(screen.getByLabelText(/ticket id/i), "TK-003");
    await user.selectOptions(screen.getByLabelText(/type/i), "incident");
    await user.type(screen.getByLabelText(/title/i), "New request");
    await user.type(screen.getByLabelText(/description/i), "Created outside events");
    await user.type(screen.getByLabelText(/service catalog id/i), "svc-auth");
    await user.click(screen.getByRole("button", { name: /save ticket/i }));

    await waitFor(() => expect(mocks.createTicketFolio).toHaveBeenCalledTimes(1));
    expect(mocks.createTicketFolio).toHaveBeenCalledWith({
      ticket_id: "TK-003",
      type: "incident",
      title: "New request",
      description: "Created outside events",
      service_catalog_id: "svc-auth",
    });
  });

  it("updates an existing ticket folio", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios.mockResolvedValueOnce(sampleTickets).mockResolvedValueOnce([
      { ...sampleTickets[0], title: "Access request updated" },
      sampleTickets[1],
    ]);
    mocks.updateTicketFolio.mockResolvedValueOnce({ ...sampleTickets[0], title: "Access request updated" });

    render(<ItsmTicketFolioPage />);
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /edit TK-001/i }));
    const titleInput = screen.getByLabelText(/title/i);
    await user.clear(titleInput);
    await user.type(titleInput, "Access request updated");
    await user.click(screen.getByRole("button", { name: /save ticket/i }));

    await waitFor(() => expect(mocks.updateTicketFolio).toHaveBeenCalledWith("TK-001", {
      title: "Access request updated",
      description: "Grant VPN access",
      service_catalog_id: "svc-auth",
    }));
  });

  it("only exposes the next linear status transition", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios.mockResolvedValueOnce(sampleTickets).mockResolvedValueOnce(sampleTickets);
    mocks.transitionTicketFolio.mockResolvedValueOnce({ ...sampleTickets[0], status: "in_progress" });

    render(<ItsmTicketFolioPage />);
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /move TK-001 to resolved/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /move TK-001 to in_progress/i }));

    await waitFor(() => expect(mocks.transitionTicketFolio).toHaveBeenCalledWith("TK-001", "in_progress", undefined));
  });

  it("asks for a close reason when moving to closed", async () => {
    const user = userEvent.setup();
    const resolvedTicket = { ...sampleTickets[0], status: "resolved" };
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("Validated by requester");
    mocks.listTicketFolios.mockResolvedValueOnce([resolvedTicket]).mockResolvedValueOnce([{ ...resolvedTicket, status: "closed" }]);
    mocks.transitionTicketFolio.mockResolvedValueOnce({ ...resolvedTicket, status: "closed", closed_reason: "Validated by requester" });

    render(<ItsmTicketFolioPage />);
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /move TK-001 to closed/i }));

    await waitFor(() => expect(mocks.transitionTicketFolio).toHaveBeenCalledWith("TK-001", "closed", "Validated by requester"));
    promptSpy.mockRestore();
  });
});
