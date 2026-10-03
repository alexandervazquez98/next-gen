/**
 * LinkTypeLegend.test.tsx
 *
 * Slice 2/4 of feat-444 (closes #444): React Testing Library tests for the
 * `LinkTypeLegend` presentational component. The component is purely
 * visual — it iterates `PHYSICAL_LINK_STYLES` and renders one row per
 * PhysicalLinkType. It MUST NOT be hardcoded to a literal list of types:
 * adding a new PhysicalLinkType must surface automatically once styled.
 *
 * Coverage map:
 *   T3 — exactly 4 list items, each type's label appears, no extra rows,
 *        component exposes a stable accessible name.
 */

import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { LinkTypeLegend } from "../LinkTypeLegend";

const CANONICAL_TYPES = ["copper", "fiber", "microwave", "wireless_ptp"] as const;

describe("LinkTypeLegend (T3)", () => {
  it("renders exactly four list items, one per PhysicalLinkType", () => {
    render(<LinkTypeLegend />);
    const list = screen.getByRole("list", {
      name: /physical link type legend/i,
    });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    // Exactly one row per canonical type — no extra, no missing.
    expect(items).toHaveLength(CANONICAL_TYPES.length);
  });

  it("exposes every canonical PhysicalLinkType label", () => {
    render(<LinkTypeLegend />);
    const labels = ["Fiber", "Copper", "Microwave", "Wireless P2P"];
    for (const label of labels) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders the canonical type key (fiber / copper / microwave / wireless_ptp)", () => {
    render(<LinkTypeLegend />);
    for (const type of CANONICAL_TYPES) {
      expect(screen.getByText(type)).toBeInTheDocument();
    }
  });

  it("uses semantic <ul>/<li> markup with an accessible name", () => {
    const { container } = render(<LinkTypeLegend />);
    const ul = container.querySelector("ul[aria-label]");
    expect(ul).not.toBeNull();
    expect(ul?.getAttribute("aria-label")).toMatch(/physical link type legend/i);
    // Each row is a real <li> child of the <ul>.
    expect(ul?.querySelectorAll(":scope > li")).toHaveLength(4);
  });
});
