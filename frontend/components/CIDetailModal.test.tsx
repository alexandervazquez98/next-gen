import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CIDetailModal from "./CIDetailModal";
import type { GraphNode } from "../types";

vi.mock("./MetricHistoryChart", () => ({
  default: () => <div>Metric history chart</div>,
}));

const makeNode = (overrides: Partial<GraphNode> = {}): GraphNode => ({
  id: overrides.id ?? "ci-1",
  label: overrides.label ?? "Core Router",
  type: overrides.type ?? "Infrastructure",
  status: overrides.status ?? "ACTIVE",
  metadata: overrides.metadata ?? {},
  category: overrides.category ?? "Network",
  category_icon_key: overrides.category_icon_key,
  ip: overrides.ip ?? "10.0.0.1",
  metrics: overrides.metrics ?? [],
  ...overrides,
});

describe("CIDetailModal technology icons", () => {
  it("renders the explicit category technology icon while keeping operational status separate", () => {
    render(
      <CIDetailModal
        node={makeNode({
          status: "EXCEPTION",
          category: "Network",
          category_icon_key: "router",
        })}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("img", { name: "Router technology icon" })).toBeInTheDocument();
    expect(screen.getByText("EXCEPTION STATUS")).toBeInTheDocument();
    expect(screen.getByText("Network")).toBeInTheDocument();
  });

  it("falls back to category-name icon resolution when icon metadata is missing", () => {
    render(
      <CIDetailModal
        node={makeNode({
          label: "Access Switch",
          category: "Layer 2 Switch",
          category_icon_key: null,
        })}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("img", { name: "Layer 2 Switch technology icon" })).toBeInTheDocument();
    expect(screen.getByText("Layer 2 Switch")).toBeInTheDocument();
  });
});

describe("CIDetailModal tunnel topology context", () => {
  it("renders scoped public-IP fallback and tunnel topology context through shared visual rows", () => {
    render(
      <CIDetailModal
        node={makeNode({
          public_ip: null,
          metadata: {
            public_ip: "203.0.113.20",
            topology_links: [
              {
                source: "ci-1",
                target: "edge-1",
                relationship: "CONNECTS_TO",
                medium: "satellite",
                tunnel_health: {
                  link_id: "ci-edge",
                  source: "ci-1",
                  target: "edge-1",
                  relationship: "CONNECTS_TO",
                  medium: "satellite",
                  status: "UP",
                  authority: { state: "UP" },
                  icmp: { available: false, reason: "icmp_failed" },
                },
              },
            ],
          },
        })}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Public IP")).toBeInTheDocument();
    expect(screen.getByText("203.0.113.20")).toBeInTheDocument();
    expect(screen.getByText("Satellite link")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Satellite Link technology icon" })).toBeInTheDocument();
    expect(screen.getByText("UP")).toBeInTheDocument();
    expect(screen.getByText("ICMP failed")).toBeInTheDocument();
    expect(screen.queryByText("DEGRADED")).not.toBeInTheDocument();
  });
});
