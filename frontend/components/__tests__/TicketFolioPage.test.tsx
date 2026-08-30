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
  listServiceCatalog: vi.fn(),
  listActiveUsers: vi.fn(),
  downloadTicketTemplate: vi.fn(),
  importTicketWorkbook: vi.fn(),
}));

vi.mock("../../services/itsm", async () => {
  const actual = await vi.importActual<typeof import("../../services/itsm")>("../../services/itsm");
  return {
    ...actual,
    listTicketFolios: (...args: unknown[]) => mocks.listTicketFolios(...args),
    createTicketFolio: (...args: unknown[]) => mocks.createTicketFolio(...args),
    updateTicketFolio: (...args: unknown[]) => mocks.updateTicketFolio(...args),
    transitionTicketFolio: (...args: unknown[]) => mocks.transitionTicketFolio(...args),
    listServiceCatalog: (...args: unknown[]) => mocks.listServiceCatalog(...args),
    listActiveUsers: (...args: unknown[]) => mocks.listActiveUsers(...args),
    downloadTicketTemplate: (...args: unknown[]) => mocks.downloadTicketTemplate(...args),
    importTicketWorkbook: (...args: unknown[]) => mocks.importTicketWorkbook(...args),
  };
});

const sampleTickets = [
  {
    ticket_id: 1,
    type: "service_request" as const,
    title: "Access request",
    description: "Grant VPN access",
    service_catalog_id: "svc-auth",
    assignee_username: "alice",
    assignee_display_name: "alice",
    assignee_active_at_assignment: true,
    assignee_currently_active: true,
    status: "open" as const,
    archived: false,
    closed_reason: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: "admin",
  },
  {
    ticket_id: 2,
    type: "incident" as const,
    title: "API outage",
    description: null,
    service_catalog_id: null,
    assignee_username: "bob",
    assignee_display_name: "bob",
    assignee_active_at_assignment: true,
    assignee_currently_active: true,
    status: "in_validation" as const,
    archived: false,
    closed_reason: null,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    updated_by: "admin",
  },
];

const sampleCatalog = [
  {
    service_id: "svc-auth",
    name: "Auth API",
    owner_team: null,
    category: null,
    tier: null,
    criticality: null,
    sla_target_minutes: 60,
    description: "Auth service",
    service_type: "service_request" as const,
    value_stream: "deliver",
    active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: null,
  },
];

const activeUsers = [
  { username: "alice", disabled: false, is_active: true },
  { username: "bob", disabled: false, is_active: true },
];

describe("ItsmTicketFolioPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listServiceCatalog.mockResolvedValue(sampleCatalog);
    mocks.listActiveUsers.mockResolvedValue(activeUsers);
  });

  it("lists ticket folios and keeps UI independent from event endpoints", async () => {
    mocks.listTicketFolios.mockResolvedValueOnce(sampleTickets);

    render(<ItsmTicketFolioPage />);

    expect(
      await screen.findByRole("heading", { name: /service management/i, level: 1 }),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());
    expect(screen.getByText("API outage")).toBeInTheDocument();
    expect(mocks.listTicketFolios).toHaveBeenCalledWith({});
  });

  it("creates request and incident folios", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios
      .mockResolvedValueOnce(sampleTickets)
      .mockResolvedValueOnce([
        ...sampleTickets,
        { ...sampleTickets[0], ticket_id: 3, title: "New request" },
      ]);
    mocks.createTicketFolio.mockResolvedValueOnce({
      ...sampleTickets[0],
      ticket_id: 3,
      title: "New request",
    });

    render(<ItsmTicketFolioPage />);
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /new ticket/i }));
    await user.selectOptions(screen.getByLabelText(/^type$/i), "service_request");
    await user.type(screen.getByLabelText(/^title$/i), "New request");
    await user.selectOptions(screen.getByLabelText(/^service$/i), "svc-auth");
    await user.selectOptions(screen.getByLabelText(/^assignee$/i), "alice");
    await user.click(screen.getByRole("button", { name: /save ticket/i }));

    await waitFor(() => expect(mocks.createTicketFolio).toHaveBeenCalledTimes(1));
    expect(mocks.createTicketFolio).toHaveBeenCalledWith({
      type: "service_request",
      title: "New request",
      description: null,
      service_catalog_id: "svc-auth",
      assignee_username: "alice",
    });
  });

  it("updates an existing ticket folio", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios
      .mockResolvedValueOnce(sampleTickets)
      .mockResolvedValueOnce([
        { ...sampleTickets[0], title: "Access request updated" },
        sampleTickets[1],
      ]);
    mocks.updateTicketFolio.mockResolvedValueOnce({
      ...sampleTickets[0],
      title: "Access request updated",
    });

    render(<ItsmTicketFolioPage />);
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /^Edit 1$/i }));
    const titleInput = screen.getByLabelText(/^title$/i);
    await user.clear(titleInput);
    await user.type(titleInput, "Access request updated");
    await user.click(screen.getByRole("button", { name: /save ticket/i }));

    await waitFor(() =>
      expect(mocks.updateTicketFolio).toHaveBeenCalledWith(1, {
        title: "Access request updated",
        description: "Grant VPN access",
        service_catalog_id: "svc-auth",
      }),
    );
  });

  it("only exposes the next linear status transition", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios
      .mockResolvedValueOnce(sampleTickets)
      .mockResolvedValueOnce(sampleTickets);
    mocks.transitionTicketFolio.mockResolvedValueOnce({
      ...sampleTickets[0],
      status: "in_progress",
    });

    render(<ItsmTicketFolioPage />);
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: /move 1 to resolved/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /move 1 to in_progress/i }));

    await waitFor(() =>
      expect(mocks.transitionTicketFolio).toHaveBeenCalledWith(1, "in_progress", undefined),
    );
  });

  it("asks for a close reason when moving to closed", async () => {
    const user = userEvent.setup();
    const resolvedTicket = { ...sampleTickets[0], status: "resolved" as const };
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("Validated by requester");
    mocks.listTicketFolios
      .mockResolvedValueOnce([resolvedTicket])
      .mockResolvedValueOnce([{ ...resolvedTicket, status: "closed" as const }]);
    mocks.transitionTicketFolio.mockResolvedValueOnce({
      ...resolvedTicket,
      status: "closed",
      closed_reason: "Validated by requester",
    });

    render(<ItsmTicketFolioPage />);
    await waitFor(() => expect(screen.getByText("Access request")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /move 1 to closed/i }));

    await waitFor(() =>
      expect(mocks.transitionTicketFolio).toHaveBeenCalledWith(
        1,
        "closed",
        "Validated by requester",
      ),
    );
    promptSpy.mockRestore();
  });
});
