// frontend/hooks/__tests__/geoViewLODData.test.ts — #524
//
// Pure-helper tests for the Geo View Tier 2 LOD migration. These
// helpers are the bridge between the LOD payload (OverviewCluster +
// DetailNode) and the Geo View's color encoding (CRITICAL=red,
// WARNING=yellow, OK=blue).
//
// Keeping these pure means the hook layer (useGeoViewLODData) is a
// thin React Query composer over the existing useGraphOverviewQuery /
// useGraphDetailQuery / useActiveEventsQuery, with no logic of its own.

import { describe, it, expect } from "vitest";
import type { DetailNode, OverviewCluster } from "../../types/graph";
import type { EventSummary } from "../../types";
import { joinEventsToNodes, getClusterRenderConfig } from "../geoViewLODData";

// ---------------------------------------------------------------------------
// joinEventsToNodes
// ---------------------------------------------------------------------------

describe("joinEventsToNodes", () => {
  it("attaches matching events to each node by ci_id", () => {
    const nodes: DetailNode[] = [
      {
        id: "ci-1",
        display_label: "Router-1",
        kind: "CI",
        ci_type: "router",
        allowed_public_axes: [],
      },
      {
        id: "ci-2",
        display_label: "Router-2",
        kind: "CI",
        ci_type: "router",
        allowed_public_axes: [],
      },
    ];
    const events: EventSummary[] = [
      {
        id: "evt-1",
        ci_id: "ci-1",
        severity: "CRITICAL",
        status: "OPEN",
        ack: false,
        message: "down",
      } as EventSummary,
      {
        id: "evt-2",
        ci_id: "ci-2",
        severity: "WARNING",
        status: "ACK",
        ack: true,
        message: "high latency",
      } as EventSummary,
    ];

    const result = joinEventsToNodes(nodes, events);

    expect(result).toHaveLength(2);
    const n1 = result.find((n) => n.id === "ci-1")!;
    const n2 = result.find((n) => n.id === "ci-2")!;
    expect(n1.events).toHaveLength(1);
    expect(n1.events[0].id).toBe("evt-1");
    expect(n2.events).toHaveLength(1);
    expect(n2.events[0].id).toBe("evt-2");
  });

  it("keeps RECOVERED events in the events array (popup history) but excludes them from color flags", () => {
    // The Geo View marker color is driven by hasCritical / hasWarning,
    // which only count ACTIVE events (RECOVERED excluded). The events
    // array itself keeps RECOVERED rows so the marker popup can show
    // the recovery history, matching the existing MonitoringConsole
    // behavior at frontend/components/MonitoringConsole.tsx.
    const nodes: DetailNode[] = [
      {
        id: "ci-1",
        display_label: "Router-1",
        kind: "CI",
        ci_type: "router",
        allowed_public_axes: [],
      },
    ];
    const events: EventSummary[] = [
      {
        id: "evt-active",
        ci_id: "ci-1",
        severity: "WARNING",
        status: "ACK",
        ack: true,
        message: "active",
      } as EventSummary,
      {
        id: "evt-recovered",
        ci_id: "ci-1",
        severity: "CRITICAL",
        status: "RECOVERED",
        ack: false,
        message: "recovered",
      } as EventSummary,
    ];

    const result = joinEventsToNodes(nodes, events);
    // Both events present in the popup history.
    expect(result[0].events).toHaveLength(2);
    // But hasCritical is false: RECOVERED events don't drive the color.
    expect(result[0].hasCritical).toBe(false);
    expect(result[0].hasWarning).toBe(true);
  });

  it("sets hasCritical / hasWarning flags from the active events only", () => {
    const nodes: DetailNode[] = [
      {
        id: "ci-1",
        display_label: "Router-1",
        kind: "CI",
        ci_type: "router",
        allowed_public_axes: [],
      },
      {
        id: "ci-2",
        display_label: "Router-2",
        kind: "CI",
        ci_type: "router",
        allowed_public_axes: [],
      },
      {
        id: "ci-3",
        display_label: "Router-3",
        kind: "CI",
        ci_type: "router",
        allowed_public_axes: [],
      },
    ];
    const events: EventSummary[] = [
      {
        id: "e1",
        ci_id: "ci-1",
        severity: "CRITICAL",
        status: "OPEN",
        ack: false,
        message: "",
      } as EventSummary,
      {
        id: "e2",
        ci_id: "ci-2",
        severity: "WARNING",
        status: "OPEN",
        ack: false,
        message: "",
      } as EventSummary,
      // ci-3 has no events.
    ];

    const result = joinEventsToNodes(nodes, events);
    const byId = Object.fromEntries(result.map((n) => [n.id, n]));
    expect(byId["ci-1"].hasCritical).toBe(true);
    expect(byId["ci-1"].hasWarning).toBe(false);
    expect(byId["ci-2"].hasCritical).toBe(false);
    expect(byId["ci-2"].hasWarning).toBe(true);
    expect(byId["ci-3"].hasCritical).toBe(false);
    expect(byId["ci-3"].hasWarning).toBe(false);
  });

  it("returns an empty event array (and OK flags) for nodes with no matching events", () => {
    const nodes: DetailNode[] = [
      {
        id: "ci-orphan",
        display_label: "Orphan",
        kind: "CI",
        ci_type: "router",
        allowed_public_axes: [],
      },
    ];
    const events: EventSummary[] = [
      {
        id: "evt-x",
        ci_id: "ci-other",
        severity: "CRITICAL",
        status: "OPEN",
        ack: false,
        message: "",
      } as EventSummary,
    ];

    const result = joinEventsToNodes(nodes, events);
    expect(result[0].events).toEqual([]);
    expect(result[0].hasCritical).toBe(false);
    expect(result[0].hasWarning).toBe(false);
  });

  it("preserves node order from the input array", () => {
    const nodes: DetailNode[] = [
      { id: "ci-a", display_label: "A", kind: "CI", ci_type: "router", allowed_public_axes: [] },
      { id: "ci-b", display_label: "B", kind: "CI", ci_type: "router", allowed_public_axes: [] },
      { id: "ci-c", display_label: "C", kind: "CI", ci_type: "router", allowed_public_axes: [] },
    ];
    const result = joinEventsToNodes(nodes, []);
    expect(result.map((n) => n.id)).toEqual(["ci-a", "ci-b", "ci-c"]);
  });
});

