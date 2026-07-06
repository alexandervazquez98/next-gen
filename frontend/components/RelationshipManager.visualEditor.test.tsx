import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import RelationshipManager from "./RelationshipManager";

const { mockApiGet } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
}));

vi.mock("../services/api", () => ({
  api: {
    get: mockApiGet,
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("./TopologyViewer", () => ({ default: () => <div>Topology viewer</div> }));

describe("RelationshipManager visual editor entry point", () => {
  beforeEach(() => {
    mockApiGet.mockReset();
    mockApiGet.mockImplementation((endpoint: string) => {
      if (endpoint === "/nodes") return Promise.resolve([]);
      if (endpoint === "/categories") return Promise.resolve([]);
      if (endpoint === "/links") return Promise.resolve([]);
      return Promise.resolve([]);
    });
  });

  it("opens the visual editor as a dedicated new-tab route", async () => {
    render(
      <MemoryRouter>
        <RelationshipManager onRefresh={vi.fn()} />
      </MemoryRouter>,
    );

    const visualEditorLink = await screen.findByRole("link", { name: /Visual editor/i });
    expect(visualEditorLink).toHaveAttribute("href", "/admin/relationships/visual-editor");
    expect(visualEditorLink).toHaveAttribute("target", "_blank");
    expect(visualEditorLink).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders tunnel rows with shared medium, icon, authority, and tooltip context", async () => {
    mockApiGet.mockImplementation((endpoint: string) => {
      if (endpoint === "/nodes") return Promise.resolve([]);
      if (endpoint === "/categories") return Promise.resolve([]);
      if (endpoint === "/links") {
        return Promise.resolve([
          {
            source: "core-router",
            source_label: "Core Router",
            target: "edge-router",
            target_label: "Edge Router",
            relationship: "CONNECTS_TO",
            medium: "vpn",
            tunnel_health: {
              link_id: "core-edge",
              source: "core-router",
              target: "edge-router",
              relationship: "CONNECTS_TO",
              medium: "vpn",
              status: "UNKNOWN",
              authority: { state: "UNKNOWN" },
              icmp: { reason: "missing_public_ip" },
            },
          },
        ]);
      }
      return Promise.resolve([]);
    });

    render(
      <MemoryRouter>
        <RelationshipManager onRefresh={vi.fn()} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("VPN tunnel")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "VPN Tunnel technology icon" })).toBeInTheDocument();
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByText("Missing public IP")).toBeInTheDocument();
  });
});
