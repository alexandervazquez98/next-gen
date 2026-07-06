import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TopologyViewer from "./TopologyViewer";
import type { GraphNode } from "../types";

const nodes: GraphNode[] = [
  { id: "root", label: "Root Router", type: "Network", status: "OK", metadata: {} },
  { id: "edge", label: "Edge Router", type: "Network", status: "OK", metadata: {} },
];

describe("TopologyViewer tunnel visual contract", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders shared medium, icon, status, warning, and tooltip rows for relevant tunnel links", () => {
    render(
      <TopologyViewer
        rootId="root"
        nodes={nodes}
        links={[
          {
            id: "tunnel-root-edge",
            source: "root",
            target: "edge",
            relationship: "DEPENDS_ON",
            medium: "sd_wan",
            tunnel_health: {
              link_id: "tunnel-root-edge",
              source: "root",
              target: "edge",
              relationship: "DEPENDS_ON",
              medium: "sd_wan",
              status: "UP",
              authority: { state: "UP" },
              icmp: { available: false, reason: "icmp_failed" },
            },
          },
        ]}
      />,
    );

    expect(screen.getAllByText("SD-WAN tunnel")).toHaveLength(2);
    expect(screen.getByRole("img", { name: "SD-WAN Tunnel technology icon" })).toBeInTheDocument();
    expect(screen.getAllByText("UP")).toHaveLength(2);
    expect(screen.getByText("ICMP failed")).toBeInTheDocument();
    expect(screen.queryByText("DEGRADED")).not.toBeInTheDocument();
  });
});
