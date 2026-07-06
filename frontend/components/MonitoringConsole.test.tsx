/* eslint-disable @typescript-eslint/no-explicit-any */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { encodeTunnelLinkId } from "../utils/tunnelVisuals";
import MonitoringConsole from "./MonitoringConsole";

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
  TileLayer: () => <div data-testid="tile-layer" />,
  Polyline: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="polyline">{children}</div>
  ),
  CircleMarker: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="circle-marker">{children}</div>
  ),
  Popup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({
    on: vi.fn(),
    off: vi.fn(),
    fitBounds: vi.fn(),
    setView: vi.fn(),
  }),
}));

const visibleTunnelLink = {
  id: "visible-tunnel",
  source: "site-a",
  target: "site-b",
  relationship: "CONNECTS_TO" as const,
  medium: "vpn" as const,
  tunnel_link_id: "arbitrary",
};

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
  {
    id: "site-b",
    label: "Site B",
    type: "Network",
    status: "OK",
    metadata: {},
    category: "Network",
    location: { lat: 21, long: -101 },
  },
  {
    id: "hidden",
    label: "Hidden",
    type: "Server",
    status: "OK",
    metadata: {},
    category: "Server",
    location: { lat: 22, long: -102 },
  },
];

describe("MonitoringConsole tunnel health visuals", () => {
  beforeEach(() => {
    mockUseVisibleTunnelHealth.mockReset();
    mockUseMonitoringConsoleData.mockReturnValue({
      nodes,
      links: [
        visibleTunnelLink,
        {
          id: "filtered-tunnel",
          source: "site-a",
          target: "hidden",
          relationship: "CONNECTS_TO",
          medium: "satellite",
          tunnel_link_id: "hidden",
        },
      ],
      events: [],
      categories: ["Network", "Server"],
    });
  });

  it("uses the encoded tunnel link key and polls only links visible after category filtering", async () => {
    mockUseVisibleTunnelHealth.mockReturnValue({
      visualByLinkId: {
        [encodeTunnelLinkId(visibleTunnelLink)]: {
          mediumLabel: "VPN tunnel",
          iconKey: "vpn_tunnel",
          authorityText: "UNKNOWN",
          state: "unknown",
          warning: "missing_public_ip",
          stale: false,
          errorKind: undefined,
          tooltipRows: [
            { label: "Medium", value: "VPN tunnel" },
            { label: "Authority", value: "UNKNOWN" },
            { label: "ICMP", value: "Missing public IP" },
          ],
        },
      },
      pollingDisabled: false,
      skippedOverCap: 0,
      suppressedCooldown: 0,
    });

    render(<MonitoringConsole />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "Network" } });
    fireEvent.click(screen.getByRole("button", { name: "Geo View" }));

    await waitFor(() => {
      const visibleLinks = mockUseVisibleTunnelHealth.mock.calls.at(-1)?.[0] ?? [];
      expect(visibleLinks.map((link: any) => link.id)).toEqual(["visible-tunnel"]);
    });
    expect(screen.getAllByText("VPN tunnel")).toHaveLength(2);
    expect(screen.getAllByText("UNKNOWN")).toHaveLength(2);
    expect(screen.getByText("Missing public IP")).toBeInTheDocument();
  });

  it("keeps UP authority with warning and shows kill-switch no-live-health context", () => {
    mockUseVisibleTunnelHealth.mockReturnValue({
      visualByLinkId: {
        [encodeTunnelLinkId(visibleTunnelLink)]: {
          mediumLabel: "VPN tunnel",
          iconKey: "vpn_tunnel",
          authorityText: "UP",
          state: "up",
          warning: "icmp_failed",
          stale: false,
          errorKind: "network",
          tooltipRows: [
            { label: "Medium", value: "VPN tunnel" },
            { label: "Authority", value: "UP" },
            { label: "ICMP", value: "ICMP failed" },
            { label: "Health", value: "Unavailable: network" },
          ],
        },
      },
      pollingDisabled: true,
      skippedOverCap: 0,
      suppressedCooldown: 0,
    });

    render(<MonitoringConsole />);
    fireEvent.click(screen.getByRole("button", { name: "Geo View" }));

    expect(screen.getByText("Live tunnel health disabled")).toBeInTheDocument();
    expect(screen.getAllByText("UP")).toHaveLength(2);
    expect(screen.getByText("ICMP failed")).toBeInTheDocument();
    expect(screen.getByText("Unavailable: network")).toBeInTheDocument();
    expect(screen.queryByText("DEGRADED")).not.toBeInTheDocument();
  });
});
