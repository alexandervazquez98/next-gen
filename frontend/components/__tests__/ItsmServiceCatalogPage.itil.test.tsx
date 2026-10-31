import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ItsmServiceCatalogPage from "../ItsmServiceCatalogPage";
import AdminPage from "../AdminPage";

// ---------------------------------------------------------------------------
// Feature #480 — ITIL-aligned Service Catalog UX (S1-S6).
//
// This suite is deliberately *contract level*: it mocks the HTTP boundary
// (`services/api`) instead of the data hooks, so every assertion proves the
// real request URL, the real controlled control, and the real wire payload.
// Mocking the hooks (as the sibling suite does) cannot prove any of those.
// ---------------------------------------------------------------------------

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("../../services/api", async () => {
  const actual = await vi.importActual<typeof import("../../services/api")>("../../services/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (...args: unknown[]) => apiMock.get(...args),
      post: (...args: unknown[]) => apiMock.post(...args),
      put: (...args: unknown[]) => apiMock.put(...args),
      delete: (...args: unknown[]) => apiMock.delete(...args),
    },
  };
});

// The administration surface reads the operator from the auth context.
vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({ hasPermission: () => true }),
}));

// Keep the AdminPage deep-link test focused on tab selection.
vi.mock("../DictionaryManager", () => ({ default: () => <div>Dictionary Manager</div> }));
vi.mock("../MetricsManager", () => ({ default: () => <div>Metrics Manager</div> }));

const DICTIONARY_RESPONSES: Record<string, Array<{ value: string; label: string }>> = {
  "/dictionaries?key=value_stream&active=true": [
    { value: "operate", label: "Operate" },
    { value: "deliver", label: "Deliver" },
  ],
  "/dictionaries?key=tier&active=true": [
    { value: "bronze", label: "Bronze" },
    { value: "silver", label: "Silver" },
    { value: "gold", label: "Gold" },
    { value: "platinum", label: "Platinum" },
  ],
  "/dictionaries?key=criticality&active=true": [
    { value: "low", label: "Low" },
    { value: "medium", label: "Medium" },
    { value: "high", label: "High" },
    { value: "critical", label: "Critical" },
  ],
};

// S4 — canonical ServiceNow-aligned ITIL taxonomy (maintainer decision).
const CANONICAL_CATEGORIES = [
  "Infrastructure & Platform",
  "Application Services",
  "End User Computing",
  "IT Security",
  "Telecommunications",
  "Business Services",
  "Workspace",
  "Consulting & Advisory",
];

const OWNERS_FIXTURE = [
  { name: "SRE", users: [] },
  { name: "Finance", users: [] },
];

const CATEGORY_FIXTURE = CANONICAL_CATEGORIES.map((name) => ({ name, icon_key: null }));

const CATALOG_FIXTURE = [
  {
    service_id: "svc-auth",
    name: "Auth API",
    owner_team: "SRE",
    category: "IT Security",
    tier: "gold",
    criticality: "high",
    sla_target_minutes: 15,
    description: "Auth service",
    service_type: "service_request",
    value_stream: "operate",
    active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: null,
  },
];

const CREATED_FIXTURE = {
  ...CATALOG_FIXTURE[0],
  service_id: "sc-operate-AbCd1234",
  name: "Chat API",
  description: "Chat service",
  owner_team: "SRE",
  category: "Application Services",
  tier: "bronze",
  criticality: "low",
  sla_target_minutes: 120,
  value_stream: "operate",
  service_type: "incident",
};

const getUrls = () => apiMock.get.mock.calls.map((call) => call[0] as string);

let queryClient: QueryClient;

const renderPage = () =>
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/itsm/service-catalog"]}>
        <ItsmServiceCatalogPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

const openCreateForm = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: /new service catalog/i }));
  // The lookups are fetched on mount; wait until the controlled selects are
  // populated so the assertions below are not racing the network layer.
  await waitFor(() => {
    expect(
      (screen.getByLabelText(/^value stream$/i) as HTMLSelectElement).options.length,
    ).toBeGreaterThan(1);
  });
};

