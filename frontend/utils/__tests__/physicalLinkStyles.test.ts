/**
 * physicalLinkStyles.test.ts
 *
 * Slice 2/4 of feat-444 (closes #444): pure-helper unit tests on the static
 * style registry that backs the future topology renderers for PhysicalLink
 * types. Pure data exports — no React, no DOM, no async. Strict TDD RED
 * fixture observed before the implementation in `physicalLinkStyles.ts`
 * existed.
 *
 * Coverage map:
 *   T1 — `getPhysicalLinkStyle(t)` returns a PhysicalLinkStyle with the
 *        canonical color for every PhysicalLinkType, plus the registry is
 *        frozen at runtime (assignment at the top level throws in strict
 *        mode).
 *   T2 — `Object.keys(PHYSICAL_LINK_STYLES).sort()` deep-equals the
 *        canonical 4-type list, catching future drift if a type is added to
 *        `PhysicalLinkType` but not styled.
 */

import { describe, expect, it } from "vitest";
import { PHYSICAL_LINK_STYLES, getPhysicalLinkStyle } from "../physicalLinkStyles";
import type { PhysicalLinkType, PhysicalLinkStyle } from "../../types";

const CANONICAL_KEYS = ["copper", "fiber", "microwave", "wireless_ptp"] as const;
const ALL_TYPES: PhysicalLinkType[] = ["fiber", "copper", "microwave", "wireless_ptp"];

// Expected colors from feat-444 style contract (see odd/tasks/feat-444-physical-link-styling.md).
const EXPECTED_COLOR: Record<PhysicalLinkType, string> = {
  fiber: "#2563eb",
  copper: "#d97706",
  microwave: "#dc2626",
  wireless_ptp: "#7c3aed",
};

describe("PHYSICAL_LINK_STYLES — exhaustive registry (T2)", () => {
  it("contains exactly the four canonical PhysicalLinkType keys", () => {
    expect(Object.keys(PHYSICAL_LINK_STYLES).sort()).toEqual([...CANONICAL_KEYS]);
  });

  it("never includes a key outside the PhysicalLinkType union", () => {
    for (const key of Object.keys(PHYSICAL_LINK_STYLES)) {
      expect(ALL_TYPES).toContain(key);
    }
  });
});

describe("getPhysicalLinkStyle — per-type lookup (T1)", () => {
  it.each(ALL_TYPES)("returns the canonical color for PhysicalLinkType '%s'", (type) => {
    const style: PhysicalLinkStyle = getPhysicalLinkStyle(type);
    expect(style.color).toBe(EXPECTED_COLOR[type]);
  });

  it.each(ALL_TYPES)(
    "returns a fully-populated shape (color / weight / dashArray / label) for '%s'",
    (type) => {
      const style = getPhysicalLinkStyle(type);
      expect(typeof style.color).toBe("string");
      expect(style.color.length).toBeGreaterThan(0);
      expect(typeof style.weight).toBe("number");
      expect(Number.isFinite(style.weight)).toBe(true);
      expect(style.weight).toBeGreaterThan(0);
      // dashArray is a non-empty string OR null — never undefined.
      if (style.dashArray !== null) {
        expect(typeof style.dashArray).toBe("string");
        expect(style.dashArray.length).toBeGreaterThan(0);
      }
      expect(typeof style.label).toBe("string");
      expect(style.label.length).toBeGreaterThan(0);
    },
  );

  it("exposes a human-readable label distinct from the raw type key", () => {
    for (const type of ALL_TYPES) {
      const style = getPhysicalLinkStyle(type);
      // Sanity: labels are not literally the snake_case type key.
      expect(style.label).not.toBe(type);
    }
  });
});

describe("PHYSICAL_LINK_STYLES — runtime immutability guard (T1)", () => {
  it("throws when an external caller attempts to mutate the top-level entry", () => {
    expect(() => {
      (PHYSICAL_LINK_STYLES as unknown as Record<string, unknown>).fiber = {};
    }).toThrow();
  });

  it("throws when an external caller attempts to add a new key", () => {
    expect(() => {
      (PHYSICAL_LINK_STYLES as unknown as Record<string, unknown>).unknown_type = {
        color: "#000",
        weight: 1,
        dashArray: null,
        label: "x",
      };
    }).toThrow();
  });
});
