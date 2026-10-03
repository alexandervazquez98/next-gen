import type { PhysicalLinkStyle, PhysicalLinkType } from "../types";

/**
 * Canonical style registry for the four PhysicalLink types
 * (slice 2/4 of feat-444, closes #444). Pure data export — no React, no DOM.
 *
 * The shape is enforced at compile time by `Record<PhysicalLinkType, ...>`:
 * adding a new PhysicalLinkType to `frontend/types.ts` without extending
 * this registry is a TS error. The shape is enforced at runtime by
 * `Object.freeze`: writing into the top-level entry throws in strict mode,
 * which guarantees that downstream consumers cannot accidentally mutate
 * shared styles (and the styles of every other link) at runtime.
 *
 * Style contract (canonical defaults, operators can tweak):
 *
 *   | Type          | Color     | Weight | DashArray | Label         |
 *   | ------------- | --------- | ------ | --------- | ------------- |
 *   | fiber         | #2563eb   | 3      | null      | Fiber         |
 *   | copper        | #d97706   | 3      | null      | Copper        |
 *   | microwave     | #dc2626   | 2      | "8, 4"    | Microwave     |
 *   | wireless_ptp  | #7c3aed   | 2      | "2, 4"    | Wireless P2P  |
 *
 * Editing any cell here is the single supported override surface — no other
 * code path needs to change.
 */
export const PHYSICAL_LINK_STYLES: Readonly<Record<PhysicalLinkType, PhysicalLinkStyle>> =
  Object.freeze({
    fiber: {
      color: "#2563eb",
      weight: 3,
      dashArray: null,
      label: "Fiber",
    },
    copper: {
      color: "#d97706",
      weight: 3,
      dashArray: null,
      label: "Copper",
    },
    microwave: {
      color: "#dc2626",
      weight: 2,
      dashArray: "8, 4",
      label: "Microwave",
    },
    wireless_ptp: {
      color: "#7c3aed",
      weight: 2,
      dashArray: "2, 4",
      label: "Wireless P2P",
    },
  });

/**
 * Pure accessor. Returns the registered style for the given PhysicalLinkType.
 * The exhaustive `PhysicalLinkType` parameter means callers cannot pass an
 * unknown string — TypeScript rejects it at compile time.
 */
export function getPhysicalLinkStyle(t: PhysicalLinkType): PhysicalLinkStyle {
  return PHYSICAL_LINK_STYLES[t];
}
