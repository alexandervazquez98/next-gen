import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ItsmTicketFolioPage from "../ItsmTicketFolioPage";

// All service endpoints the page uses are mocked below.
const mocks = vi.hoisted(() => ({
  listTicketFolios: vi.fn(),
  createTicketFolio: vi.fn(),
  updateTicketFolio: vi.fn(),
  transitionTicketFolio: vi.fn(),
  listServiceCatalog: vi.fn(),
  listActiveUsers: vi.fn(),
  downloadTicketTemplate: vi.fn(),
  importTicketWorkbook: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock("../../services/itsm", () => ({
  listTicketFolios: (...args: unknown[]) => mocks.listTicketFolios(...args),
  createTicketFolio: (...args: unknown[]) => mocks.createTicketFolio(...args),
  updateTicketFolio: (...args: unknown[]) => mocks.updateTicketFolio(...args),
  transitionTicketFolio: (...args: unknown[]) => mocks.transitionTicketFolio(...args),
  listServiceCatalog: (...args: unknown[]) => mocks.listServiceCatalog(...args),
  listActiveUsers: (...args: unknown[]) => mocks.listActiveUsers(...args),
  downloadTicketTemplate: (...args: unknown[]) => mocks.downloadTicketTemplate(...args),
  importTicketWorkbook: (...args: unknown[]) => mocks.importTicketWorkbook(...args),
}));

const sampleTickets = [
  {
    ticket_id: 1,
    type: "incident",
    title: "Router down",
    description: "Core router unreachable",
    service_catalog_id: "svc-net-inc",
    assignee_username: "alice",
    assignee_display_name: "alice",
    assignee_active_at_assignment: true,
    assignee_currently_active: true,
    status: "open",
    archived: false,
    closed_reason: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: "admin",
  },
];

const sampleCatalog = [
  {
    service_id: "svc-net-inc",
    name: "Net Incident",
    owner_team: null,
    category: null,
    tier: null,
    criticality: null,
    sla_target_minutes: 60,
    description: "Network incident handling",
    service_type: "incident",
    value_stream: "operate",
    active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: null,
  },
  {
    service_id: "svc-vpn-req",
    name: "VPN Access",
    owner_team: null,
    category: null,
    tier: null,
    criticality: null,
    sla_target_minutes: 30,
    description: "VPN access requests",
    service_type: "service_request",
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

describe("ItsmTicketFolioPage — WU 8 contract-aligned form", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listServiceCatalog.mockResolvedValue(sampleCatalog);
    mocks.listActiveUsers.mockResolvedValue(activeUsers);
  });

  it("renames the heading to Service Management and shows only canonical ticket types", async () => {
    mocks.listTicketFolios.mockResolvedValueOnce(sampleTickets);
    render(<ItsmTicketFolioPage />);

    expect(
      await screen.findByRole("heading", { name: /service management/i, level: 1 }),
    ).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: /new ticket/i }));

    const typeSelect = screen.getByLabelText(/^type$/i) as HTMLSelectElement;
    expect(Array.from(typeSelect.options).map((opt) => opt.value)).toEqual([
      "incident",
      "service_request",
    ]);
  });

  it("does NOT expose a client-supplied ticket_id input on create", async () => {
    mocks.listTicketFolios.mockResolvedValueOnce(sampleTickets);
    render(<ItsmTicketFolioPage />);

    await screen.findByRole("heading", { name: /service management/i, level: 1 });
    await userEvent.setup().click(screen.getByRole("button", { name: /new ticket/i }));

    expect(screen.queryByLabelText(/^ticket id$/i)).not.toBeInTheDocument();
  });

  it("shows the server-generated numeric ticket_id after create", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        { ...sampleTickets[0], ticket_id: 4242, title: "Generated" },
      ]);
    mocks.createTicketFolio.mockResolvedValueOnce({
      ...sampleTickets[0],
      ticket_id: 4242,
      title: "Generated",
    });

    render(<ItsmTicketFolioPage />);
    await screen.findByRole("heading", { name: /service management/i, level: 1 });

    await user.click(screen.getByRole("button", { name: /new ticket/i }));
    await user.selectOptions(screen.getByLabelText(/^type$/i), "incident");
    await user.type(screen.getByLabelText(/^title$/i), "Generated");
    await user.selectOptions(screen.getByLabelText(/^service$/i), "svc-net-inc");
    await user.selectOptions(screen.getByLabelText(/^assignee$/i), "alice");
    await user.click(screen.getByRole("button", { name: /save ticket/i }));

    await waitFor(() => expect(mocks.createTicketFolio).toHaveBeenCalledTimes(1));
    const payload = mocks.createTicketFolio.mock.calls[0][0];
    expect(payload).toEqual({
      type: "incident",
      title: "Generated",
      description: null,
      service_catalog_id: "svc-net-inc",
      assignee_username: "alice",
    });
    expect(Object.keys(payload)).not.toContain("ticket_id");
    await waitFor(() => expect(screen.getByText("4242")).toBeInTheDocument());
  });

  it("filters service options by the selected ticket type", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios.mockResolvedValueOnce([]);

    render(<ItsmTicketFolioPage />);
    await screen.findByRole("heading", { name: /service management/i, level: 1 });

    await user.click(screen.getByRole("button", { name: /new ticket/i }));

    // Default type is incident — service_request must be filtered out.
    const serviceSelect = screen.getByLabelText(/^service$/i) as HTMLSelectElement;
    let values = Array.from(serviceSelect.options)
      .map((opt) => opt.value)
      .filter(Boolean);
    expect(values).toContain("svc-net-inc");
    expect(values).not.toContain("svc-vpn-req");

    await user.selectOptions(screen.getByLabelText(/^type$/i), "service_request");
    values = Array.from(serviceSelect.options)
      .map((opt) => opt.value)
      .filter(Boolean);
    expect(values).toContain("svc-vpn-req");
    expect(values).not.toContain("svc-net-inc");
  });

  it("requires an assignee and rejects submit when missing", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios.mockResolvedValueOnce([]);
    render(<ItsmTicketFolioPage />);
    await screen.findByRole("heading", { name: /service management/i, level: 1 });

    await user.click(screen.getByRole("button", { name: /new ticket/i }));
    await user.type(screen.getByLabelText(/^title$/i), "No assignee");
    await user.selectOptions(screen.getByLabelText(/^service$/i), "svc-net-inc");

    const assigneeSelect = screen.getByLabelText(/^assignee$/i) as HTMLSelectElement;
    expect(assigneeSelect.required).toBe(true);

    // Force a blank value: no option selected.
    await user.selectOptions(assigneeSelect, "");
    await user.click(screen.getByRole("button", { name: /save ticket/i }));

    expect(mocks.createTicketFolio).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/assignee is required/i),
    ).toBeInTheDocument();
  });

  it("surfaces the inactive-user backend error when assignee is rejected at write time", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios.mockResolvedValueOnce([]);
    mocks.createTicketFolio.mockRejectedValueOnce(
      Object.assign(new Error("user_inactive_at_write"), { status: 400 }),
    );

    render(<ItsmTicketFolioPage />);
    await screen.findByRole("heading", { name: /service management/i, level: 1 });

    await user.click(screen.getByRole("button", { name: /new ticket/i }));
    await user.type(screen.getByLabelText(/^title$/i), "Trigger inactive error");
    await user.selectOptions(screen.getByLabelText(/^service$/i), "svc-net-inc");
    await user.selectOptions(screen.getByLabelText(/^assignee$/i), "alice");
    await user.click(screen.getByRole("button", { name: /save ticket/i }));

    expect(
      await screen.findByText(/user_inactive_at_write|inactive/i),
    ).toBeInTheDocument();
  });

  it("surfaces the compatibility error when backend rejects the selected service", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios.mockResolvedValueOnce([]);
    mocks.createTicketFolio.mockRejectedValueOnce(
      Object.assign(new Error("service_type_mismatch_at_write"), { status: 400 }),
    );

    render(<ItsmTicketFolioPage />);
    await screen.findByRole("heading", { name: /service management/i, level: 1 });

    await user.click(screen.getByRole("button", { name: /new ticket/i }));
    await user.selectOptions(screen.getByLabelText(/^type$/i), "incident");
    await user.type(screen.getByLabelText(/^title$/i), "Trigger compatibility error");
    await user.selectOptions(screen.getByLabelText(/^service$/i), "svc-net-inc");
    await user.selectOptions(screen.getByLabelText(/^assignee$/i), "alice");
    await user.click(screen.getByRole("button", { name: /save ticket/i }));

    expect(
      await screen.findByText(/service_type_mismatch|compatibility|incompatible/i),
    ).toBeInTheDocument();
  });

  it("downloads the ticket import template when the button is clicked", async () => {
    mocks.listTicketFolios.mockResolvedValueOnce([]);
    mocks.downloadTicketTemplate.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();

    render(<ItsmTicketFolioPage />);
    await screen.findByRole("heading", { name: /service management/i, level: 1 });

    await user.click(screen.getByRole("button", { name: /download import template/i }));
    expect(mocks.downloadTicketTemplate).toHaveBeenCalledTimes(1);
  });

  it("uploads the selected workbook and surfaces structured import errors", async () => {
    const user = userEvent.setup();
    mocks.listTicketFolios.mockResolvedValueOnce([]);
    mocks.importTicketWorkbook.mockRejectedValueOnce(
      Object.assign(new Error("Validation failed"), {
        status: 400,
        detail: {
          status: "validation_failed",
          message: "Workbook validation failed; no records were imported.",
          errors: [
            { row: 3, field: "service_catalog_id", code: "incompatible_type", reason: "bad" },
          ],
          error_count: 1,
        },
      }),
    );

    render(<ItsmTicketFolioPage />);
    await screen.findByRole("heading", { name: /service management/i, level: 1 });

    const fileInput = screen.getByLabelText(/^import workbook$/i) as HTMLInputElement;
    const file = new File(["fake"], "tickets.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await user.upload(fileInput, file);

    await waitFor(() => expect(mocks.importTicketWorkbook).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(/Workbook validation failed; no records were imported/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Row 3 — service_catalog_id/)).toBeInTheDocument();
  });
});