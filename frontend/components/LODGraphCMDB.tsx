// frontend/components/LODGraphCMDB.tsx — #392 PR4
//
// Level-of-Detail CMDB view. Mount calls ``GET /api/graph/overview``
// (the LOD endpoint shipped in v1.18.0) instead of ``/api/graph/full``,
// so the first paint only loads location-cluster aggregates — not
// every CI node. Per-cluster expansion to detail arrives in PR5 via
// ``GET /api/graph/detail/{cluster_id}``.
//
// This component coexists with the legacy ``GraphCMDB.tsx`` while
// consumer migration happens in #393. The router (``App.tsx``)
// routes ``/cmdb`` to this component; ``NetworkVisualizer`` and other
// consumers keep using the legacy component until their own migration
// lands.
//
// Visual design: cluster cards in a responsive grid, each showing
// the location label, visible-node count, and redaction status. The
// cards are click handlers that surface cluster selection (PR5 wires
// them to detail hydration; PR4 leaves the handler a no-op).

import { useCallback, useState } from "react";
import { type OverviewCluster } from "../types/graph";
import { useGraphOverviewQuery } from "../hooks/queries/useGraphOverviewQuery";
import { useGraphDetailQuery } from "../hooks/queries/useGraphDetailQuery";
import { useGraphTopologyQuery } from "../hooks/queries/useGraphTopologyQuery";
import { useCategoriesQuery } from "../hooks/queries/useCategoriesQuery";
import { useOwnersQuery } from "../hooks/queries/useOwnersQuery";

export interface LODGraphCMDBProps {
  // Forwarded to the parent. The full cluster object is forwarded;
  // the parent decides what to do with it (PR5 wires detail fetch).
  onClusterClick?(_cluster: OverviewCluster): void;
}

