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

import { useCallback } from "react";
import { type OverviewCluster } from "../types/graph";
import { useGraphOverviewQuery } from "../hooks/queries/useGraphOverviewQuery";
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
  const { data: overview, isLoading, error } = useGraphOverviewQuery();
  // Topology is still loaded in the background for the location
  // filter catalog (``allLocations``) and as the fallback path
  // (PR6). It is NOT the primary render source anymore.
  const { data: fullData } = useGraphTopologyQuery({});
  const { data: categories } = useCategoriesQuery();
  const { data: owners } = useOwnersQuery();

  const handleClusterClick = useCallback(
    (cluster: OverviewCluster) => {
      if (onClusterClick) {
        onClusterClick(cluster);
      }
      // PR5 wires this to fetchGraphDetail + setSelectedClusterId.
    },
    [onClusterClick],
  );

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

  if (error) {
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
            {error.message}. PR6 will add automatic fallback to /graph/full.
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

// Helper for downstream tests / Storybook stories.
// (Removed: PR4 keeps the module side-effect-free for fast refresh.)
