/**
 * PhysicalLinkPreview.test.tsx
 *
 * Slice 2/4 of feat-444 (closes #444): React Testing Library tests for the
 * `PhysicalLinkPreview` showcase component. The component is the public
 * proof that the static visual contract (registry + legend) lines up with
 * real CRUD data — it renders the legend alongside a fetched list of
 * PhysicalLinks and exposes a small create form + status selector.
 *
 * Coverage map:
 *   - The legend renders (reuse the LinkTypeLegend contract — exactly four
 *     rows, every canonical type appears).
 *   - Fetched rows are rendered with a status badge and endpoints display.
 *   - Submitting the create form triggers the create mutation with the
 *     user-supplied payload.
 *   - Changing a row's status selector triggers the status mutation with
 *     the row's id and the new status.
 *
 * Mocking strategy: `vi.mock` both hook modules so the test does not touch
 * the network or need a QueryClientProvider. Each hook returns a stub object
 * that exposes a `mutate` jest-style function we can spy on.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PhysicalLink, PhysicalLinkType } from "../../../../types";

const { mutateCreate, mutateStatus } = vi.hoisted(() => ({
  mutateCreate: vi.fn(),
  mutateStatus: vi.fn(),
}));

const sampleRow: PhysicalLink = {
  id: "pl-fiber-001",
  type: "fiber",
  endpoints: ["ci-router-a", "ci-router-b"],
  status: "UP",
  capacity_gbps: 10,
  install_date: null,
};

const sampleRows: PhysicalLink[] = [
  sampleRow,
  {
    id: "pl-copper-002",
    type: "copper",
    endpoints: ["ci-switch-a", "ci-switch-b"],
    status: "DOWN",
    capacity_gbps: 1,
    install_date: null,
  },
];

vi.mock("../../../../hooks/queries/usePhysicalLinksQuery", () => ({
  usePhysicalLinksQuery: () => ({
    data: sampleRows,
    isLoading: false,
    error: null,
  }),
}));

vi.mock("../../../../hooks/queries/usePhysicalLinkMutations", () => ({
  useCreatePhysicalLink: () => ({ mutate: mutateCreate, isPending: false }),
  useUpdatePhysicalLinkStatus: () => ({ mutate: mutateStatus, isPending: false }),
}));

import { PhysicalLinkPreview } from "../PhysicalLinkPreview";

describe("PhysicalLinkPreview", () => {
  it("renders the LinkTypeLegend alongside the fetched list", () => {
    render(<PhysicalLinkPreview />);

    // Legend assertions — the legend is keyed off the registry, so four rows
    // is the contract regardless of how the list is populated.
    const list = screen.getByRole("list", { name: /physical link type legend/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    for (const label of ["Fiber", "Copper", "Microwave", "Wireless P2P"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders the fetched PhysicalLinks with endpoints + status badges", () => {
    render(<PhysicalLinkPreview />);

    // Each row's id is rendered so the test can scope queries to a single row.
    expect(screen.getByText("pl-fiber-001")).toBeInTheDocument();
    expect(screen.getByText("pl-copper-002")).toBeInTheDocument();

    // Endpoints are joined by '→' in the rendered output.
    expect(screen.getByText(/ci-router-a\s+→\s+ci-router-b/)).toBeInTheDocument();
    expect(screen.getByText(/ci-switch-a\s+→\s+ci-switch-b/)).toBeInTheDocument();

    // Status badge text appears for both rows.
    const upBadge = screen.getAllByText("UP");
    const downBadge = screen.getAllByText("DOWN");
    expect(upBadge.length).toBeGreaterThanOrEqual(1);
    expect(downBadge.length).toBeGreaterThanOrEqual(1);
  });

  it("renders a row swatch derived from the registered PhysicalLinkStyle", () => {
    const { container } = render(<PhysicalLinkPreview />);
    // Each row carries an SVG swatch; the stroke equals the registered color.
    const swatches = container.querySelectorAll('[data-testid^="physical-link-row-swatch-"]');
    expect(swatches.length).toBe(sampleRows.length);
    // The fiber row carries stroke=#2563eb (the registered color) on its inner line.
    const fiberSwatch = container.querySelector(
      '[data-testid="physical-link-row-swatch-fiber"] line',
    );
    expect(fiberSwatch).not.toBeNull();
    expect((fiberSwatch as SVGLineElement).getAttribute("stroke")).toBe("#2563eb");
  });

  it("submits the create form with the user-supplied payload", () => {
    render(<PhysicalLinkPreview />);

    fireEvent.change(screen.getByLabelText(/id/i), {
      target: { value: "pl-new" },
    });
    fireEvent.change(screen.getByLabelText(/^type$/i), {
      target: { value: "fiber" as PhysicalLinkType },
    });
    fireEvent.change(screen.getByLabelText(/endpoint a/i), {
      target: { value: "ci-x" },
    });
    fireEvent.change(screen.getByLabelText(/endpoint b/i), {
      target: { value: "ci-y" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    expect(mutateCreate).toHaveBeenCalled();
    expect(mutateCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "pl-new",
        type: "fiber",
        endpoints: ["ci-x", "ci-y"],
      }),
    );
  });

  it("changing a row's status selector fires the status mutation with id + status", () => {
    render(<PhysicalLinkPreview />);

    // There are two selects: one in the create form (PhysicalLinkType) and
    // one per row (status). Find the row's status select via its aria-label.
    const statusSelect = screen.getByLabelText(/status for pl-fiber-001/i);
    fireEvent.change(statusSelect, { target: { value: "DOWN" } });

    expect(mutateStatus).toHaveBeenCalled();
    expect(mutateStatus).toHaveBeenCalledWith({
      id: "pl-fiber-001",
      status: "DOWN",
    });
  });
});
