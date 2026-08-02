/**
 * MonitoringConsole.smoke.test.tsx
 *
 * Smoke tests for MonitoringConsole.
 * Verifies the component mounts without errors and that banned imports
 * (leaflet-ant-path) are not present.
 *
 * react-leaflet and leaflet are mocked because they require a real browser
 * DOM with canvas/SVG that jsdom does not fully support.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import type React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { mockApiGet, mockApiPost } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockApiPost: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock api service — returns empty arrays to avoid fetch errors in jsdom
vi.mock("../../services/api", () => ({
  api: {
    get: mockApiGet,
    post: mockApiPost,
  },
}));

// Mock react-leaflet — components that need real Leaflet/canvas are stubbed
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: any) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => null,
  Polyline: () => null,
  CircleMarker: ({ children }: any) => <div>{children}</div>,
  Circle: () => null,
  Popup: ({ children }: any) => <div>{children}</div>,
  useMap: () => ({ fitBounds: vi.fn() }),
}));

// Mock leaflet itself to avoid window/document errors
vi.mock("leaflet", () => ({
  default: {
    icon: vi.fn(() => ({})),
    Marker: { prototype: { options: { icon: null } } },
    latLngBounds: vi.fn(() => ({ isValid: () => true })),
  },
  icon: vi.fn(() => ({})),
  Marker: { prototype: { options: { icon: null } } },
  latLngBounds: vi.fn(() => ({})),
}));

// Mock leaflet CSS — not needed in tests
vi.mock("leaflet/dist/leaflet.css", () => ({}));

// Mock child components that have their own complex deps
vi.mock("../DependencyMiniMap", () => ({
  default: () => <div data-testid="dependency-mini-map" />,
}));

vi.mock("../../hooks/useEventCorrelation", () => ({
  useEventCorrelation: (events: any[]) => events,
}));

// Mock AuthContext — MonitoringConsole now reads user/tier/hasPermission from useAuth
vi.mock("../../context/AuthContext", () => ({
  useAuth: vi.fn(() => ({
    user: {
      username: "admin",
      role: "ADMIN",
      permissions: [],
      tier: "T3",
      allowed_locations: [],
    },
    hasPermission: (_perm: string) => true,
    isAuthenticated: true,
    token: "mock-token",
    login: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MonitoringConsole smoke tests", () => {
  const renderWithQueryClient = (ui: React.ReactElement) => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockApiPost.mockResolvedValue({ message: "ok" });
    mockApiGet.mockResolvedValue([]);
  });

  it("GIVEN the component WHEN rendered with empty data THEN mounts without throwing", async () => {
    // Dynamic import after mocks are registered
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    expect(() => renderWithQueryClient(<MonitoringConsole />)).not.toThrow();
  });

  it("GIVEN the component WHEN rendered THEN Event Console header is visible", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    renderWithQueryClient(<MonitoringConsole />);

    expect(screen.getByText("Event Console")).toBeDefined();
  });

  it("GIVEN an ack action succeeds WHEN shared active events refetch THEN widgets and table converge without refetching nodes or links", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    let activeEventsCalls = 0;
    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") {
        return Promise.resolve([
          {
            id: "ci-1",
            label: "Router-01",
            type: "INFRASTRUCTURE",
            status: "OK",
            metadata: {},
            category: "NETWORK",
            ip: "10.0.0.1",
            location: { lat: 40.4, long: -3.7 },
            location_name: "Madrid HQ",
          },
        ]);
      }
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([{ name: "NETWORK" }]);
      if (url === "/events?status=CONSOLE") {
        activeEventsCalls += 1;
        return Promise.resolve(
          activeEventsCalls === 1
            ? [
                {
                  id: "evt-1",
                  ci_id: "ci-1",
                  ci_name: "Router-01",
                  metric_id: "metric-1",
                  metric_name: "CPU",
                  metric_protocol: "SNMP",
                  status: "OPEN",
                  severity: "CRITICAL",
                  message: "CPU over threshold",
                  created_at: "2026-04-04T20:00:00.000Z",
                  last_seen: "2026-04-04T20:00:00.000Z",
                  ack: false,
                  comments: [],
                },
              ]
            : [
                {
                  id: "evt-1",
                  ci_id: "ci-1",
                  ci_name: "Router-01",
                  metric_id: "metric-1",
                  metric_name: "CPU",
                  metric_protocol: "SNMP",
                  status: "ACK",
                  severity: "CRITICAL",
                  message: "CPU over threshold",
                  created_at: "2026-04-04T20:00:00.000Z",
                  last_seen: "2026-04-04T20:00:00.000Z",
                  ack: true,
                  ack_by: "admin",
                  comments: [],
                },
              ],
        );
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    expect(await screen.findByText("CPU over threshold")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ack" })).toBeInTheDocument();

    const criticalCard = screen.getByText("Critical Events").closest("div");
    const acknowledgedCard = screen.getByText("Acknowledged").closest("div");
    expect(criticalCard?.textContent).toContain("1");
    expect(acknowledgedCard?.textContent).toContain("0");

    fireEvent.click(screen.getByRole("button", { name: "Ack" }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/events/evt-1/ack", {});
    });

    await waitFor(() => {
      expect(screen.getByText("ACK")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: "Ack" })).toBeNull();
    expect(criticalCard?.textContent).toContain("0");
    expect(acknowledgedCard?.textContent).toContain("1");

    const endpointCalls = mockApiGet.mock.calls.reduce<Record<string, number>>((counts, [url]) => {
      counts[url] = (counts[url] ?? 0) + 1;
      return counts;
    }, {});

    expect(endpointCalls["/nodes"]).toBe(1);
    expect(endpointCalls["/links"]).toBe(1);
    expect(endpointCalls["/categories"]).toBe(1);
    expect(endpointCalls["/events?status=CONSOLE"]).toBe(2);
    expect(endpointCalls["/events/availability-report"]).toBeUndefined();
  });

  it("GIVEN an event CI has category_icon_key WHEN the stream renders THEN it shows the shared technology icon separate from status", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") {
        return Promise.resolve([
          {
            id: "ci-router",
            label: "Router-01",
            type: "Network",
            status: "OK",
            metadata: {},
            category: "Router",
            category_icon_key: "router",
            ip: "10.0.0.1",
            location: { lat: 40.4, long: -3.7 },
          },
        ]);
      }
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([{ name: "Router", icon_key: "router" }]);
      if (url === "/events?status=CONSOLE") {
        return Promise.resolve([
          {
            id: "evt-router",
            ci_id: "ci-router",
            ci_name: "Router-01",
            metric_id: "metric-cpu",
            metric_name: "CPU",
            metric_protocol: "SNMP",
            status: "OPEN",
            severity: "CRITICAL",
            message: "CPU over threshold",
            created_at: "2026-04-04T20:00:00.000Z",
            last_seen: "2026-04-04T20:00:00.000Z",
            ack: false,
            comments: [],
          },
        ]);
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    expect(await screen.findByLabelText("Router technology icon")).toHaveTextContent("router");
    expect(screen.getByText("Router-01")).toBeInTheDocument();
    expect(screen.getByText("OPEN")).toBeInTheDocument();
  });

  it("GIVEN an event CI lacks category_icon_key WHEN the stream renders THEN it falls back by category name", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") {
        return Promise.resolve([
          {
            id: "ci-switch",
            label: "Access-SW-01",
            type: "Layer 2 Switch",
            status: "OK",
            metadata: {},
            category: "Layer 2 Switch",
            category_icon_key: null,
            ip: "10.0.0.2",
            location: { lat: 40.4, long: -3.7 },
          },
        ]);
      }
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([{ name: "Layer 2 Switch" }]);
      if (url === "/events?status=CONSOLE") {
        return Promise.resolve([
          {
            id: "evt-switch",
            ci_id: "ci-switch",
            ci_name: "Access-SW-01",
            metric_id: "metric-latency",
            metric_name: "Latency",
            metric_protocol: "SNMP",
            status: "ACK",
            severity: "WARNING",
            message: "Latency over threshold",
            created_at: "2026-04-04T20:00:00.000Z",
            last_seen: "2026-04-04T20:00:00.000Z",
            ack: true,
            comments: [],
          },
        ]);
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    expect(await screen.findByLabelText("Layer 2 Switch technology icon")).toHaveTextContent("lan");
    expect(screen.getByText("Access-SW-01")).toBeInTheDocument();
    expect(screen.getByText("ACK")).toBeInTheDocument();
  });

  it("GIVEN event detail opens for a CI with category_icon_key WHEN the category strip renders THEN it shows the shared technology icon separate from severity", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") {
        return Promise.resolve([
          {
            id: "ci-detail-router",
            label: "Edge-Router-01",
            type: "Network",
            status: "OK",
            metadata: {},
            category: "Router",
            category_icon_key: "router",
            ip: "10.0.0.1",
            location: { lat: 40.4, long: -3.7 },
          },
        ]);
      }
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([{ name: "Router", icon_key: "router" }]);
      if (url === "/events?status=CONSOLE") {
        return Promise.resolve([
          {
            id: "evt-detail-router",
            ci_id: "ci-detail-router",
            ci_name: "Edge-Router-01",
            metric_id: "metric-cpu",
            metric_name: "CPU",
            metric_protocol: "SNMP",
            status: "OPEN",
            severity: "CRITICAL",
            message: "CPU over threshold",
            created_at: "2026-04-04T20:00:00.000Z",
            last_seen: "2026-04-04T20:00:00.000Z",
            ack: false,
            comments: [],
          },
        ]);
      }
      if (url === "/events/evt-detail-router") {
        return Promise.resolve({
          event: {
            id: "evt-detail-router",
            ci_ref: { id: "ci-detail-router", label: "Edge-Router-01" },
            metric_name: "CPU",
            metric_protocol: "SNMP",
            status: "OPEN",
            severity: "CRITICAL",
            message: "CPU over threshold",
            created_at: "2026-04-04T20:00:00.000Z",
            comments: [],
          },
          business_context: {
            source: "catalog",
            service_catalog: { category: "Router" },
          },
          itsm_context: {},
        });
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    expect(await screen.findByText("CPU over threshold")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));

    const categoryLabel = await screen.findByText("Categoría CI");
    const categoryStrip = categoryLabel.closest("div")?.parentElement;
    expect(categoryStrip).not.toBeNull();
    expect(
      within(categoryStrip as HTMLElement).getByLabelText("Router technology icon"),
    ).toHaveTextContent("router");
    expect(within(categoryStrip as HTMLElement).getByText("Router")).toBeInTheDocument();
    expect(screen.getAllByText("CRITICAL").length).toBeGreaterThan(0);
  });

  it("GIVEN event detail opens for a CI without category_icon_key WHEN the category strip renders THEN it falls back by category name", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") {
        return Promise.resolve([
          {
            id: "ci-detail-switch",
            label: "Access-SW-01",
            type: "Layer 2 Switch",
            status: "OK",
            metadata: {},
            category: "Layer 2 Switch",
            category_icon_key: null,
            ip: "10.0.0.2",
            location: { lat: 40.4, long: -3.7 },
          },
        ]);
      }
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([{ name: "Layer 2 Switch" }]);
      if (url === "/events?status=CONSOLE") {
        return Promise.resolve([
          {
            id: "evt-detail-switch",
            ci_id: "ci-detail-switch",
            ci_name: "Access-SW-01",
            metric_id: "metric-latency",
            metric_name: "Latency",
            metric_protocol: "SNMP",
            status: "ACK",
            severity: "WARNING",
            message: "Latency over threshold",
            created_at: "2026-04-04T20:00:00.000Z",
            last_seen: "2026-04-04T20:00:00.000Z",
            ack: true,
            comments: [],
          },
        ]);
      }
      if (url === "/events/evt-detail-switch") {
        return Promise.resolve({
          event: {
            id: "evt-detail-switch",
            ci_ref: { id: "ci-detail-switch", label: "Access-SW-01" },
            metric_name: "Latency",
            metric_protocol: "SNMP",
            status: "ACK",
            severity: "WARNING",
            message: "Latency over threshold",
            created_at: "2026-04-04T20:00:00.000Z",
            comments: [],
          },
          business_context: {
            source: "catalog",
            service_catalog: { category: "Layer 2 Switch" },
          },
          itsm_context: {},
        });
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    expect(await screen.findByText("Latency over threshold")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));

    const categoryLabel = await screen.findByText("Categoría CI");
    const categoryStrip = categoryLabel.closest("div")?.parentElement;
    expect(categoryStrip).not.toBeNull();
    expect(
      within(categoryStrip as HTMLElement).getByLabelText("Layer 2 Switch technology icon"),
    ).toHaveTextContent("lan");
    expect(within(categoryStrip as HTMLElement).getByText("Layer 2 Switch")).toBeInTheDocument();
    expect(screen.getAllByText("ACK").length).toBeGreaterThan(0);
  });

  it("GIVEN monitoring dashboard renders THEN it does not fetch or show the full availability report", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") return Promise.resolve([]);
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([]);
      if (url === "/events?status=CONSOLE") return Promise.resolve([]);
      if (url === "/events/availability-report") {
        throw new Error("Monitoring must not fetch availability analytics");
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    await waitFor(() => {
      expect(mockApiGet.mock.calls.some(([url]) => url === "/events?status=CONSOLE")).toBe(true);
    });
    expect(screen.queryByText("Availability Metrics")).not.toBeInTheDocument();
    expect(screen.queryByText("MTTR/MTBF by CI + event type")).not.toBeInTheDocument();
    expect(screen.queryByText("Active Down")).not.toBeInTheDocument();
    expect(mockApiGet.mock.calls.some(([url]) => url === "/events/availability-report")).toBe(
      false,
    );
  });

  it("GIVEN recovered events WHEN console feed loads THEN they stay visible without ACK action and are cleanable", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") {
        return Promise.resolve([
          {
            id: "ci-1",
            label: "Router-01",
            type: "INFRASTRUCTURE",
            status: "OK",
            metadata: {},
            category: "NETWORK",
            ip: "10.0.0.1",
            location: { lat: 40.4, long: -3.7 },
            location_name: "Madrid HQ",
          },
        ]);
      }
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([{ name: "NETWORK" }]);
      if (url === "/events?status=CONSOLE") {
        return Promise.resolve([
          {
            id: "evt-recovered",
            ci_id: "ci-1",
            ci_name: "Router-01",
            metric_id: "metric-ping",
            metric_name: "Ping availability",
            metric_protocol: "ICMP",
            status: "RECOVERED",
            severity: "CRITICAL",
            message: "Host recovered",
            created_at: "2026-04-04T20:00:00.000Z",
            last_seen: "2026-04-04T20:05:00.000Z",
            ack: false,
            comments: [],
          },
        ]);
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    expect(await screen.findByText("Host recovered")).toBeInTheDocument();
    expect(screen.getByText("RECOVERED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ack" })).toBeNull();
    expect(screen.getByRole("button", { name: /Clean recovered \(1\)/i })).toBeInTheDocument();
  });

  it("GIVEN the module WHEN imported THEN has no reference to leaflet-ant-path", async () => {
    // Read the source file as text and assert the banned import is absent.
    // This is a static analysis guard that runs at test time.
    const fs = await import("fs");
    const path = await import("path");
    const filePath = path.resolve(process.cwd(), "components/MonitoringConsole.tsx");
    const source = fs.readFileSync(filePath, "utf-8");

    expect(source).not.toContain("leaflet-ant-path");
    expect(source).not.toContain("AntPath");
  });

  it("GIVEN the module WHEN imported THEN has no animate-ping or animate-pulse on map markers", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const filePath = path.resolve(process.cwd(), "components/MonitoringConsole.tsx");
    const source = fs.readFileSync(filePath, "utf-8");

    // These Tailwind classes caused the full-map red flash — must not appear
    // inside pathOptions of CircleMarker/Circle (map section)
    // We check that neither className: 'animate-ping' nor animate-pulse appears
    // in pathOptions objects (the map markers section)
    expect(source).not.toContain("className: 'animate-ping'");
    expect(source).not.toContain("className: 'animate-pulse'");
  });

  it("GIVEN polluted mixed-root+propagated feed WHEN the console renders THEN KPI counts exclude PROPAGATED rows (P2 root-only contract)", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") return Promise.resolve([]);
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([]);
      if (url === "/events?status=CONSOLE") {
        return Promise.resolve([
          {
            id: "evt-root-crit",
            ci_id: "ci-1",
            ci_name: "Router-01",
            metric_id: "m-cpu",
            metric_name: "CPU",
            metric_protocol: "SNMP",
            status: "OPEN",
            severity: "CRITICAL",
            message: "CPU overload",
            created_at: "2026-04-04T20:00:00.000Z",
            last_seen: "2026-04-04T20:00:00.000Z",
            ack: false,
            correlation_type: "ROOT",
            affected_count: 3,
          },
          {
            id: "evt-prop-noise",
            ci_id: "ci-1",
            ci_name: "Router-01",
            metric_id: "m-lat",
            metric_name: "Latency",
            metric_protocol: "SNMP",
            status: "OPEN",
            severity: "CRITICAL",
            message: "Propagated noise",
            created_at: "2026-04-04T20:00:00.000Z",
            last_seen: "2026-04-04T20:00:00.000Z",
            ack: false,
            correlation_type: "PROPAGATED",
          },
        ]);
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    // Both events render in the stream (the grouping engine still shows them).
    expect(await screen.findByText("CPU overload")).toBeInTheDocument();

    // KPI counts: only the ROOT event counts → 1 critical, 0 warning, 0 ack.
    const criticalCard = screen.getByText("Critical Events").closest("div");
    const warningCard = screen.getByText("Warnings").closest("div");
    const ackCard = screen.getByText("Acknowledged").closest("div");
    const totalCard = screen.getByText("Total Active").closest("div");
    expect(criticalCard?.textContent).toContain("1");
    expect(warningCard?.textContent).toContain("0");
    expect(ackCard?.textContent).toContain("0");
    expect(totalCard?.textContent).toContain("1");

    // Sub-label reports the blast radius from the ROOT event only.
    expect(screen.getByTestId("stat-sublabel-total-active")).toHaveTextContent("affecting 3 CIs");
  });

  it("GIVEN mixed event states WHEN KPI cards are clicked THEN stream auto-filters and sorts by severity then open age", async () => {
    const { default: MonitoringConsole } = await import("../MonitoringConsole");

    mockApiGet.mockImplementation((url: string) => {
      if (url === "/nodes") {
        return Promise.resolve([
          {
            id: "ci-1",
            label: "Router-01",
            type: "INFRASTRUCTURE",
            status: "OK",
            metadata: {},
            category: "NETWORK",
            ip: "10.0.0.1",
            location: { lat: 40.4, long: -3.7 },
            location_name: "Madrid HQ",
          },
        ]);
      }
      if (url === "/links") return Promise.resolve([]);
      if (url === "/categories") return Promise.resolve([{ name: "NETWORK" }]);
      if (url === "/events?status=CONSOLE") {
        return Promise.resolve([
          {
            id: "evt-older-warning",
            ci_id: "ci-1",
            ci_name: "Router-01",
            metric_id: "metric-warning",
            metric_name: "Latency",
            metric_protocol: "SNMP",
            status: "OPEN",
            severity: "WARNING",
            message: "Older warning",
            created_at: "2026-04-04T19:00:00.000Z",
            last_seen: "2026-04-04T19:00:00.000Z",
            ack: false,
            comments: [],
          },
          {
            id: "evt-older-critical",
            ci_id: "ci-1",
            ci_name: "Router-01",
            metric_id: "metric-critical-older",
            metric_name: "CPU",
            metric_protocol: "SNMP",
            status: "OPEN",
            severity: "CRITICAL",
            message: "Older critical",
            created_at: "2026-04-04T18:00:00.000Z",
            last_seen: "2026-04-04T18:00:00.000Z",
            ack: false,
            comments: [],
          },
          {
            id: "evt-newer-critical",
            ci_id: "ci-1",
            ci_name: "Router-01",
            metric_id: "metric-critical",
            metric_name: "CPU",
            metric_protocol: "SNMP",
            status: "OPEN",
            severity: "CRITICAL",
            message: "Newest critical",
            created_at: "2026-04-04T21:00:00.000Z",
            last_seen: "2026-04-04T21:00:00.000Z",
            ack: false,
            comments: [],
          },
          {
            id: "evt-ack",
            ci_id: "ci-1",
            ci_name: "Router-01",
            metric_id: "metric-ack",
            metric_name: "Power",
            metric_protocol: "SNMP",
            status: "ACK",
            severity: "CRITICAL",
            message: "Acknowledged event",
            created_at: "2026-04-04T20:00:00.000Z",
            last_seen: "2026-04-04T20:00:00.000Z",
            ack: true,
            ack_by: "admin",
            comments: [],
          },
        ]);
      }
      return Promise.resolve([]);
    });

    renderWithQueryClient(<MonitoringConsole />);

    expect(await screen.findByText("Newest critical")).toBeInTheDocument();
    expect(screen.getByText("Older critical")).toBeInTheDocument();
    expect(screen.getByText("Older warning")).toBeInTheDocument();
    expect(screen.getByText("Acknowledged event")).toBeInTheDocument();

    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Older critical");
    expect(rows[2]).toHaveTextContent("Newest critical");

    fireEvent.click(screen.getByRole("button", { name: /Warnings/i }));
    expect(screen.getByText("Older warning")).toBeInTheDocument();
    expect(screen.queryByText("Newest critical")).toBeNull();
    expect(screen.queryByText("Older critical")).toBeNull();
    expect(screen.queryByText("Acknowledged event")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Acknowledged/i }));
    expect(screen.getByText("Acknowledged event")).toBeInTheDocument();
    expect(screen.queryByText("Older warning")).toBeNull();
  });
});
