import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ItsmServiceCatalogPage from "../ItsmServiceCatalogPage";

const mocks = vi.hoisted(() => ({
  listServiceCatalog: vi.fn(),
  createServiceCatalog: vi.fn(),
  updateServiceCatalog: vi.fn(),
  deactivateServiceCatalog: vi.fn(),
  downloadCatalogTemplate: vi.fn(),
  importCatalogWorkbook: vi.fn(),
}));

vi.mock("../../services/itsm", async () => {
  const actual = await vi.importActual<typeof import("../../services/itsm")>(
    "../../services/itsm",
  );
  return {
    ...actual,
    listServiceCatalog: (...args: unknown[]) => mocks.listServiceCatalog(...args),
    createServiceCatalog: (...args: unknown[]) => mocks.createServiceCatalog(...args),
    updateServiceCatalog: (...args: unknown[]) => mocks.updateServiceCatalog(...args),
    deactivateServiceCatalog: (...args: unknown[]) => mocks.deactivateServiceCatalog(...args),
    downloadCatalogTemplate: (...args: unknown[]) => mocks.downloadCatalogTemplate(...args),
    importCatalogWorkbook: (...args: unknown[]) => mocks.importCatalogWorkbook(...args),
  };
});

type ServiceCatalogFixture = {
  service_id: string;
  name: string;
  owner_team: string | null;
  category: string | null;
  tier: string | null;
  criticality: string | null;
  sla_target_minutes: number;
  description: string;
  service_type: "incident" | "service_request";
  value_stream: string;
  active: boolean;
  created_at: string;
  updated_at: string;
  updated_by: string | null;
};

const sampleCatalogs: ServiceCatalogFixture[] = [
  {
    service_id: "svc-auth",
    name: "Auth API",
    owner_team: "Platform",
    category: "SaaS",
    tier: "gold",
    criticality: "high",
    sla_target_minutes: 15,
    description: "Auth service",
    service_type: "service_request",
    value_stream: "deliver",
    active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: null,
  },
  {
    service_id: "svc-billing",
    name: "Billing API",
    owner_team: "Finance",
    category: "B2B",
    tier: "silver",
    criticality: "medium",
    sla_target_minutes: 45,
    description: "Billing service",
    service_type: "incident",
    value_stream: "operate",
    active: true,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    updated_by: null,
  },
];

const renderCatalogRoute = () =>
  render(
    <MemoryRouter initialEntries={["/itsm/service-catalog"]}>
      <Routes>
        <Route path="/itsm/service-catalog" element={<ItsmServiceCatalogPage />} />
      </Routes>
    </MemoryRouter>,
  );

describe("ItsmServiceCatalogPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("reads and renders /itsm/service-catalog route with list data", async () => {
    mocks.listServiceCatalog.mockResolvedValueOnce(sampleCatalogs);

    renderCatalogRoute();

    expect(
      await screen.findByRole("heading", { name: /service catalog/i, level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new service catalog/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });
    expect(screen.getByText("Billing API")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Edit ${"svc-auth"}` })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Deactivate ${"svc-auth"}` })).toBeInTheDocument();
    expect(mocks.listServiceCatalog).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/SLA\s*15/)).toBeInTheDocument();
  });

  it("creates a service catalog through the API wrapper and refreshes the list", async () => {
    const user = userEvent.setup();
    const createdEntry: ServiceCatalogFixture = {
      service_id: "svc-chat",
      name: "Chat API",
      owner_team: "Product",
      category: null,
      tier: null,
      criticality: null,
      sla_target_minutes: 20,
      description: "Chat service",
      service_type: "incident",
      value_stream: "operate",
      active: true,
      created_at: "2026-01-03T00:00:00Z",
      updated_at: "2026-01-03T00:00:00Z",
      updated_by: null,
    };

    mocks.listServiceCatalog
      .mockResolvedValueOnce(sampleCatalogs)
      .mockResolvedValueOnce([...sampleCatalogs, createdEntry]);
    mocks.createServiceCatalog.mockResolvedValueOnce(createdEntry);

    renderCatalogRoute();

    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /new service catalog/i }));
    expect(screen.getByRole("heading", { name: /create service catalog/i })).toBeInTheDocument();

    await user.type(screen.getByLabelText(/^service id$/i), "svc-chat");
    await user.type(screen.getByLabelText(/^name$/i), "Chat API");
    await user.type(screen.getByLabelText(/^description$/i), "Chat service");
    await user.selectOptions(screen.getByLabelText(/^service type$/i), "incident");
    await user.type(screen.getByLabelText(/^value stream$/i), "operate");
    await user.type(screen.getByLabelText(/^sla target minutes$/i), "20");

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(mocks.createServiceCatalog).toHaveBeenCalledTimes(1);
    });
    const payload = mocks.createServiceCatalog.mock.calls[0][0];
    expect(payload).toMatchObject({
      service_id: "svc-chat",
      name: "Chat API",
      description: "Chat service",
      service_type: "incident",
      value_stream: "operate",
      sla_target_minutes: 20,
    });

    await waitFor(() => {
      expect(screen.getByText("Chat API")).toBeInTheDocument();
    });
    expect(mocks.listServiceCatalog).toHaveBeenCalledTimes(2);
  });

  it("edits an existing catalog and calls updateServiceCatalog", async () => {
    const user = userEvent.setup();
    const updatedEntry = {
      ...sampleCatalogs[0],
      name: "Auth API v2",
      sla_target_minutes: 25,
    };

    mocks.listServiceCatalog
      .mockResolvedValueOnce(sampleCatalogs)
      .mockResolvedValueOnce([updatedEntry, sampleCatalogs[1]]);
    mocks.updateServiceCatalog.mockResolvedValueOnce(updatedEntry);

    renderCatalogRoute();

    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: `Edit ${"svc-auth"}` }));

    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement;
    await user.clear(nameInput);
    await user.type(nameInput, "Auth API v2");

    await user.clear(screen.getByLabelText(/^sla target minutes$/i));
    await user.type(screen.getByLabelText(/^sla target minutes$/i), "25");

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(mocks.updateServiceCatalog).toHaveBeenCalledTimes(1);
    });
    const payload = mocks.updateServiceCatalog.mock.calls[0][1];
    expect(payload).toMatchObject({
      service_id: "svc-auth",
      name: "Auth API v2",
      sla_target_minutes: 25,
    });
    expect(payload).toHaveProperty("description");

    await waitFor(() => {
      expect(screen.getByText("Auth API v2")).toBeInTheDocument();
    });
    expect(screen.getByText("Auth API v2")).toBeInTheDocument();
  });

  it("deactivates a catalog entry and refreshes from /itsm/service-catalog", async () => {
    const user = userEvent.setup();

    mocks.listServiceCatalog
      .mockResolvedValueOnce(sampleCatalogs)
      .mockResolvedValueOnce(sampleCatalogs);
    mocks.deactivateServiceCatalog.mockResolvedValueOnce({
      ...sampleCatalogs[0],
      active: false,
    });

    renderCatalogRoute();

    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: `Deactivate ${"svc-auth"}` }));

    await waitFor(() => {
      expect(mocks.deactivateServiceCatalog).toHaveBeenCalledTimes(1);
    });
    expect(mocks.deactivateServiceCatalog).toHaveBeenCalledWith("svc-auth");
    expect(mocks.listServiceCatalog).toHaveBeenCalledTimes(2);
  });
});