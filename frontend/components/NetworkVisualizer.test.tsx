/* eslint-disable @typescript-eslint/no-explicit-any */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { encodeTunnelLinkId } from "../utils/tunnelVisuals";
import NetworkVisualizer from "./NetworkVisualizer";

const { mockUseVisibleTunnelHealth } = vi.hoisted(() => ({
  mockUseVisibleTunnelHealth: vi.fn(),
}));

vi.mock("../hooks/queries/useVisibleTunnelHealth", () => ({
  useVisibleTunnelHealth: mockUseVisibleTunnelHealth,
}));

vi.mock("react-force-graph-3d", async () => {
  const React = await vi.importActual<typeof import("react")>("react");

  return {
    default: React.forwardRef((props: any, ref) => {
      React.useImperativeHandle(ref, () => ({
        d3Force: () => ({
          strength: vi.fn(),
          distance: vi.fn(),
        }),
        zoomToFit: vi.fn(),
      }));

      return (
        <div data-testid="force-graph">
          <div data-testid="link-count">{props.graphData.links.length}</div>
          {props.graphData.nodes.map((node: any) => (
            <div key={node.id} data-testid={`node-color-${node.id}`}>
              {props.nodeColor(node)}
            </div>
          ))}
        </div>
      );
    }),
  };
});

const graphPayload = {
  nodes: [
    {
      id: "router-1",
      label: "Router 1",
      type: "CI",
      status: "CRITICAL",
      category: "Network",
      category_icon_key: "router",
    },
    {
      id: "switch-1",
      label: "Switch 1",
      type: "CI",
      status: "ACTIVE",
      category: "Layer 2 switch",
    },
  ],
  links: [],
};

describe("NetworkVisualizer technology icons", () => {
  beforeEach(() => {
    mockUseVisibleTunnelHealth.mockReturnValue({ visualByLinkId: {}, pollingDisabled: false });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => graphPayload,
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the shared technology icon from category_icon_key while keeping status color separate", async () => {
    render(<NetworkVisualizer />);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/graph/full"));
    fireEvent.click(screen.getByRole("button", { name: "SHOW INFRASTRUCTURE (CIs)" }));

    const icon = await screen.findByRole("img", { name: "Router technology icon" });

    expect(icon).toHaveTextContent("router");
    expect(icon).not.toHaveTextContent("CRITICAL");
    expect(screen.getByTestId("node-color-router-1")).toHaveTextContent("#ff0055");
  });

  it("falls back to category-derived technology icon when no explicit icon key exists", async () => {
    render(<NetworkVisualizer />);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/graph/full"));
    fireEvent.click(screen.getByRole("button", { name: "SHOW INFRASTRUCTURE (CIs)" }));

    const icon = await screen.findByRole("img", { name: "Layer 2 Switch technology icon" });

    expect(icon).toHaveTextContent("lan");
    expect(screen.getByText("Switch 1")).toBeInTheDocument();
  });
});

