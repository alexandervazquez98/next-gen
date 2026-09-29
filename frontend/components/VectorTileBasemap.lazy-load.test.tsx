/**
 * VectorTileBasemap.lazy-load.test.tsx
 *
 * Verifies that the vector-tile basemap module — and therefore `maplibre-gl`,
 * a ~1 MB WebGL renderer — is not loaded until the Geo View tab is activated.
 *
 * This is a behavioral test. It observes WHEN the module is requested by the
 * module graph, which is the thing the change actually alters.
 *
 * It deliberately does NOT mock `maplibre-gl` itself. `VectorTileBasemap.tsx`
 * never imports `maplibre-gl` directly — it imports `@maplibre/maplibre-gl-leaflet`,
 * which pulls maplibre in transitively. Mocking `maplibre-gl` while also mocking
 * the leaflet binding severs that chain, so the flag stays false whether the
 * import is static or lazy. Such a test passes against unimplemented code and
 * proves nothing. This file mocks the basemap module itself so the assertion has
 * real discriminating power: it FAILS against a static import.
 */
import React from "react";
import { fireEvent, render, act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Flipped by the module factory below the moment ./VectorTileBasemap is
 * requested. Declared through vi.hoisted because vi.mock factories are
 * hoisted above ordinary top-level declarations — a plain `let` would throw
 * "Cannot access before initialization" the moment the factory runs.
 */
const basemap = vi.hoisted(() => ({ requested: false }));

vi.mock("./VectorTileBasemap", () => {
  basemap.requested = true;
  return {
    __esModule: true,
    VectorTileBasemap: () => null,
    default: () => null,
    OPENFREEMAP_POSITRON_STYLE_URL: "https://tiles.openfreemap.org/styles/positron",
  };
});

const { mockUseMonitoringConsoleData, mockUseVisibleTunnelHealth } = vi.hoisted(() => ({
  mockUseMonitoringConsoleData: vi.fn(),
  mockUseVisibleTunnelHealth: vi.fn(),
}));

vi.mock("../hooks/queries/useMonitoringConsoleData", () => ({
  useMonitoringConsoleData: mockUseMonitoringConsoleData,
}));

vi.mock("../hooks/queries/useVisibleTunnelHealth", () => ({
  useVisibleTunnelHealth: mockUseVisibleTunnelHealth,
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    user: { username: "operator", tier: "T1" },
    hasPermission: () => true,
  }),
}));

vi.mock("../hooks/queries/useEventMutations", () => ({
  useEventMutations: () => ({
    ackEvent: vi.fn(),
    commentEvent: vi.fn(),
    closeEvent: vi.fn(),
    takeEvent: vi.fn(),
    usePruneRecovered: () => ({
      isComplete: false,
      isStreaming: false,
      isError: false,
      progress: null,
      errorMessage: null,
      start: vi.fn(),
    }),
  }),
}));

vi.mock("../hooks/queries/useEventDetailQuery", () => ({
  useEventDetailQuery: () => ({
    data: undefined,
    isSuccess: false,
    isError: false,
    isLoading: false,
  }),
}));

vi.mock("../hooks/queries/useRelatedEventsQuery", () => ({
  useRelatedEventsQuery: () => ({ data: [] }),
}));

vi.mock("../hooks/useEventCorrelation", () => ({
  useEventCorrelation: (events: unknown[]) => events,
}));

vi.mock("../hooks/useSmartCulling", () => ({
  useSmartCulling: (nodes: unknown[]) => ({ culledNodes: nodes, isActive: false }),
}));

vi.mock("../hooks/useMapClustering", () => ({
  useMapClustering: () => ({
    clusters: [],
    enabled: false,
    toggleClustering: vi.fn(),
    expandedClusterId: null,
    expandCluster: vi.fn(),
    collapseCluster: vi.fn(),
  }),
}));

vi.mock("leaflet", () => ({
  default: {
    icon: vi.fn(() => ({})),
    Marker: { prototype: { options: {} } },
    latLngBounds: vi.fn(() => ({})),
  },
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="map">{children}</div>
  ),
  Polyline: () => <div data-testid="polyline" />,
  CircleMarker: () => <div data-testid="circle-marker" />,
  Popup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({
    on: vi.fn(),
    off: vi.fn(),
    fitBounds: vi.fn(),
    setView: vi.fn(),
    getBounds: vi.fn(() => ({
      getSouth: () => 0,
      getWest: () => 0,
      getNorth: () => 1,
      getEast: () => 1,
    })),
    removeLayer: vi.fn(),
  }),
}));

const nodes = [
  {
    id: "site-a",
    label: "Site A",
    type: "Network",
    status: "OK",
    metadata: {},
    category: "Network",
    location: { lat: 20, long: -100 },
  },
];

function activateGeoView(container: HTMLElement) {
  const buttons = Array.from(container.querySelectorAll("button"));
  const geoViewButton = buttons.find((btn) => btn.textContent?.includes("Geo View"));
  expect(geoViewButton, "Geo View tab button not found").toBeTruthy();
  fireEvent.click(geoViewButton!);
}

describe("VectorTileBasemap lazy-loading", () => {
  beforeEach(() => {
    basemap.requested = false;
    mockUseMonitoringConsoleData.mockReturnValue({
      nodes,
      links: [],
      events: [],
      categories: ["Network"],
    });
    mockUseVisibleTunnelHealth.mockReturnValue({
      visualByLinkId: {},
      pollingDisabled: false,
      skippedOverCap: 0,
      suppressedCooldown: false,
    });
  });

  it("does not request the basemap module while the Stream tab is active", async () => {
    // Reset the module registry so this test observes a FRESH import of
    // MonitoringConsole. Without this, a static import would have already run
    // the mock factory at file-load time and `beforeEach` would have wiped the
    // evidence — the assertion would pass against unimplemented code.
    vi.resetModules();
    basemap.requested = false;
    const { default: FreshConsole } = await import("./MonitoringConsole");

    render(<FreshConsole />);

    // DASHBOARD is the default view mode; the basemap is not rendered there,
    // so the module must not have been requested.
    expect(basemap.requested).toBe(false);
  });

  it("requests the basemap module once the Geo View tab is activated", async () => {
    vi.resetModules();
    basemap.requested = false;
    const { default: FreshConsole } = await import("./MonitoringConsole");

    const { container } = render(<FreshConsole />);

    expect(basemap.requested, "precondition: must not be loaded before activation").toBe(false);

    await act(async () => {
      activateGeoView(container);
    });

    await waitFor(() => {
      expect(basemap.requested).toBe(true);
    });
  });
});