function ClusterCard({
  cluster,
  onClick,
}: {
  cluster: OverviewCluster;
  onClick: (_cluster: OverviewCluster) => void;
}) {
  const isRedacted = cluster.aggregate_redacted;
  return (
    <button
      type="button"
      onClick={() => onClick(cluster)}
      data-testid={`cluster-card-${cluster.cluster_id}`}
      className={`group text-left p-4 rounded-xl border transition-all ${
        isRedacted
          ? "border-orange-500/20 bg-orange-500/5 hover:bg-orange-500/10"
          : "border-white/5 bg-neutral-950/60 hover:bg-neutral-900 hover:border-brand-500/30"
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <div
          className={`w-2 h-2 rounded-full ${
            isRedacted
              ? "bg-orange-500 shadow-[0_0_8px_rgba(249,115,22,0.5)]"
              : "bg-brand-500 shadow-[0_0_8px_rgba(52,91,242,0.5)]"
          }`}
        />
        <span className="text-[10px] font-black uppercase tracking-tighter text-neutral-300">
          {cluster.display_label}
        </span>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-black text-white">{cluster.visible_node_count}</span>
        <span className="text-[10px] font-bold text-neutral-500 uppercase">nodes</span>
      </div>
      {isRedacted && (
        <div className="mt-2 text-[10px] text-orange-400 uppercase font-bold tracking-tight">
          Aggregate Redacted ({cluster.suppression_reason ?? "low_cardinality"})
        </div>
      )}
    </button>
  );
}

const LODGraphCMDB = ({ onClusterClick }: LODGraphCMDBProps) => {
  const { data: overview, isLoading, error: overviewError } = useGraphOverviewQuery();
  // Topology is still loaded in the background for the location
  // filter catalog (``allLocations``) and as the fallback path
  // (PR6). It is NOT the primary render source anymore.
  const { data: fullData } = useGraphTopologyQuery({});
  const { data: categories } = useCategoriesQuery();
  const { data: owners } = useOwnersQuery();

  // PR5: detail hydration state.
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const { data: detail, isFetching: detailLoading } = useGraphDetailQuery(selectedClusterId);

  const handleClusterClick = useCallback(
    (cluster: OverviewCluster) => {
      setSelectedClusterId(cluster.cluster_id);
      if (onClusterClick) {
        onClusterClick(cluster);
      }
    },
    [onClusterClick],
  );

  const handleDetailClose = useCallback(() => {
    setSelectedClusterId(null);
  }, []);

  const clusters = overview?.clusters ?? [];
  const allLocations = Array.from(
    new Set(
      (fullData?.nodes ?? [])
        .map((n) => n.location_name)
        .filter((loc): loc is string => Boolean(loc)),
    ),
  ).sort();

  if (isLoading) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-surface-950 grid-bg">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-brand-500/20 border-t-brand-500 rounded-full animate-spin" />
          <span className="text-xs font-black text-brand-500 uppercase tracking-widest">
            Loading LOD overview…
          </span>
        </div>
      </div>
    );
  }

  // PR6: fallback path. When overview fails but the background
  // topology query succeeded, render the topology as a degraded
  // fallback so operators still see data.
  if (overviewError && fullData) {
    return (
      <FallbackView
        nodes={fullData.nodes ?? []}
        links={fullData.links ?? []}
        reason={overviewError.message}
        onClusterClick={onClusterClick}
      />
    );
  }

  if (overviewError) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-surface-950 grid-bg">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div className="w-12 h-12 rounded-full bg-red-500/20 flex items-center justify-center">
            <span className="text-red-500 material-symbols-outlined">error</span>
          </div>
          <span className="text-xs font-black text-red-400 uppercase tracking-widest">
            LOD overview unavailable
          </span>
          <span className="text-xs text-neutral-500">
            {overviewError.message}. Both overview and fallback topology failed.
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full flex flex-col bg-surface-950 grid-bg">
      <header className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-black text-white uppercase tracking-widest">
            CMDB Topology (LOD)
          </h2>
          <p className="text-[10px] text-neutral-500 uppercase mt-1">
            {clusters.length} cluster
            {clusters.length === 1 ? "" : "s"} ·{" "}
            {clusters.reduce((acc, c) => acc + c.visible_node_count, 0)} total nodes visible
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-brand-500 shadow-[0_0_8px_rgba(52,91,242,0.5)]" />
          <span className="text-[10px] font-bold text-neutral-300 uppercase">
            v1.18.0 LOD overview
          </span>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
          }}
          data-testid="cluster-grid"
        >
          {clusters.map((cluster) => (
            <ClusterCard key={cluster.cluster_id} cluster={cluster} onClick={handleClusterClick} />
          ))}
        </div>
        {clusters.length === 0 && (
          <div className="flex flex-col items-center gap-2 mt-12">
            <span className="text-xs font-black text-neutral-500 uppercase tracking-widest">
              No visible clusters
            </span>
            <span className="text-[10px] text-neutral-500">
              Hidden ≡ absent (REQ-OVERVIEW-3, REQ-DETAIL-4): an empty overview is indistinguishable
              from an empty graph.
            </span>
          </div>
        )}
        {/* PR5: detail panel — delimited overlay when a cluster is selected */}
        {selectedClusterId && (
          <div
            data-testid="detail-panel"
            className="mt-6 rounded-xl border border-brand-500/30 bg-neutral-950/80 p-4"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-brand-500" />
                <span className="text-[10px] font-black text-neutral-300 uppercase">
                  Detail: {selectedClusterId}
                </span>
                {detailLoading && (
                  <span className="text-[10px] text-neutral-500 uppercase">loading…</span>
                )}
              </div>
              <button
                type="button"
                onClick={handleDetailClose}
                data-testid="detail-close"
                className="text-[10px] text-neutral-500 hover:text-white uppercase"
              >
                Close
              </button>
            </div>
            {detail && (
              <ul className="space-y-1 text-[10px] text-neutral-400" data-testid="detail-nodes">
                {detail.nodes.slice(0, 20).map((node) => (
                  <li
                    key={node.id}
                    className="px-2 py-1 rounded bg-neutral-900 border border-white/5"
                  >
                    {node.id} — {node.display_label} ({node.ci_type})
                  </li>
                ))}
                {detail.nodes.length > 20 && (
                  <li className="text-[10px] text-neutral-500 px-2 py-1">
                    … {detail.nodes.length - 20} more nodes (truncated for display)
                  </li>
                )}
                {detail.nodes.length === 0 && (
                  <li className="text-[10px] text-neutral-500 px-2 py-1">
                    {detail.empty_reason === "hidden_absent"
                      ? "Hidden — externally indistinguishable from absent."
                      : "No visible nodes in this cluster."}
                  </li>
                )}
              </ul>
            )}
          </div>
        )}
      </div>

      <footer className="px-6 py-3 border-t border-white/5 flex items-center justify-between text-[10px] uppercase text-neutral-500">
        <span>Locations catalog: {allLocations.length} (background topology fetch)</span>
        <span>
          Categories: {categories?.length ?? 0} · Owners: {owners?.length ?? 0}
        </span>
      </footer>
    </div>
  );
};

export default LODGraphCMDB;

/**
 * PR6: Fallback view rendered when the LOD overview endpoint fails
 * but the background /graph/full query succeeded.
 */
function FallbackView({
  nodes,
  links: _links,
  reason,
  onClusterClick,
}: {
  nodes: Array<{ id: string; label?: string; location_name?: string | null }>;
  links: unknown[];
  reason: string;
  onClusterClick?: (_cluster: OverviewCluster) => void;
}) {
  const fallbackClusters: OverviewCluster[] = nodes.map((node) => ({
    cluster_id: `node:${node.id}`,
    display_label: node.label ?? node.id,
    visible_node_count: 1,
    visible_link_count: 0,
    aggregate_redacted: false,
    suppression_reason: null,
  }));
  return (
    <div className="w-full h-full flex flex-col bg-surface-950 grid-bg" data-testid="fallback-view">
      <div
        className="px-4 py-2 bg-orange-500/10 border-b border-orange-500/30 text-[10px] text-orange-300 uppercase font-bold tracking-widest"
        data-testid="fallback-banner"
      >
        Fallback active — LOD overview endpoint failed. Showing legacy topology until overview
        recovers. Reason: {reason}
      </div>
      <header className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
        <h2 className="text-sm font-black text-white uppercase tracking-widest">
          CMDB Topology (Fallback)
        </h2>
      </header>
      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
          }}
          data-testid="cluster-grid"
        >
          {fallbackClusters.map((cluster) => (
            <ClusterCard
              key={cluster.cluster_id}
              cluster={cluster}
              onClick={(c) => onClusterClick?.(c)}
            />
          ))}
        </div>
        {fallbackClusters.length === 0 && (
          <div className="flex flex-col items-center gap-2 mt-12">
            <span className="text-xs font-black text-neutral-500 uppercase tracking-widest">
              Fallback topology is empty
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// Helper for downstream tests / Storybook stories.
// (Removed: PR4 keeps the module side-effect-free for fast refresh.)