// ---------------------------------------------------------------------------
// getClusterRenderConfig — color encoding for OverviewCluster markers
// ---------------------------------------------------------------------------

describe("getClusterRenderConfig", () => {
  const baseCluster: OverviewCluster = {
    cluster_id: "location:HQ-Madrid",
    display_label: "HQ-Madrid",
    visible_node_count: 42,
    visible_link_count: 17,
    aggregate_redacted: false,
    suppression_reason: null,
    critical_count: 0,
    warning_count: 0,
    event_count: 0,
  };

  it("returns OK color when neither critical nor warning events are present", () => {
    const cfg = getClusterRenderConfig(baseCluster);
    expect(cfg.worstSeverity).toBe("OK");
    expect(cfg.color).toBe("#10b981"); // matches MonitoringConsole OK color
  });

  it("escalates to CRITICAL when critical_count > 0 (worst severity wins)", () => {
    const cluster: OverviewCluster = {
      ...baseCluster,
      critical_count: 1,
      warning_count: 5,
      event_count: 6,
    };
    const cfg = getClusterRenderConfig(cluster);
    expect(cfg.worstSeverity).toBe("CRITICAL");
    expect(cfg.color).toBe("#ef4444");
  });

  it("escalates to WARNING when only warning_count > 0", () => {
    const cluster: OverviewCluster = {
      ...baseCluster,
      critical_count: 0,
      warning_count: 3,
      event_count: 3,
    };
    const cfg = getClusterRenderConfig(cluster);
    expect(cfg.worstSeverity).toBe("WARNING");
    expect(cfg.color).toBe("#eab308");
  });

  it("returns OK color for redacted clusters even if the underlying counts are non-zero", () => {
    // Belt-and-braces: the service already zeroes counts on redacted
    // clusters, but the renderer is defensive in case someone hands it
    // a raw payload. aggregate_redacted=True must always be OK.
    const cluster: OverviewCluster = {
      ...baseCluster,
      aggregate_redacted: true,
      suppression_reason: "low_cardinality",
      critical_count: 7, // would be a leak if surfaced as CRITICAL
      warning_count: 9,
      event_count: 16,
    };
    const cfg = getClusterRenderConfig(cluster);
    expect(cfg.worstSeverity).toBe("OK");
    expect(cfg.color).toBe("#10b981");
  });

  it("scales pixel radius with visible_node_count (supercluster-style hint)", () => {
    const cfg = getClusterRenderConfig({ ...baseCluster, visible_node_count: 1000 });
    expect(cfg.pixelRadius).toBeGreaterThan(getClusterRenderConfig(baseCluster).pixelRadius);
  });
});