describe("NetworkVisualizer tunnel health visuals", () => {
  beforeEach(() => {
    mockUseVisibleTunnelHealth.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the encoded tunnel link key for visible live health lookup", async () => {
    const visibleTunnelLink = {
      id: "tunnel-visible",
      source: "site-a",
      target: "site-b",
      relationship: "CONNECTS_TO" as const,
      medium: "vpn" as const,
      tunnel_link_id: "arbitrary",
    };

    mockUseVisibleTunnelHealth.mockReturnValue({
      visualByLinkId: {
        [encodeTunnelLinkId(visibleTunnelLink)]: {
          mediumLabel: "VPN tunnel",
          iconKey: "vpn_tunnel",
          authorityText: "UNKNOWN",
          state: "unknown",
          warning: "missing_public_ip",
          stale: false,
          tooltipRows: [
            { label: "Medium", value: "VPN tunnel" },
            { label: "Authority", value: "UNKNOWN" },
            { label: "ICMP", value: "Missing public IP" },
          ],
          healthAffectsIcon: false,
        },
      },
      pollingDisabled: false,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          nodes: [
            { id: "site-a", label: "Site A", type: "Category", status: "OK", metadata: {} },
            { id: "site-b", label: "Site B", type: "Category", status: "OK", metadata: {} },
            { id: "ci-hidden", label: "Hidden CI", type: "CI", status: "ACTIVE", metadata: {} },
          ],
          links: [
            visibleTunnelLink,
            {
              id: "tunnel-hidden",
              source: "site-a",
              target: "ci-hidden",
              relationship: "CONNECTS_TO",
              medium: "vpn",
              tunnel_link_id: "hidden",
            },
            { id: "non-tunnel", source: "site-a", target: "site-b", relationship: "DEPENDS_ON" },
          ],
        }),
      }),
    );

    render(<NetworkVisualizer />);

    expect(await screen.findAllByText("VPN tunnel")).toHaveLength(2);

    expect(screen.getByTestId("link-count")).toHaveTextContent("2");
    const visibleLinks = mockUseVisibleTunnelHealth.mock.calls.at(-1)?.[0] ?? [];
    expect(visibleLinks.map((link: any) => link.id)).toEqual(["tunnel-visible", "non-tunnel"]);
    expect(screen.getAllByText("UNKNOWN")).toHaveLength(2);
    expect(screen.getByText("Missing public IP")).toBeInTheDocument();
    expect(screen.queryByText("DEGRADED")).not.toBeInTheDocument();
  });

  it("keeps UP authority while rendering warning and unavailable-health context", async () => {
    const visibleTunnelLink = {
      id: "tunnel-visible",
      source: "site-a",
      target: "site-b",
      relationship: "CONNECTS_TO" as const,
      medium: "sd_wan" as const,
      tunnel_link_id: "tunnel1",
    };

    mockUseVisibleTunnelHealth.mockReturnValue({
      visualByLinkId: {
        [encodeTunnelLinkId(visibleTunnelLink)]: {
          mediumLabel: "SD-WAN tunnel",
          iconKey: "sd_wan_tunnel",
          authorityText: "UP",
          state: "up",
          warning: "icmp_failed",
          stale: true,
          errorKind: "server",
          tooltipRows: [
            { label: "Medium", value: "SD-WAN tunnel" },
            { label: "Authority", value: "UP" },
            { label: "ICMP", value: "ICMP failed" },
            { label: "Health", value: "Unavailable: server" },
          ],
          healthAffectsIcon: false,
        },
      },
      pollingDisabled: false,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          nodes: [
            { id: "site-a", label: "Site A", type: "Category", status: "OK", metadata: {} },
            { id: "site-b", label: "Site B", type: "Category", status: "OK", metadata: {} },
          ],
          links: [visibleTunnelLink],
        }),
      }),
    );

    render(<NetworkVisualizer />);

    expect(await screen.findAllByText("SD-WAN tunnel")).toHaveLength(2);
    expect(screen.getAllByText("UP")).toHaveLength(2);
    expect(screen.getByText("ICMP failed")).toBeInTheDocument();
    expect(screen.getByText("Unavailable: server")).toBeInTheDocument();
    expect(screen.queryByText("DOWN")).not.toBeInTheDocument();
  });

  it("shows kill-switch no-live-health context without claiming live status", async () => {
    mockUseVisibleTunnelHealth.mockReturnValue({ visualByLinkId: {}, pollingDisabled: true });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({
          nodes: [
            { id: "site-a", label: "Site A", type: "Category", status: "OK", metadata: {} },
            { id: "site-b", label: "Site B", type: "Category", status: "OK", metadata: {} },
          ],
          links: [
            {
              id: "tunnel-visible",
              source: "site-a",
              target: "site-b",
              relationship: "CONNECTS_TO",
              medium: "satellite",
            },
          ],
        }),
      }),
    );

    render(<NetworkVisualizer />);

    expect(await screen.findByText("Live tunnel health disabled")).toBeInTheDocument();
    expect(screen.getAllByText("Satellite link")).toHaveLength(2);
    expect(screen.getAllByText("UNKNOWN")).toHaveLength(2);
  });
});