const fillCreateForm = async (
  user: ReturnType<typeof userEvent.setup>,
  { sla = "2", unit = "hours" }: { sla?: string; unit?: string } = {},
) => {
  await openCreateForm(user);
  await user.type(screen.getByLabelText(/^name$/i), "Chat API");
  await user.type(screen.getByLabelText(/^description$/i), "Chat service");
  await user.selectOptions(screen.getByLabelText(/^service type$/i), "incident");
  await user.selectOptions(screen.getByLabelText(/^value stream$/i), "operate");
  await user.selectOptions(screen.getByLabelText(/^owner team$/i), "SRE");
  await user.selectOptions(screen.getByLabelText(/^category$/i), "Application Services");
  await user.selectOptions(screen.getByLabelText(/^tier$/i), "bronze");
  await user.selectOptions(screen.getByLabelText(/^criticality$/i), "low");
  const slaInput = screen.getByLabelText(/^sla target$/i);
  await user.clear(slaInput);
  await user.type(slaInput, sla);
  await user.selectOptions(screen.getByLabelText(/^sla unit$/i), unit);
};

const lastCreatePayload = () => {
  const calls = apiMock.post.mock.calls;
  const call = calls[calls.length - 1];
  return { endpoint: call[0] as string, payload: call[1] as Record<string, unknown> };
};

beforeEach(() => {
  vi.clearAllMocks();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  apiMock.get.mockImplementation((endpoint: string) => {
    if (endpoint === "/itsm/service-catalog") {
      return Promise.resolve(CATALOG_FIXTURE);
    }
    if (endpoint in DICTIONARY_RESPONSES) {
      return Promise.resolve(DICTIONARY_RESPONSES[endpoint]);
    }
    if (endpoint === "/owners") {
      return Promise.resolve(OWNERS_FIXTURE);
    }
    if (endpoint === "/categories") {
      return Promise.resolve(CATEGORY_FIXTURE);
    }
    return Promise.resolve([]);
  });
  apiMock.post.mockResolvedValue(CREATED_FIXTURE);
  apiMock.put.mockResolvedValue(CATALOG_FIXTURE[0]);
});

afterEach(() => {
  queryClient.clear();
});

