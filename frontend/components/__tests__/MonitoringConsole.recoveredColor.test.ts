/**
 * MonitoringConsole — recovered-event color isolation.
 *
 * Verifies that the map marker color and size for a CI reflect only
 * ACTIVE events (OPEN / ACK). Events that have transitioned to
 * RECOVERED must not keep the marker red, and the marker radius must
 * shrink back to its base size once all critical/warning events are
 * recovered.
 *
 * Bug history: a CI whose CRITICAL event recovered would stay red
 * forever until the operator manually closed it — see task
 * `odd/tasks/fix-event-recovered-color-ci-marker.md`.
 */

import { describe, expect, it } from "vitest";
import { getNodeRenderConfig } from "../MonitoringConsole";

describe("getNodeRenderConfig — RECOVERED event isolation", () => {
  it("CRITICAL OPEN keeps the marker red", () => {
    const cfg = getNodeRenderConfig({
      hasCritical: true,
      hasWarning: false,
      events: [{ severity: "CRITICAL", status: "OPEN" }],
    });
    expect(cfg.color).toBe("#ef4444");
    expect(cfg.showAura).toBe(true);
  });

  it("CRITICAL RECOVERED alone does NOT keep the marker red", () => {
    // The pre-computed hasCritical flag is what drives the colour branch.
    // At the data-source level (`nodesWithEvents`), hasCritical is computed
    // from active events only — so a CI with only recovered events gets
    // hasCritical=false and falls into the OK branch below.
    const cfg = getNodeRenderConfig({
      hasCritical: false,
      hasWarning: false,
      events: [{ severity: "CRITICAL", status: "RECOVERED" }],
    });
    expect(cfg.color).not.toBe("#ef4444");
    expect(cfg.color).not.toBe("#eab308"); // not yellow either
    expect(cfg.showAura).toBe(false);
  });

  it("RECOVERED is excluded from the critCount that scales the marker radius", () => {
    // Two recovered + one open critical: the marker should size as if there
    // was only ONE active critical event, not three.
    const cfg = getNodeRenderConfig({
      hasCritical: true,
      hasWarning: false,
      events: [
        { severity: "CRITICAL", status: "RECOVERED" },
        { severity: "CRITICAL", status: "RECOVERED" },
        { severity: "CRITICAL", status: "OPEN" },
      ],
    });
    // BASE_RADIUS = 6, critCount-after-filter = 1.
    // pixelRadius = 6 * 1.5 + 1 * 2 = 11.
    expect(cfg.pixelRadius).toBe(11);
  });

  it("mix of CRITICAL RECOVERED + WARNING OPEN → yellow, not red", () => {
    // Critical is recovered (system healed). Only a warning remains.
    const cfg = getNodeRenderConfig({
      hasCritical: false,
      hasWarning: true,
      events: [
        { severity: "CRITICAL", status: "RECOVERED" },
        { severity: "WARNING", status: "OPEN" },
      ],
    });
    expect(cfg.color).toBe("#eab308");
  });

  it("CRITICAL ACK keeps the marker red (still actionable)", () => {
    // ACK means a human acknowledged but the issue hasn't cleared.
    const cfg = getNodeRenderConfig({
      hasCritical: true,
      hasWarning: false,
      events: [{ severity: "CRITICAL", status: "ACK" }],
    });
    expect(cfg.color).toBe("#ef4444");
  });

  it("empty events → OK marker (blue)", () => {
    const cfg = getNodeRenderConfig({
      hasCritical: false,
      hasWarning: false,
      events: [],
    });
    expect(cfg.color).toBe("#3b82f6");
  });
});
