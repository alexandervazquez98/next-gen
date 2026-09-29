// frontend/hooks/geoViewLODData.ts — #524 Tier 2 helpers
//
// Pure helpers that bridge the LOD payload (OverviewCluster + DetailNode)
// and the Geo View's color encoding. The hook layer (useGeoViewLODData)
// is a thin React Query composer over the existing queries — these
// helpers hold the actual logic.
//
// Why pure? So the function is unit-testable without a query client, and
// so the hook layer stays a single-purpose composer with no business
// logic of its own. If a future iteration splits the Geo View into
// multiple components, the helpers can be reused as-is.

import type { DetailNode, OverviewCluster } from "../types/graph";
import type { EventSummary } from "../types";

// ---------------------------------------------------------------------------
// GeoViewNode — DetailNode enriched with event-derived color flags
// ---------------------------------------------------------------------------

/**
 * A `DetailNode` enriched with the events that target its CI plus the
 * derived color flags. RECOVERED events are excluded from the joined
 * array (the Geo View paints green when the underlying condition clears,
 * mirroring the cluster-level color encoding in getClusterRenderConfig).
 */
export interface GeoViewNode extends DetailNode {
  events: EventSummary[];
  hasCritical: boolean;
  hasWarning: boolean;
}

// ---------------------------------------------------------------------------
// Color encoding constants — match MonitoringConsole's STATUS_COLORS
// ---------------------------------------------------------------------------

const COLOR_OK = "#10b981"; // emerald-500 (MonitoringConsole OK)
const COLOR_WARNING = "#eab308"; // yellow-500
const COLOR_CRITICAL = "#ef4444"; // red-500

export interface ClusterRenderConfig {
  worstSeverity: "OK" | "WARNING" | "CRITICAL";
  color: string;
  pixelRadius: number;
}

// ---------------------------------------------------------------------------
// joinEventsToNodes — match each DetailNode to its active events
// ---------------------------------------------------------------------------

/**
 * Joins events to nodes by `event.ci_id === node.id`. RECOVERED events
 * are excluded from the joined array — the Geo View treats them as
 * "system healed" and doesn't color on them. CLOSED events are also
 * excluded since the active feed (status="CONSOLE") only returns
 * OPEN + ACK + RECOVERED rows; this function is robust regardless.
 */
export function joinEventsToNodes(
  nodes: DetailNode[],
  events: EventSummary[],
): GeoViewNode[] {
  return nodes.map((node) => {
    const nodeEvents = events.filter((e) => e.ci_id === node.id);
    const active = nodeEvents.filter((e) => e.status !== "RECOVERED");
    return {
      ...node,
      events: nodeEvents,
      hasCritical: active.some((e) => e.severity === "CRITICAL"),
      hasWarning: active.some((e) => e.severity === "WARNING"),
    };
  });
}

// ---------------------------------------------------------------------------
// getClusterRenderConfig — color encoding for OverviewCluster markers
// ---------------------------------------------------------------------------

/**
 * Resolves the render config for an `OverviewCluster` based on its
 * aggregated severity counts (#524). Worst severity wins:
 *
 *   critical_count > 0   → CRITICAL (red)
 *   warning_count  > 0   → WARNING  (yellow)
 *   otherwise            → OK       (green / emerald)
 *
 * Redacted clusters (aggregate_redacted=True) are ALWAYS rendered OK,
 * regardless of the count fields. The service layer already zeros those
 * counts on the wire (REQ-9 sensitivity policy), but the renderer is
 * defensive in case it ever receives a raw payload that violates the
 * contract.
 *
 * `pixelRadius` scales with `visible_node_count` so busy clusters draw
 * larger circles — a supercluster-style hint that's stable for any
 * node count, including the 50k+ case the issue targets.
 */
export function getClusterRenderConfig(cluster: OverviewCluster): ClusterRenderConfig {
  let worstSeverity: "OK" | "WARNING" | "CRITICAL";
  let color: string;

  if (cluster.aggregate_redacted) {
    // Defensive: redacted clusters are OK regardless of underlying counts.
    worstSeverity = "OK";
    color = COLOR_OK;
  } else if (cluster.critical_count > 0) {
    worstSeverity = "CRITICAL";
    color = COLOR_CRITICAL;
  } else if (cluster.warning_count > 0) {
    worstSeverity = "WARNING";
    color = COLOR_WARNING;
  } else {
    worstSeverity = "OK";
    color = COLOR_OK;
  }

  // Scale pixel radius with visible_node_count. Clamped so a 50k cluster
  // doesn't paint over the entire viewport; minimum 8 px so a single-node
  // cluster is still visible.
  const BASE_RADIUS = 8;
  const SCALE = Math.log10(Math.max(cluster.visible_node_count, 1)) * 4;
  const pixelRadius = Math.min(BASE_RADIUS + SCALE, 28);

  return { worstSeverity, color, pixelRadius };
}