describe("ItsmServiceCatalogPage — ITIL contract (feature #480)", () => {
  it("S2/S5: reads value_stream, tier and criticality from the root dictionary contract", async () => {
    renderPage();

    await waitFor(() => {
      expect(getUrls()).toContain("/dictionaries?key=value_stream&active=true");
    });

    expect(getUrls()).toContain("/dictionaries?key=tier&active=true");
    expect(getUrls()).toContain("/dictionaries?key=criticality&active=true");

    // No other dictionary shape may be used — the pre-#480 implementation
    // called the nonexistent `/dictionaries/values` path.
    const dictionaryUrls = getUrls().filter((url) => url.startsWith("/dictionaries"));
    expect(dictionaryUrls).toHaveLength(3);
    expect(dictionaryUrls.every((url) => !url.includes("/dictionaries/values"))).toBe(true);
  });

  it("S3/S4: reads owners and categories from their public endpoints", async () => {
    renderPage();

    await waitFor(() => {
      expect(getUrls()).toContain("/owners");
    });
    expect(getUrls()).toContain("/categories");
  });

  it("S2/S3/S4/S5: renders every lookup as a controlled select fed by the fetched data", async () => {
    const user = userEvent.setup();
    renderPage();

    await openCreateForm(user);

    const valueStream = screen.getByLabelText(/^value stream$/i) as HTMLSelectElement;
    expect(valueStream.tagName).toBe("SELECT");
    expect(Array.from(valueStream.options).map((option) => option.value)).toEqual([
      "",
      "operate",
      "deliver",
    ]);

    const owner = screen.getByLabelText(/^owner team$/i) as HTMLSelectElement;
    expect(owner.tagName).toBe("SELECT");
    expect(Array.from(owner.options).map((option) => option.value)).toEqual(["", "SRE", "Finance"]);

    const category = screen.getByLabelText(/^category$/i) as HTMLSelectElement;
    expect(category.tagName).toBe("SELECT");
    expect(Array.from(category.options).map((option) => option.value)).toEqual([
      "",
      ...CANONICAL_CATEGORIES,
    ]);

    const tier = screen.getByLabelText(/^tier$/i) as HTMLSelectElement;
    expect(tier.tagName).toBe("SELECT");
    expect(Array.from(tier.options).map((option) => option.value)).toEqual([
      "",
      "bronze",
      "silver",
      "gold",
      "platinum",
    ]);

    const criticality = screen.getByLabelText(/^criticality$/i) as HTMLSelectElement;
    expect(criticality.tagName).toBe("SELECT");
    expect(Array.from(criticality.options).map((option) => option.value)).toEqual([
      "",
      "low",
      "medium",
      "high",
      "critical",
    ]);
  });

  it("S2: links the value stream CTA to the existing Dictionary manager route", async () => {
    const user = userEvent.setup();
    renderPage();

    await openCreateForm(user);

    const cta = screen.getByRole("link", { name: /\+ add new value stream/i });
    const href = cta.getAttribute("href") ?? "";
    expect(href).toContain("/admin");
    expect(href).toContain("tab=dictionaries");
    expect(href).not.toContain("/itsm/dictionaries");
  });

  it("S3: shows the create-owner hint when no owner groups exist", async () => {
    apiMock.get.mockImplementation((endpoint: string) => {
      if (endpoint === "/owners") {
        return Promise.resolve([]);
      }
      if (endpoint === "/itsm/service-catalog") {
        return Promise.resolve(CATALOG_FIXTURE);
      }
      if (endpoint in DICTIONARY_RESPONSES) {
        return Promise.resolve(DICTIONARY_RESPONSES[endpoint]);
      }
      if (endpoint === "/categories") {
        return Promise.resolve(CATEGORY_FIXTURE);
      }
      return Promise.resolve([]);
    });

    const user = userEvent.setup();
    renderPage();

    await openCreateForm(user);

    expect(
      await screen.findByText(/No owner groups exist yet — create one in the Owners tab first\./i),
    ).toBeInTheDocument();
  });

  it("S4: cites the eight canonical ServiceNow-aligned categories in the helper", async () => {
    const user = userEvent.setup();
    renderPage();

    await openCreateForm(user);

    const helper = screen.getByRole("list", { name: /canonical itil categories/i });
    for (const category of CANONICAL_CATEGORIES) {
      expect(within(helper).getByText(category)).toBeInTheDocument();
    }
  });

  it("S5: keeps tier and criticality independent and shows the recommended pairing matrix", async () => {
    const user = userEvent.setup();
    renderPage();

    await openCreateForm(user);

    const matrix = screen.getByRole("table", {
      name: /recommended tier and criticality pairing/i,
    });
    const rows = within(matrix).getAllByRole("row").slice(1);
    expect(
      rows.map((row) =>
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

    // Independent controls: a contradictory pair is still submitted as-is
    // (no server-side derivation, no wire-format change).
    await user.selectOptions(screen.getByLabelText(/^tier$/i), "gold");
    await user.selectOptions(screen.getByLabelText(/^criticality$/i), "low");
    expect((screen.getByLabelText(/^tier$/i) as HTMLSelectElement).value).toBe("gold");
    expect((screen.getByLabelText(/^criticality$/i) as HTMLSelectElement).value).toBe("low");
  });

  it("S1: omits service_id from the create payload and shows the assigned id read-only", async () => {
    const user = userEvent.setup();
    renderPage();

    await openCreateForm(user);

    // No service_id input while creating — the backend mints it.
    expect(screen.queryByLabelText(/^service id$/i)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/^name$/i), "Chat API");
    await user.type(screen.getByLabelText(/^description$/i), "Chat service");
    await user.selectOptions(screen.getByLabelText(/^service type$/i), "incident");
    await user.selectOptions(screen.getByLabelText(/^value stream$/i), "operate");
    await user.selectOptions(screen.getByLabelText(/^owner team$/i), "SRE");
    await user.selectOptions(screen.getByLabelText(/^category$/i), "Application Services");
    await user.selectOptions(screen.getByLabelText(/^tier$/i), "bronze");
    await user.selectOptions(screen.getByLabelText(/^criticality$/i), "low");

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledTimes(1);
    });

    const { endpoint, payload } = lastCreatePayload();
    expect(endpoint).toBe("/itsm/service-catalog");
    expect(payload).not.toHaveProperty("service_id");
    expect(payload).toMatchObject({
      name: "Chat API",
      description: "Chat service",
      service_type: "incident",
      value_stream: "operate",
      owner_team: "SRE",
      category: "Application Services",
      tier: "bronze",
      criticality: "low",
    });

    // The assigned id is displayed read-only instead of being cleared away.
    const assigned = await screen.findByLabelText(/^service id$/i);
    expect(assigned).toHaveValue("sc-operate-AbCd1234");
    expect(assigned).toHaveAttribute("readonly");
    expect(assigned).not.toBeDisabled();
  });

  it("S1: keeps the persisted service_id disabled in edit mode", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Auth API")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Edit svc-auth" }));

    const serviceId = screen.getByLabelText(/^service id$/i);
    expect(serviceId).toBeDisabled();
    expect(serviceId).toHaveValue("svc-auth");
  });

  it("S6: converts hours into integer minutes on create", async () => {
    const user = userEvent.setup();
    renderPage();

    await fillCreateForm(user, { sla: "2", unit: "hours" });
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledTimes(1);
    });

    const { payload } = lastCreatePayload();
    expect(payload.sla_target_minutes).toBe(120);
    expect(Number.isInteger(payload.sla_target_minutes)).toBe(true);
  });

  it("S6: converts minutes into integer minutes on create", async () => {
    const user = userEvent.setup();
    renderPage();

    await fillCreateForm(user, { sla: "45", unit: "minutes" });
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledTimes(1);
    });

    const { payload } = lastCreatePayload();
    expect(payload.sla_target_minutes).toBe(45);
  });

  it("S6: converts days into integer minutes on create", async () => {
    const user = userEvent.setup();
    renderPage();

    await fillCreateForm(user, { sla: "2", unit: "days" });
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledTimes(1);
    });

    const { payload } = lastCreatePayload();
    expect(payload.sla_target_minutes).toBe(2880);
  });

  it("S6: defaults the SLA unit to hours", async () => {
    const user = userEvent.setup();
    renderPage();

    await openCreateForm(user);

    expect(screen.getByLabelText(/^sla unit$/i)).toHaveValue("hours");
  });
});

// ---------------------------------------------------------------------------
// S2 — the Dictionary manager deep link consumed by the CTA above.
// ---------------------------------------------------------------------------
describe("AdminPage — Dictionary manager deep link (#480 S2)", () => {
  const renderAdminPage = (initialEntry: string) =>
    render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <AdminPage />
      </MemoryRouter>,
    );

  it("preselects the Dictionaries tab when the tab query parameter is present", async () => {
    renderAdminPage("/admin?tab=dictionaries");

    expect(await screen.findByText("Dictionary Manager")).toBeInTheDocument();
    expect(screen.queryByText("Metrics Manager")).not.toBeInTheDocument();
  });

  it("keeps the default METRICS tab when no tab parameter is present", async () => {
    renderAdminPage("/admin");

    expect(await screen.findByText("Metrics Manager")).toBeInTheDocument();
    expect(screen.queryByText("Dictionary Manager")).not.toBeInTheDocument();
  });

  it("falls back to the default METRICS tab for an unknown tab parameter", async () => {
    renderAdminPage("/admin?tab=bogus");

    expect(await screen.findByText("Metrics Manager")).toBeInTheDocument();
    expect(screen.queryByText("Dictionary Manager")).not.toBeInTheDocument();
  });
});
