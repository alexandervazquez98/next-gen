/* eslint-disable @typescript-eslint/no-explicit-any */
import React, { useState } from "react";
import { GraphLink, GraphNode } from "../types";
import { getStatusClasses } from "../utils/status";
import CategoryIcon from "./CategoryIcon";
import MetricHistoryChart from "./MetricHistoryChart";
import { isTunnelMedium, resolveTunnelVisual } from "../utils/tunnelVisuals";
import TunnelVisualSummary from "./TunnelVisualSummary";

interface CIDetailModalProps {
  node: GraphNode | null;
  onClose: () => void;
}

const CIDetailModal: React.FC<CIDetailModalProps> = ({ node, onClose }) => {
  const [selectedMetric, setSelectedMetric] = useState<any | null>(null);

  if (!node) return null;
  const scopedPublicIp =
    node.public_ip ??
    (typeof node.metadata?.public_ip === "string" ? node.metadata.public_ip : null);
  const topologyLinks = Array.isArray(node.metadata?.topology_links)
    ? (node.metadata.topology_links as GraphLink[])
    : [];
  const tunnelVisuals = topologyLinks
    .filter((link) => isTunnelMedium(link.medium))
    .map((link) => ({
      link,
      visual: resolveTunnelVisual(link, link.tunnel_health ?? undefined),
    }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-surface-900 border border-white/10 rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col shadow-2xl animate-scale-in relative">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-neutral-500 hover:text-white transition-colors z-10"
        >
          <span className="material-symbols-outlined">close</span>
        </button>

        {/* Header */}
        <div className="p-8 border-b border-white/5 bg-white/5 relative overflow-hidden">
          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-2">
              <span
                className={`w-3 h-3 rounded-full ${node.status === "EXCEPTION" ? "bg-red-500 animate-pulse" : "bg-emerald-500"}`}
              ></span>
              <span className="text-xs font-bold text-neutral-400 uppercase tracking-widest">
                {node.status} STATUS
              </span>
            </div>
            <h2 className="text-4xl font-black text-white uppercase tracking-tighter">
              {node.label || node.id}
            </h2>
            <div className="flex flex-wrap gap-3 mt-4">
              <span className="text-xs font-mono text-neutral-400 bg-black/40 px-3 py-1.5 rounded-lg border border-white/5">
                ID: {node.id}
              </span>
              {(node.category || node.type) && (
                <span className="inline-flex items-center gap-1 text-xs font-bold text-brand-400 bg-brand-500/10 px-3 py-1.5 rounded-lg border border-brand-500/20">
                  <CategoryIcon
                    iconKey={node.category_icon_key}
                    categoryName={node.category || node.type}
                    className="text-sm"
                  />
                  {node.category || node.type}
                </span>
              )}
              <span className="text-xs font-mono text-accent-cyan bg-accent-cyan/10 px-3 py-1.5 rounded-lg border border-accent-cyan/20">
                {node.ip || "NO IP"}
              </span>
              {scopedPublicIp && (
                <span className="text-xs font-mono text-emerald-300 bg-emerald-500/10 px-3 py-1.5 rounded-lg border border-emerald-500/20">
                  <span className="font-bold">Public IP</span>: <span>{scopedPublicIp}</span>
                </span>
              )}
              {node.location_name && (
                <span className="text-xs font-bold text-purple-400 bg-purple-500/10 px-3 py-1.5 rounded-lg border border-purple-500/20">
                  {node.location_name}
                </span>
              )}
            </div>
          </div>
          {/* Background Pattern */}
          <div className="absolute top-0 right-0 p-8 opacity-10 pointer-events-none">
            <span className="material-symbols-outlined text-[120px]">hub</span>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-8">
          {/* Selected Metric Chart */}
          {selectedMetric && (
            <div className="mb-8 animate-fade-in">
              <MetricHistoryChart
                nodeId={node.id}
                metricId={selectedMetric.name} // Assuming name maps to ID for now, or use mapped ID
                metricName={selectedMetric.name}
                unit={selectedMetric.unit}
              />
            </div>
          )}

          <div className="flex items-center justify-between mb-6">
            <h3 className="text-lg font-bold text-white uppercase tracking-tight flex items-center gap-2">
              <span className="material-symbols-outlined">monitoring</span>
              Live Metrics
            </h3>
            <span className="bg-white/10 px-3 py-1 rounded-full text-[10px] font-bold text-neutral-300">
              {node.metrics?.length || 0} ACTIVE
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {node.metrics?.map((metric, idx) => (
              <div
                key={idx}
                onClick={() => setSelectedMetric(metric)}
                className={`cursor-pointer p-5 rounded-xl border ${selectedMetric?.name === metric.name ? "border-brand-500 bg-brand-500/10 ring-1 ring-brand-500" : getStatusClasses(metric.status) + " bg-surface-800"} flex flex-col gap-3 transition-all hover:scale-[1.02] hover:shadow-lg`}
              >
                <div className="flex justify-between items-start">
                  <div className="flex flex-col">
                    <span className="text-[10px] font-black uppercase opacity-60 tracking-wider mb-0.5">
                      {metric.protocol}
                    </span>
                    <h4 className="font-black text-sm uppercase text-white/90">{metric.name}</h4>
                  </div>
                  {metric.status === "CRITICAL" && (
                    <span className="material-symbols-outlined text-red-500 animate-pulse">
                      warning
                    </span>
                  )}
                  {metric.status === "WARNING" && (
                    <span className="material-symbols-outlined text-orange-500">priority_high</span>
                  )}
                  {metric.status === "OK" && (
                    <span className="material-symbols-outlined text-emerald-500">check_circle</span>
                  )}
                </div>

                <div className="flex items-end gap-2 py-1">
                  <span className="text-3xl font-black tracking-tighter text-white">
                    {metric.value ?? "--"}
                  </span>
                  {/* Metric unit is not available on MetricValue type currently */}
                </div>

                <div className="mt-auto border-t border-white/5 pt-3 flex justify-between items-center text-[10px] font-mono opacity-50">
                  <span>Last Updated</span>
                  <span>
                    {metric.last_updated
                      ? new Date(metric.last_updated).toLocaleTimeString()
                      : "NEVER"}
                  </span>
                </div>
              </div>
            ))}

            {(!node.metrics || node.metrics.length === 0) && (
              <div className="col-span-full border border-dashed border-white/10 rounded-xl p-12 text-center text-neutral-500 flex flex-col items-center justify-center">
                <span className="material-symbols-outlined text-4xl mb-3 opacity-50">
                  sensor_window
                </span>
                <p className="text-sm font-bold uppercase">No Telemetry Configured</p>
                <p className="text-xs mt-1 opacity-60 max-w-xs">
                  Assign metrics to this CI in the Inventory or Administration settings.
                </p>
              </div>
            )}
          </div>

          {tunnelVisuals.length > 0 && (
            <div className="mt-8 border-t border-white/5 pt-8">
              <h3 className="text-lg font-bold text-white uppercase tracking-tight flex items-center gap-2 mb-6">
                <span className="material-symbols-outlined">account_tree</span>
                Topology Context
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {tunnelVisuals.map(({ link, visual }) => (
                  <TunnelVisualSummary
                    key={link.id ?? `${link.source}-${link.target}-${link.relationship}`}
                    title={`${link.source} → ${link.target}`}
                    visual={visual}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Metadata Section */}
          {node.metadata && Object.keys(node.metadata).length > 0 && (
            <div className="mt-8 border-t border-white/5 pt-8">
              <h3 className="text-lg font-bold text-white uppercase tracking-tight flex items-center gap-2 mb-6">
                <span className="material-symbols-outlined">info</span>
                Metadata
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Object.entries(node.metadata).map(([key, value]) => (
                  <div key={key} className="bg-white/5 rounded-lg p-3 border border-white/5">
                    <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-1">
                      {key}
                    </p>
                    <p
                      className="text-sm font-mono text-neutral-300 truncate"
                      title={String(value)}
                    >
                      {String(value)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CIDetailModal;
