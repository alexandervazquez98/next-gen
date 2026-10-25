import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
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

const hooks = vi.hoisted(() => ({
  valueStreams: [
    { value: "operate", label: "Operate" },
    { value: "deliver", label: "Deliver" },
  ],
  tiers: [
    { value: "bronze", label: "Bronze" },
    { value: "silver", label: "Silver" },
    { value: "gold", label: "Gold" },
    { value: "platinum", label: "Platinum" },
  ],
  criticalities: [
    { value: "low", label: "Low" },
    { value: "medium", label: "Medium" },
    { value: "high", label: "High" },
    { value: "critical", label: "Critical" },
  ],
  owners: [{ name: "SRE" }, { name: "Finance" }],
  categories: [{ name: "Business" }, { name: "Technical" }],
}));

const useDictionariesModule = vi.hoisted(() => ({
  useDictionaryValues: vi.fn(),
  useValueStreams: vi.fn(),
  useTiers: vi.fn(),
  useCriticalities: vi.fn(),
}));
const useOwnersModule = vi.hoisted(() => ({ useOwners: vi.fn() }));
const useCategoriesModule = vi.hoisted(() => ({ useCategories: vi.fn() }));

vi.mock("../../services/itsm", async () => {
  const actual = await vi.importActual<typeof import("../../services/itsm")>("../../services/itsm");
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

vi.mock("../../hooks/useDictionaries", () => useDictionariesModule);
vi.mock("../../hooks/useOwners", () => useOwnersModule);
vi.mock("../../hooks/useCategories", () => useCategoriesModule);

const fakeQuery = (data: unknown) => ({
  data,
  isLoading: false,
  isError: false,
  error: null,
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

const installHookMocks = ({
  valueStreams = hooks.valueStreams,
  tiers = hooks.tiers,
  criticalities = hooks.criticalities,
  owners = hooks.owners,
  categories = hooks.categories,
  ownersEmpty = false,
  categoriesEmpty = false,
}: {
  valueStreams?: typeof hooks.valueStreams;
  tiers?: typeof hooks.tiers;
  criticalities?: typeof hooks.criticalities;
  owners?: typeof hooks.owners;
  categories?: typeof hooks.categories;
  ownersEmpty?: boolean;
  categoriesEmpty?: boolean;
} = {}) => {
  useDictionariesModule.useDictionaryValues.mockReturnValue(fakeQuery(valueStreams));
  useDictionariesModule.useValueStreams.mockReturnValue(fakeQuery(valueStreams));
  useDictionariesModule.useTiers.mockReturnValue(fakeQuery(tiers));
  useDictionariesModule.useCriticalities.mockReturnValue(fakeQuery(criticalities));
  useOwnersModule.useOwners.mockReturnValue({
    owners: ownersEmpty ? [] : owners,
    isLoading: false,
    isError: false,
    error: null,
    isEmpty: ownersEmpty,
  });
  useCategoriesModule.useCategories.mockReturnValue({
    categories: categoriesEmpty ? [] : categories,
    isLoading: false,
    isError: false,
    error: null,
    isEmpty: categoriesEmpty,
  });
};

describe("ItsmServiceCatalogPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    installHookMocks();
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

  it("S1: drops service_id input on create — backend mints the id", async () => {
    const user = userEvent.setup();
    const createdEntry: ServiceCatalogFixture = {
      ...sampleCatalogs[0],
      service_id: "sc-operate-AbCd1234",
      name: "Chat API",
      description: "Chat service",
      tier: "bronze",
      criticality: "low",
      owner_team: "SRE",
      category: "Technical",
      sla_target_minutes: 60,
      value_stream: "operate",
      service_type: "incident",
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

    // S1: no service_id input on create form.
    expect(screen.queryByLabelText(/^service id$/i)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/^name$/i), "Chat API");
    await user.type(screen.getByLabelText(/^description$/i), "Chat service");
    await user.selectOptions(screen.getByLabelText(/^service type$/i), "incident");
    await user.selectOptions(screen.getByLabelText(/^value stream$/i), "operate");
    await user.selectOptions(screen.getByLabelText(/^owner team$/i), "SRE");
    await user.selectOptions(screen.getByLabelText(/^category$/i), "Technical");
    await user.selectOptions(screen.getByLabelText(/^tier$/i), "bronze");
    await user.selectOptions(screen.getByLabelText(/^criticality$/i), "low");
    // S6: composite SLA control — defaults to hours, value "1" => 60 minutes.
    expect(screen.getByLabelText(/^sla unit$/i)).toHaveValue("hours");
    await user.clear(screen.getByLabelText(/^sla target$/i));
    await user.type(screen.getByLabelText(/^sla target$/i), "1");

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(mocks.createServiceCatalog).toHaveBeenCalledTimes(1);
    });
    const payload = mocks.createServiceCatalog.mock.calls[0][0];
    // The wire payload must NOT carry service_id (S1 contract).
    expect(payload).not.toHaveProperty("service_id");
    expect(payload).toMatchObject({
      name: "Chat API",
      description: "Chat service",
      service_type: "incident",
      value_stream: "operate",
      owner_team: "SRE",
      category: "Technical",
      tier: "bronze",
      criticality: "low",
      sla_target_minutes: 60, // 1 hour × 60 min/hr
    });

    await waitFor(() => {
      expect(screen.getByText("Chat API")).toBeInTheDocument();
    });
    expect(mocks.listServiceCatalog).toHaveBeenCalledTimes(2);

    // S1: the backend-assigned id is surfaced read-only instead of being
    // cleared away with the rest of the form.
    const assignedId = screen.getByLabelText(/^service id$/i);
    expect(assignedId).toHaveValue("sc-operate-AbCd1234");
    expect(assignedId).toHaveAttribute("readonly");
    expect(assignedId).not.toBeDisabled();
  });

  it("S1: edit form displays service_id read-only (disabled)", async () => {
    const user = userEvent.setup();
    mocks.listServiceCatalog.mockResolvedValueOnce(sampleCatalogs);
    mocks.updateServiceCatalog.mockResolvedValueOnce(sampleCatalogs[0]);

    renderCatalogRoute();

    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: `Edit ${"svc-auth"}` }));

    const serviceIdField = screen.getByLabelText(/^service id$/i);
    expect(serviceIdField).toBeInTheDocument();
    expect(serviceIdField).toBeDisabled();
    expect((serviceIdField as HTMLInputElement).value).toBe("svc-auth");
  });

  it("S2: renders value_stream as a <select> populated from the dictionary endpoint", async () => {
    const user = userEvent.setup();
    mocks.listServiceCatalog.mockResolvedValueOnce(sampleCatalogs);

    renderCatalogRoute();
    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /new service catalog/i }));

    const select = screen.getByLabelText(/^value stream$/i) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("operate");
    expect(options).toContain("deliver");
    // The CTA must point at the Dictionary manager that actually exists
    // (Administration → Dictionaries), not at a nonexistent route.
    const cta = screen.getByRole("link", { name: /\+ add new value stream/i });
    expect(cta.getAttribute("href")).toContain("/admin");
    expect(cta.getAttribute("href")).not.toContain("/itsm/dictionaries");
  });

  it("S3: renders owner_team as a <select> with empty-state hint", async () => {
    mocks.listServiceCatalog.mockResolvedValueOnce(sampleCatalogs);
    installHookMocks({ ownersEmpty: true });

    renderCatalogRoute();
    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await userEvent.setup().click(screen.getByRole("button", { name: /new service catalog/i }));

    const select = screen.getByLabelText(/^owner team$/i) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.options.length).toBe(1); // only the placeholder
    expect(
      screen.getByText(/No owner groups exist yet — create one in the Owners tab first\./i),
    ).toBeInTheDocument();
  });

  it("S4: renders category as a <select> with ITIL helper text", async () => {
    const user = userEvent.setup();
    mocks.listServiceCatalog.mockResolvedValueOnce(sampleCatalogs);

    renderCatalogRoute();
    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /new service catalog/i }));

    const select = screen.getByLabelText(/^category$/i) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    const labels = Array.from(select.options).map((o) => o.text);
    expect(labels).toContain("Business");
    expect(labels).toContain("Technical");
    expect(
      screen.getByText(/ITIL-aligned taxonomy — see docs\/itsm\/service-catalog\.md/i),
    ).toBeInTheDocument();

    // S4: the helper cites the eight canonical ServiceNow-aligned categories.
    const helper = screen.getByRole("list", { name: /canonical itil categories/i });
    for (const category of [
      "Infrastructure & Platform",
      "Application Services",
      "End User Computing",
      "IT Security",
      "Telecommunications",
      "Business Services",
      "Workspace",
      "Consulting & Advisory",
    ]) {
      expect(within(helper).getByText(category)).toBeInTheDocument();
    }
  });

  it("S5: renders tier and criticality as <select> from new dictionary entries", async () => {
    const user = userEvent.setup();
    mocks.listServiceCatalog.mockResolvedValueOnce(sampleCatalogs);

    renderCatalogRoute();
    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /new service catalog/i }));

    const tierSelect = screen.getByLabelText(/^tier$/i) as HTMLSelectElement;
    expect(tierSelect.tagName).toBe("SELECT");
    expect(Array.from(tierSelect.options).map((o) => o.value)).toEqual([
      "",
      "bronze",
      "silver",
      "gold",
      "platinum",
    ]);

    const criticalitySelect = screen.getByLabelText(/^criticality$/i) as HTMLSelectElement;
    expect(criticalitySelect.tagName).toBe("SELECT");
    expect(Array.from(criticalitySelect.options).map((o) => o.value)).toEqual([
      "",
      "low",
      "medium",
      "high",
      "critical",
    ]);

    expect(screen.getByText(/bronze \/ silver \/ gold \/ platinum/i)).toBeInTheDocument();
    expect(screen.getByText(/low \/ medium \/ high \/ critical/i)).toBeInTheDocument();

    // S5: the recommended pairing matrix is visible (recommended only —
    // the two controls stay independent).
    const matrix = screen.getByRole("table", {
      name: /recommended tier and criticality pairing/i,
    });
    expect(
      within(matrix)
        .getAllByRole("row")
        .slice(1)
        .map((row) =>
          within(row)
            .getAllByRole("cell")
            .map((cell) => cell.textContent),
        ),
    ).toEqual([
      ["bronze", "low"],
      ["silver", "medium"],
      ["gold", "high"],
      ["platinum", "critical"],
    ]);
  });

  it("S6: SLA unit selector defaults to hours and converts to minutes on submit", async () => {
    const user = userEvent.setup();
    const createdEntry: ServiceCatalogFixture = {
      ...sampleCatalogs[0],
      service_id: "sc-deliver-XyZ12345",
      name: "Portal API",
      sla_target_minutes: 240, // 4 hours × 60
      description: "Portal service",
      tier: "silver",
      criticality: "medium",
      value_stream: "deliver",
      owner_team: "SRE",
      category: "Business",
      service_type: "service_request",
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

    // S6: default unit is hours.
    expect(screen.getByLabelText(/^sla unit$/i)).toHaveValue("hours");

    await user.type(screen.getByLabelText(/^name$/i), "Portal API");
    await user.type(screen.getByLabelText(/^description$/i), "Portal service");
    await user.selectOptions(screen.getByLabelText(/^service type$/i), "service_request");
    await user.selectOptions(screen.getByLabelText(/^value stream$/i), "deliver");
    await user.selectOptions(screen.getByLabelText(/^owner team$/i), "SRE");
    await user.selectOptions(screen.getByLabelText(/^category$/i), "Business");
    await user.selectOptions(screen.getByLabelText(/^tier$/i), "silver");
    await user.selectOptions(screen.getByLabelText(/^criticality$/i), "medium");
    await user.clear(screen.getByLabelText(/^sla target$/i));
    await user.type(screen.getByLabelText(/^sla target$/i), "4");

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(mocks.createServiceCatalog).toHaveBeenCalledTimes(1);
    });
    const payload = mocks.createServiceCatalog.mock.calls[0][0];
    expect(payload.sla_target_minutes).toBe(240); // 4 hours → 240 minutes
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

    await user.clear(screen.getByLabelText(/^sla target$/i));
    await user.type(screen.getByLabelText(/^sla target$/i), "25");

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
