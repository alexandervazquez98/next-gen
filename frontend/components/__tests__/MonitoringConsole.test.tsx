/**
 * MonitoringConsole.test.tsx
 *
 * Unit tests for rankCIs pure function.
 * Tests ranking order, top-n cap, and stable sort for equal scores.
 */

import { describe, it, expect, vi } from "vitest";
import { rankCIs } from "../MonitoringConsole";
import { GraphNode, Event } from "../../types";

// ---------------------------------------------------------------------------
// P2 REQ-005 / SCN-008: shared mocks for the KPI root filter test
// ---------------------------------------------------------------------------

const { mockApi } = vi.hoisted(() => ({
  mockApi: vi.fn(),
}));

vi.mock("../../services/api", () => ({
  api: { get: mockApi, post: vi.fn() },
}));
vi.mock("../../hooks/useEventCorrelation", () => ({
  useEventCorrelation: (events: any[]) => events,
}));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: any) => <div>{children}</div>,
  TileLayer: () => null,
  Polyline: () => null,
  useMap: () => ({}),
}));
vi.mock("leaflet", () => ({
  default: {
    icon: () => ({}),
    Marker: { prototype: { options: { icon: null } } },
    latLngBounds: () => ({ isValid: () => true }),
  },
  icon: () => ({}),
  Marker: { prototype: { options: { icon: null } } },
  latLngBounds: () => ({}),
}));
vi.mock("leaflet/dist/leaflet.css", () => ({}));
vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({
    user: {
      username: "admin",
      role: "ADMIN",
      permissions: [],
      tier: "T3",
      allowed_locations: [],
    },
    hasPermission: () => true,
    isAuthenticated: true,
    token: "t",
    login: () => undefined,
    logout: () => undefined,
  }),
}));

