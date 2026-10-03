import React from "react";
import { PHYSICAL_LINK_STYLES } from "../../../utils/physicalLinkStyles";
import type { PhysicalLinkStyle, PhysicalLinkType } from "../../../types";

/**
 * Static visual legend for the four PhysicalLink types
 * (slice 2/4 of feat-444, closes #444).
 *
 * Presentational component — no props, no state, no side effects. Iterates
 * the keys of `PHYSICAL_LINK_STYLES` (NOT a hardcoded literal list), so
 * adding a new PhysicalLinkType and registering its style in
 * `physicalLinkStyles.ts` automatically surfaces in the legend. There is
 * no other code path to update.
 *
 * Markup is intentionally semantic: a single `<ul role="list">` with
 * one `<li>` per type, exposing an accessible name (`aria-label`). Each
 * row renders the canonical style as an inline SVG swatch (color +
 * dashArray sample), the human-readable label, and the type key in
 * monospace.
 *
 * This slice does NOT wire the styles into TopologyViewer /
 * NetworkVisualizer / MonitoringConsole / VisualRelationshipEditor. None
 * of those components consume PhysicalLink data today; wiring is a
 * follow-up slice that introduces the data flow.
 */
export function LinkTypeLegend() {
  const entries = Object.entries(PHYSICAL_LINK_STYLES) as Array<
    [PhysicalLinkType, PhysicalLinkStyle]
  >;

  return (
    <ul
      role="list"
      aria-label="Physical link type legend"
      data-testid="link-type-legend"
      style={{ listStyle: "none", margin: 0, padding: 0 }}
    >
      {entries.map(([type, style]) => (
        <li
          key={type}
          data-testid={`link-type-legend-row-${type}`}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            padding: "0.25rem 0",
          }}
        >
          <svg
            aria-hidden="true"
            focusable="false"
            width={40}
            height={12}
            viewBox="0 0 40 12"
            style={{ display: "block" }}
          >
            <line
              x1={0}
              y1={6}
              x2={40}
              y2={6}
              stroke={style.color}
              strokeWidth={style.weight}
              strokeDasharray={style.dashArray ?? undefined}
            />
          </svg>
          <span>{style.label}</span>
          <code
            style={{
              fontFamily: "ui-monospace, SFMono-Regular, monospace",
              fontSize: "0.75rem",
              color: "#475569",
            }}
          >
            {type}
          </code>
        </li>
      ))}
    </ul>
  );
}

export default LinkTypeLegend;
