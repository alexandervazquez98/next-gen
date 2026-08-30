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
    listServiceCatalog: (...a: unknown[]) => mocks.listServiceCatalog(...a),
    createServiceCatalog: (...a: unknown[]) => mocks.createServiceCatalog(...a),
    updateServiceCatalog: (...a: unknown[]) => mocks.updateServiceCatalog(...a),
    deactivateServiceCatalog: (...a: unknown[]) => mocks.deactivateServiceCatalog(...a),
    downloadCatalogTemplate: (...a: unknown[]) => mocks.downloadCatalogTemplate(...a),
    importCatalogWorkbook: (...a: unknown[]) => mocks.importCatalogWorkbook(...a),
  };
});

const baseCatalog = {
  service_id: "svc-auth",
  name: "Auth API",
  owner_team: "Platform",
  category: "SaaS",
  tier: "gold",
  criticality: "high",
  sla_target_minutes: 15,
  description: "Auth service",
  service_type: "service_request" as const,
  value_stream: "deliver",
  active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  updated_by: null,
};

const renderCatalogRoute = () =>
  render(
    <MemoryRouter initialEntries={["/itsm/service-catalog"]}>
      <Routes>
        <Route path="/itsm/service-catalog" element={<ItsmServiceCatalogPage />} />
      </Routes>
    </MemoryRouter>,
  );

describe("ItsmServiceCatalogPage — WU 8 governance + import UX", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the catalog with Service Management copy and required governance fields", async () => {
    mocks.listServiceCatalog.mockResolvedValueOnce([baseCatalog]);
    renderCatalogRoute();

    expect(
      await screen.findByRole("heading", { name: /service catalog/i, level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Auth API/)).toBeInTheDocument();
  });

  it("creates a catalog entry with description, service_type, and value_stream", async () => {
    const user = userEvent.setup();
    const createdEntry = {
      ...baseCatalog,
      service_id: "svc-chat",
      name: "Chat API",
      owner_team: "Product",
      description: "Chat service",
      service_type: "incident" as const,
      value_stream: "operate",
      sla_target_minutes: 20,
    };

    mocks.listServiceCatalog
      .mockResolvedValueOnce([baseCatalog])
      .mockResolvedValueOnce([baseCatalog, createdEntry]);
    mocks.createServiceCatalog.mockResolvedValueOnce(createdEntry);

    renderCatalogRoute();
    await screen.findByText(/Auth API/);

    await user.click(screen.getByRole("button", { name: /new service catalog/i }));
    await user.type(screen.getByLabelText(/^service id$/i), "svc-chat");
    await user.type(screen.getByLabelText(/^name$/i), "Chat API");
    await user.type(screen.getByLabelText(/^description$/i), "Chat service");
    await user.selectOptions(screen.getByLabelText(/^service type$/i), "incident");
    await user.type(screen.getByLabelText(/^value stream$/i), "operate");
    await user.type(screen.getByLabelText(/^sla target minutes$/i), "20");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(mocks.createServiceCatalog).toHaveBeenCalledTimes(1));
    const payload = mocks.createServiceCatalog.mock.calls[0][0];
    expect(payload).toMatchObject({
      service_id: "svc-chat",
      name: "Chat API",
      description: "Chat service",
      service_type: "incident",
      value_stream: "operate",
      sla_target_minutes: 20,
    });
  });

  it("blocks save when description, service_type, or value_stream is missing", async () => {
    const user = userEvent.setup();
    mocks.listServiceCatalog.mockResolvedValueOnce([baseCatalog]);

    renderCatalogRoute();
    await screen.findByText(/Auth API/);

    await user.click(screen.getByRole("button", { name: /new service catalog/i }));
    await user.type(screen.getByLabelText(/^service id$/i), "svc-bad");
    await user.type(screen.getByLabelText(/^name$/i), "Bad");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mocks.createServiceCatalog).not.toHaveBeenCalled();
    expect(await screen.findByText(/description.*required/i)).toBeInTheDocument();
  });

  it("downloads the catalog import template when the button is clicked", async () => {
    mocks.listServiceCatalog.mockResolvedValueOnce([baseCatalog]);
    mocks.downloadCatalogTemplate.mockResolvedValueOnce(undefined);

    renderCatalogRoute();
    await screen.findByText(/Auth API/);

    await userEvent.setup().click(screen.getByRole("button", { name: /download import template/i }));
    expect(mocks.downloadCatalogTemplate).toHaveBeenCalledTimes(1);
  });

  it("uploads the workbook and surfaces the structured validation failure", async () => {
    const user = userEvent.setup();
    mocks.listServiceCatalog.mockResolvedValueOnce([baseCatalog]);
    mocks.importCatalogWorkbook.mockRejectedValueOnce(
      Object.assign(new Error("Validation failed"), {
        status: 400,
        detail: {
          status: "validation_failed",
          message: "Workbook validation failed; no records were imported.",
          errors: [
            {
              row: 4,
              field: "service_type",
              code: "invalid_enum",
              reason: "Must be one of: incident, service_request",
            },
          ],
          error_count: 1,
        },
      }),
    );

    renderCatalogRoute();
    await screen.findByText(/Auth API/);

    const fileInput = screen.getByLabelText(/^import workbook$/i) as HTMLInputElement;
    const file = new File(["fake"], "catalog.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await user.upload(fileInput, file);

    await waitFor(() => expect(mocks.importCatalogWorkbook).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(/Workbook validation failed; no records were imported/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Row 4 — service_type/)).toBeInTheDocument();
  });
});