describe("rankCIs", () => {
  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------
  const makeNode = (
    overrides: Partial<GraphNode> & { events?: Event[] },
  ): GraphNode & { events: Event[] } => ({
    id: "ci-1",
    label: "Test Node",
    type: "INFRASTRUCTURE",
    status: "OK",
    metadata: {},
    category: "COMPUTE",
    events: [],
    ...overrides,
  });

  const makeEvent = (overrides: Partial<Event>): Event => ({
    id: "evt-1",
    ci_id: "ci-1",
    ci_name: "Test CI",
    metric_id: "metric-1",
    metric_name: "CPU",
    status: "OPEN",
    severity: "CRITICAL",
    message: "Test event",
    created_at: "2024-01-01T00:00:00Z",
    last_seen: "2024-01-01T00:00:00Z",
    ack: false,
    ...overrides,
  });

  // -------------------------------------------------------------------------
  // Task 4.1: Ranking order (higher weighted severity = higher rank)
  // -------------------------------------------------------------------------
  describe("ranking order", () => {
    it("GIVEN nodes with CRITICAL and WARNING events WHEN ranked THEN CRITICAL nodes rank higher", () => {
      const nodes = [
        makeNode({
          id: "ci-warning",
          label: "Warning Node",
          events: [makeEvent({ severity: "WARNING", id: "evt-warn" })],
        }),
        makeNode({
          id: "ci-critical",
          label: "Critical Node",
          events: [makeEvent({ severity: "CRITICAL", id: "evt-crit" })],
        }),
        makeNode({ id: "ci-ok", label: "OK Node", events: [] }),
      ];

      const result = rankCIs(nodes, 50);

      // CRITICAL weight=3, WARNING weight=2, INFO weight=1
      expect(result[0].id).toBe("ci-critical");
      expect(result[1].id).toBe("ci-warning");
      expect(result[2].id).toBe("ci-ok");
    });

    it("GIVEN nodes with multiple events of same severity WHEN ranked THEN total event count determines rank", () => {
      const nodes = [
        makeNode({
          id: "ci-single",
          label: "Single",
          events: [makeEvent({ severity: "CRITICAL", id: "evt-1" })],
        }),
        makeNode({
          id: "ci-triple",
          label: "Triple",
          events: [
            makeEvent({ severity: "CRITICAL", id: "evt-2a" }),
            makeEvent({ severity: "CRITICAL", id: "evt-2b" }),
            makeEvent({ severity: "CRITICAL", id: "evt-2c" }),
          ],
        }),
      ];

      const result = rankCIs(nodes, 50);

      // ci-triple has score=9 (3*3), ci-single has score=3 (1*3)
      expect(result[0].id).toBe("ci-triple");
      expect(result[1].id).toBe("ci-single");
    });

    it("GIVEN mixed severity events per node WHEN ranked THEN weighted sum determines rank", () => {
      const nodes = [
        makeNode({
          id: "ci-2crit",
          label: "2 Critical",
          events: [
            makeEvent({ severity: "CRITICAL", id: "evt-a" }),
            makeEvent({ severity: "CRITICAL", id: "evt-b" }),
          ],
        }),
        makeNode({
          id: "ci-3warn",
          label: "3 Warning",
          events: [
            makeEvent({ severity: "WARNING", id: "evt-c" }),
            makeEvent({ severity: "WARNING", id: "evt-d" }),
            makeEvent({ severity: "WARNING", id: "evt-e" }),
          ],
        }),
      ];

      const result = rankCIs(nodes, 50);

      // 2*CRITICAL(3) = 6, 3*WARNING(2) = 6 — equal scores, stable sort keeps original order
      expect(result[0].id).toBe("ci-2crit");
      expect(result[1].id).toBe("ci-3warn");
    });
  });

  // -------------------------------------------------------------------------
  // Task 4.2: Top-n cap (returns exactly n items when input > n)
  // -------------------------------------------------------------------------
  describe("top-n cap", () => {
    it("GIVEN 10 nodes WHEN top-n=3 THEN returns exactly 3 nodes", () => {
      const nodes = Array.from({ length: 10 }, (_, i) =>
        makeNode({
          id: `ci-${i}`,
          label: `Node ${i}`,
          events: [makeEvent({ severity: "CRITICAL", id: `evt-${i}` })],
        }),
      );

      const result = rankCIs(nodes, 3);

      expect(result).toHaveLength(3);
      expect(result[0].id).toBe("ci-0");
      expect(result[1].id).toBe("ci-1");
      expect(result[2].id).toBe("ci-2");
    });

    it("GIVEN fewer nodes than n WHEN ranked THEN returns all nodes", () => {
      const nodes = [
        makeNode({ id: "ci-1", events: [makeEvent({ severity: "WARNING" })] }),
        makeNode({ id: "ci-2", events: [makeEvent({ severity: "CRITICAL" })] }),
      ];

      const result = rankCIs(nodes, 50);

      expect(result).toHaveLength(2);
    });

    it("GIVEN empty array WHEN ranked THEN returns empty array", () => {
      const result = rankCIs([], 50);
      expect(result).toHaveLength(0);
    });

    it("GIVEN n=0 WHEN ranked THEN returns empty array", () => {
      const nodes = [makeNode({ id: "ci-1", events: [makeEvent({ severity: "CRITICAL" })] })];

      const result = rankCIs(nodes, 0);

      expect(result).toHaveLength(0);
    });
  });

  // -------------------------------------------------------------------------
  // Task 4.3: Stable sort for equal scores (original order preserved)
  // -------------------------------------------------------------------------
  describe("stable sort for equal scores", () => {
    it("GIVEN nodes with identical scores WHEN ranked THEN original order is preserved", () => {
      const nodes = [
        makeNode({
          id: "ci-first",
          label: "First",
          events: [makeEvent({ severity: "INFO", id: "evt-1" })],
        }),
        makeNode({
          id: "ci-second",
          label: "Second",
          events: [makeEvent({ severity: "INFO", id: "evt-2" })],
        }),
        makeNode({
          id: "ci-third",
          label: "Third",
          events: [makeEvent({ severity: "INFO", id: "evt-3" })],
        }),
      ];

      const result = rankCIs(nodes, 50);

      // All INFO weight=1, so all scores=1 — stable sort preserves order
      expect(result[0].id).toBe("ci-first");
      expect(result[1].id).toBe("ci-second");
      expect(result[2].id).toBe("ci-third");
    });

    it("GIVEN nodes with equal weighted scores WHEN ranked THEN earlier node wins", () => {
      // Node with 2 WARNING (score=4) vs 4 INFO (score=4)
      const nodes = [
        makeNode({
          id: "ci-2warn",
          label: "2W",
          events: [
            makeEvent({ severity: "WARNING", id: "evt-a" }),
            makeEvent({ severity: "WARNING", id: "evt-b" }),
          ],
        }),
        makeNode({
          id: "ci-4info",
          label: "4I",
          events: [
            makeEvent({ severity: "INFO", id: "evt-c" }),
            makeEvent({ severity: "INFO", id: "evt-d" }),
            makeEvent({ severity: "INFO", id: "evt-e" }),
            makeEvent({ severity: "INFO", id: "evt-f" }),
          ],
        }),
      ];

      const result = rankCIs(nodes, 50);

      // Both score=4, ci-2warn comes first in original array
      expect(result[0].id).toBe("ci-2warn");
      expect(result[1].id).toBe("ci-4info");
    });
  });

  // ---------------------------------------------------------------------------
  // P2 REQ-005 / SCN-008: KPI cards count ROOT events only and render the
  // "affecting N CIs" sub-label sourced from `affected_count`.
  // ---------------------------------------------------------------------------

  describe("KPI root filter + sub-label (SCN-008)", () => {
    it("counts only ROOT events and renders affecting-N-CIs sub-label", async () => {
      const React = await import("react");
      const { render, screen, waitFor } = await import("@testing-library/react");
      const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");

      mockApi.mockImplementation((url: string) => {
        if (url === "/nodes") return Promise.resolve([]);
        if (url === "/links") return Promise.resolve([]);
        if (url === "/categories") return Promise.resolve([]);
        if (url === "/events?status=CONSOLE") {
          return Promise.resolve([
            {
              id: "evt-root-1",
              ci_id: "ci-1",
              ci_name: "Router-01",
              metric_id: "cpu",
              metric_name: "CPU",
              status: "OPEN",
              severity: "CRITICAL",
              message: "CPU high",
              created_at: "2026-04-04T20:00:00.000Z",
              last_seen: "2026-04-04T20:00:00.000Z",
              ack: false,
              correlation_type: "ROOT",
              affected_count: 3,
            },
            {
              id: "evt-root-2",
              ci_id: "ci-2",
              ci_name: "Router-02",
              metric_id: "mem",
              metric_name: "Memory",
              status: "OPEN",
              severity: "WARNING",
              message: "Memory high",
              created_at: "2026-04-04T20:00:00.000Z",
              last_seen: "2026-04-04T20:00:00.000Z",
              ack: false,
              correlation_type: "ROOT",
              affected_count: 2,
            },
            {
              id: "evt-prop",
              ci_id: "ci-3",
              ci_name: "Router-03",
              metric_id: "latency",
              metric_name: "Latency",
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

      const { default: MonitoringConsole } = await import("../MonitoringConsole");

      const client = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      });

      render(
        React.createElement(
          QueryClientProvider,
          { client },
          React.createElement(MonitoringConsole),
        ),
      );

      await waitFor(() => {
        expect(screen.getByText("CPU high")).toBeInTheDocument();
      });

      // Sub-label sums `affected_count` over roots: 3 + 2 = 5.
      const subLabel = await screen.findByTestId("stat-sublabel-total-active");
      expect(subLabel.textContent).toBe("affecting 5 CIs");

      // Total KPI counts ROOT rows only (2), not 3 (PROPAGATED excluded).
      const totalCard = screen.getByText("Total Active").closest("div");
      expect(totalCard?.textContent).toContain("2");
    });
  });
});
