import { describe, beforeEach, expect, it, vi } from "vitest";
import {
  createServiceCatalog,
  createTicketFolio,
  deactivateServiceCatalog,
  listServiceCatalog,
  listTicketFolios,
  transitionTicketFolio,
  updateServiceCatalog,
  updateTicketFolio,
} from "../itsm";

const mocks = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
}));

vi.mock("../api", () => ({
  api: {
    get: mocks.mockGet,
    post: mocks.mockPost,
    put: mocks.mockPut,
  },
}));

describe("ITSM service catalog API wrapper", () => {
  beforeEach(() => {
    mocks.mockGet.mockReset();
    mocks.mockPost.mockReset();
    mocks.mockPut.mockReset();
  });

  it("loads the catalog list from /api/itsm/service-catalog", async () => {
    const catalog = {
      service_id: "svc-auth",
      name: "Auth Platform",
      sla_target_minutes: 30,
      active: true,
      owner_team: "Platform",
      category: "SaaS",
      tier: "gold",
      criticality: "high",
      updated_by: "admin",
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
    };

    mocks.mockGet.mockResolvedValue([catalog]);

    const payload = await listServiceCatalog();

    expect(payload).toEqual([catalog]);
    expect(mocks.mockGet).toHaveBeenCalledTimes(1);
    expect(mocks.mockGet).toHaveBeenCalledWith("/itsm/service-catalog", {});
  });

  it("creates service catalog entries using /api/itsm/service-catalog", async () => {
    const requestPayload = {
      service_id: "svc-billing",
      name: "Billing Gateway",
      sla_target_minutes: 45,
      active: true,
    };
    const created = {
      ...requestPayload,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      owner_team: null,
      category: null,
      tier: null,
      criticality: null,
      updated_by: null,
    };

    mocks.mockPost.mockResolvedValue(created);

    const result = await createServiceCatalog(requestPayload);

    expect(result).toEqual(created);
    expect(mocks.mockPost).toHaveBeenCalledTimes(1);
    expect(mocks.mockPost).toHaveBeenCalledWith("/itsm/service-catalog", requestPayload);
  });

  it("updates catalog entries using encoded /itsm/service-catalog/{id}", async () => {
    const serviceId = "svc/network:core";
    const requestPayload = {
      name: "Network Core",
      sla_target_minutes: 60,
      category: "network",
    };

    const updated = {
      service_id: serviceId,
      name: requestPayload.name,
      sla_target_minutes: 60,
      active: true,
      owner_team: null,
      criticality: null,
      tier: null,
      category: requestPayload.category,
      updated_by: "admin",
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
    };

    mocks.mockPut.mockResolvedValue(updated);

    const result = await updateServiceCatalog(serviceId, requestPayload);

    expect(result).toEqual(updated);
    expect(mocks.mockPut).toHaveBeenCalledTimes(1);
    expect(mocks.mockPut).toHaveBeenCalledWith(
      "/itsm/service-catalog/svc%2Fnetwork%3Acore",
      requestPayload,
    );
  });

  it("lists ticket folios from /api/itsm/tickets", async () => {
    const ticket = {
      ticket_id: "TK-001",
      type: "request",
      title: "Access request",
      description: null,
      service_catalog_id: "svc-auth",
      status: "open",
      closed_reason: null,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      updated_by: "admin",
    };

    mocks.mockGet.mockResolvedValue([ticket]);

    const result = await listTicketFolios({ status: "open", service_catalog_id: "svc-auth" });

    expect(result).toEqual([ticket]);
    expect(mocks.mockGet).toHaveBeenCalledWith("/itsm/tickets", {
      params: { status: "open", service_catalog_id: "svc-auth" },
    });
  });

  it("creates and updates ticket folios through /api/itsm/tickets", async () => {
    const created = {
      ticket_id: "TK-002",
      type: "incident",
      title: "Alarm follow-up",
      description: "Check alarm",
      service_catalog_id: null,
      status: "open",
      closed_reason: null,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      updated_by: "admin",
    };
    mocks.mockPost.mockResolvedValueOnce(created);
    mocks.mockPut.mockResolvedValueOnce({ ...created, title: "Alarm follow-up updated" });

    await expect(createTicketFolio({ ticket_id: "TK-002", type: "incident", title: "Alarm follow-up" })).resolves.toEqual(created);
    await expect(updateTicketFolio("TK-002", { title: "Alarm follow-up updated" })).resolves.toMatchObject({
      title: "Alarm follow-up updated",
    });

    expect(mocks.mockPost).toHaveBeenCalledWith("/itsm/tickets", {
      ticket_id: "TK-002",
      type: "incident",
      title: "Alarm follow-up",
    });
    expect(mocks.mockPut).toHaveBeenCalledWith("/itsm/tickets/TK-002", {
      title: "Alarm follow-up updated",
    });
  });

  it("transitions ticket folios through /api/itsm/tickets/{id}/transition", async () => {
    const transitioned = {
      ticket_id: "TK-003",
      type: "request",
      title: "Validate access",
      description: null,
      service_catalog_id: null,
      status: "in_validation",
      closed_reason: null,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      updated_by: "admin",
    };
    mocks.mockPost.mockResolvedValueOnce(transitioned);

    const result = await transitionTicketFolio("TK-003", "in_validation");

    expect(result).toEqual(transitioned);
    expect(mocks.mockPost).toHaveBeenCalledWith("/itsm/tickets/TK-003/transition", {
      next_status: "in_validation",
    });
  });

  it("deactivates catalog records through /api/itsm/service-catalog/{id}/deactivate", async () => {
    const deactivated = {
      service_id: "svc-auth",
      name: "Auth Platform",
      sla_target_minutes: 30,
      active: false,
      owner_team: "Platform",
      category: "SaaS",
      tier: "gold",
      criticality: "high",
      updated_by: "admin",
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-02T00:00:00Z",
    };

    mocks.mockPost.mockResolvedValue(deactivated);

    const result = await deactivateServiceCatalog("svc-auth");

    expect(result).toEqual(deactivated);
    expect(mocks.mockPost).toHaveBeenCalledTimes(1);
    expect(mocks.mockPost).toHaveBeenCalledWith("/itsm/service-catalog/svc-auth/deactivate", {});
  });
});
