/* eslint-disable no-console */
import type React from "react";
import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import type { GraphNode, TunnelHealthResponse, TunnelMedium } from "../types";
import TopologyViewer from "./TopologyViewer";
import { api } from "../services/api";
import RelationshipBadge from "./RelationshipBadge";
import RelationshipTooltip from "./RelationshipTooltip";
import { canDeleteRelationship, isReadOnlyRelationship } from "./relationshipCapabilities";
import { isTunnelMedium, resolveTunnelVisual } from "../utils/tunnelVisuals";
import TunnelVisualSummary from "./TunnelVisualSummary";

// ============================================================================
// Relationship Indicators — Types & Utilities
// ============================================================================

interface CiRelationshipEntry {
  otherId: string;
  otherLabel: string;
  type: string;
}

interface CiRelationships {
  asSource: CiRelationshipEntry[];
  asTarget: CiRelationshipEntry[];
}

type CiRelationshipMap = Map<string, CiRelationships>;

export interface LinkData {
  source: string;
  source_label?: string;
  target: string;
  target_label?: string;
  relationship: string;
  medium?: TunnelMedium;
  tunnel_health?: TunnelHealthResponse | null;
}

/**
 * Derives a Map<ciId, {asSource[], asTarget[]}> from raw link data.
 * O(n) per call — called inside useMemo in the component.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const computeRelationshipMap = (links: LinkData[]): CiRelationshipMap => {
  const map: CiRelationshipMap = new Map();

  for (const link of links) {
    // Skip HAS_METRIC links — not relevant to CI-to-CI relationship topology
    if (link.relationship === "HAS_METRIC") continue;

    const sourceId = link.source;
    const targetId = link.target;
    const sourceLabel = link.source_label || link.source;
    const targetLabel = link.target_label || link.target;

    // Initialize both endpoints if not already in map
    if (!map.has(sourceId)) map.set(sourceId, { asSource: [], asTarget: [] });
    if (!map.has(targetId)) map.set(targetId, { asSource: [], asTarget: [] });

    // source → target: source is "asSource", target is "asTarget"
    map
      .get(sourceId)!
      .asSource.push({ otherId: targetId, otherLabel: targetLabel, type: link.relationship });
    map
      .get(targetId)!
      .asTarget.push({ otherId: sourceId, otherLabel: sourceLabel, type: link.relationship });
  }

  return map;
};

interface RelationshipManagerProps {
  onRefresh: () => void;
}

interface CategoryResponse {
  name: string;
}

interface MetricResponse {
  name: string;
  description?: string;
}

/**
 * RelationshipManager Component
 *
 * Manages the creation, deletion, and visualization of relationships between Configuration Items (CIs).
 * Also handles the promotion of SNMP Metrics to Nodes (Graph Objects).
 */
const RelationshipManager: React.FC<RelationshipManagerProps> = ({ onRefresh }) => {
  // --- State: Data ---
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  // --- State: Source Selection ---
  const [sourceCategory, setSourceCategory] = useState<string>("");
  const [sourceNodeId, setSourceNodeId] = useState<string>("");

  // --- State: Target Selection ---
  const [targetCategory] = useState<string>("");
  const [targetNodeIds, setTargetNodeIds] = useState<string[]>([]);

  // --- State: Relationship Settings ---
  const [relType, setRelType] = useState<string>("DEPENDS_ON");

  // --- State: Links & Graph ---
  const [links, setLinks] = useState<LinkData[]>([]);

  // --- State: Search ---
  const [searchCiLinks, setSearchCiLinks] = useState("");

  // --- Derived: Relationship map for indicators ---
  // recomputes when links change, O(n) with typical CI counts (<1000)
  const relationshipMap = useMemo(() => computeRelationshipMap(links), [links]);

  // --- Memoized: filtered link lists to avoid repeated filter calls ---
  const ciLinks = useMemo(() => links.filter((l) => l.relationship !== "HAS_METRIC"), [links]);
  const metricLinks = useMemo(() => links.filter((l) => l.relationship === "HAS_METRIC"), [links]);

  // --- Memoized: search-filtered CI links ---
  const filteredCiLinks = useMemo(() => {
    if (!searchCiLinks.trim()) return ciLinks;
    const q = searchCiLinks.toLowerCase();
    return ciLinks.filter(
      (l) =>
        l.source.toLowerCase().includes(q) ||
        (l.source_label || "").toLowerCase().includes(q) ||
        l.target.toLowerCase().includes(q) ||
        (l.target_label || "").toLowerCase().includes(q) ||
        l.relationship.toLowerCase().includes(q),
    );
  }, [ciLinks, searchCiLinks]);

  // --- State: Mode (Links/Metrics) ---
  const [viewMode, setViewMode] = useState<"LINKS" | "METRICS">("LINKS");
  const [availableMetrics, setAvailableMetrics] = useState<MetricResponse[]>([]);
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([]);

  // --- State: Visualization Modal ---
  const [visualizationTarget, setVisualizationTarget] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  // --- Effects ---
  useEffect(() => {
    fetchData();
    fetchLinks();
  }, []);

  // Fetch metrics when Source Node changes in Metrics Mode
  useEffect(() => {
    if (viewMode === "METRICS" && sourceNodeId) {
      fetchNodeMetrics(sourceNodeId);
    } else {
      setAvailableMetrics([]);
    }
  }, [viewMode, sourceNodeId]);

  // --- API Interactions ---

  const fetchData = async () => {
    setLoading(true);
    try {
      const [nodesData, catsData] = await Promise.all([
        api.get<GraphNode[]>("/nodes"),
        api.get<CategoryResponse[]>("/categories"),
      ]);

      setNodes(Array.isArray(nodesData) ? nodesData : []);
      setCategories(Array.isArray(catsData) ? catsData.map((c) => c.name) : []);
    } catch (error) {
      console.error("Failed to fetch data", error);
      setNodes([]); // Safety fallback
      setCategories([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchLinks = async () => {
    try {
      const data = await api.get<LinkData[]>("/links");
      setLinks(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error("Failed to fetch links", error);
      setLinks([]);
    }
  };

  const fetchNodeMetrics = async (nodeId: string) => {
    try {
      const data = await api.get<MetricResponse[]>(`/nodes/${nodeId}/metrics`);
      setAvailableMetrics(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error(e);
      setAvailableMetrics([]);
    }
  };

  // --- Action Handlers ---

  const handlePromoteMetrics = async () => {
    if (!sourceNodeId || selectedMetrics.length === 0) return;

    setLoading(true);
    try {
      for (const metricName of selectedMetrics) {
        const m = availableMetrics.find((am) => am.name === metricName);
        await api.post("/metrics/promote", {
          ci_id: sourceNodeId,
          metric_name: metricName,
          display_name: m?.description || metricName,
        });
      }
      alert("Metrics promoted to Nodes successfully!");
      setSelectedMetrics([]);
      // Refresh to show new nodes in list
      fetchData();
      fetchLinks();
      onRefresh();
    } catch (e) {
      console.error(e);
      alert("Error promoting metrics");
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!sourceNodeId || targetNodeIds.length === 0 || !relType) {
      alert("Please select a source, at least one target, and a relationship type.");
      return;
    }

    if (confirm(`Create ${targetNodeIds.length} links from ${sourceNodeId}?`)) {
      setLoading(true);
      try {
        // Batch create with concurrency limit of 10
        const batchSize = 10;
        for (let i = 0; i < targetNodeIds.length; i += batchSize) {
          const batch = targetNodeIds.slice(i, i + batchSize);
          await Promise.all(
            batch.map((targetId) =>
              api.post("/links", {
                source: sourceNodeId,
                target: targetId,
                relationship: relType,
              }),
            ),
          );
        }
        alert("Relationships created successfully!");
        setTargetNodeIds([]); // Reset targets
        fetchLinks();
        onRefresh();
      } catch (e) {
        console.error(e);
        alert("Error creating links");
      } finally {
        setLoading(false);
      }
    }
  };

  const handleDelete = async (link: LinkData) => {
    if (!canDeleteRelationship(link.relationship)) return;

    if (confirm(`Delete link: ${link.source} -[${link.relationship}]-> ${link.target}?`)) {
      try {
        await api.delete("/links", link);
        fetchLinks();
        onRefresh();
      } catch (e) {
        console.error(e);
      }
    }
  };

  // --- Helpers ---

  const toggleTarget = (id: string) => {
    setTargetNodeIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  // Filter Logic
  const sourceNodes = sourceCategory
    ? nodes.filter((n) => (n.type || "").toLowerCase() === sourceCategory.toLowerCase())
    : nodes;

  // Filter out the selected source node from targets to prevent self-linking
  const targetNodes = targetCategory
    ? nodes.filter(
        (n) =>
          (n.type || "").toLowerCase() === targetCategory.toLowerCase() && n.id !== sourceNodeId,
      )
    : nodes.filter((n) => n.id !== sourceNodeId);

  return (
    <div className="flex gap-6 h-[calc(100vh-250px)]">
      {/* Help Modal */}
      {showHelp && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={() => setShowHelp(false)}
        >
          <div
            className="bg-surface-900 border border-white/10 rounded-2xl max-w-3xl w-full p-8 shadow-2xl space-y-6 relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setShowHelp(false)}
              className="absolute top-4 right-4 text-neutral-500 hover:text-white"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
            <h2 className="text-2xl font-black text-white uppercase tracking-tight flex items-center gap-2">
              <span className="material-symbols-outlined text-brand-500">school</span>
              Relationship Guide
            </h2>
            {/* Simplified Help Content */}
            <div className="p-4 bg-black/30 text-neutral-400 text-sm rounded-lg">
              Defines how CIs interact. DEPENDS_ON drives the impact analysis.
            </div>
          </div>
        </div>
      )}

      {/* Left Panel: Creator & Controls */}
      <div className="w-1/3 glass p-6 rounded-2xl border border-white/5 flex flex-col gap-6 overflow-y-auto custom-scrollbar">
        <div className="flex items-center justify-between">
          <h3 className="text-xl font-bold text-white uppercase flex items-center gap-2">
            <span className="material-symbols-outlined">hub</span>
            Topology Manager
          </h3>
          <div className="flex bg-black/40 rounded-lg p-1">
            <button
              onClick={() => setViewMode("LINKS")}
              className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${viewMode === "LINKS" ? "bg-brand-500 text-white" : "text-neutral-500 hover:text-white"}`}
            >
              LINKS
            </button>
            <button
              onClick={() => setViewMode("METRICS")}
              className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${viewMode === "METRICS" ? "bg-blue-600 text-white" : "text-neutral-500 hover:text-white"}`}
            >
              METRICS
            </button>
          </div>
        </div>

        {/* 1. Source Selection */}
        <div className="space-y-3 p-4 bg-white/5 rounded-xl border border-white/5">
          <div className="flex items-center gap-2 text-brand-400 font-bold text-xs uppercase tracking-widest">
            <span className="material-symbols-outlined text-sm">output</span>
            1. Select Source (Parent/Host)
          </div>
          <select
            className="w-full bg-black/20 border border-white/10 rounded-lg p-2 text-sm text-white focus:border-brand-500 outline-none"
            value={sourceCategory}
            onChange={(e) => {
              setSourceCategory(e.target.value);
              setSourceNodeId("");
            }}
          >
            <option value="">-- All Categories --</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            className="w-full bg-black/20 border border-white/10 rounded-lg p-2 text-sm text-white focus:border-brand-500 outline-none"
            value={sourceNodeId}
            onChange={(e) => setSourceNodeId(e.target.value)}
          >
            <option value="">-- Select Source CI --</option>
            {sourceNodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.label}
              </option>
            ))}
          </select>
        </div>

        {viewMode === "LINKS" ? (
          <>
            <div className="space-y-2">
              <label className="text-xs text-neutral-500 font-bold uppercase">
                Relationship Type
              </label>
              <select
                className="w-full bg-black/20 border border-white/10 rounded-lg p-2 text-sm text-white outline-none font-mono"
                value={relType}
                onChange={(e) => setRelType(e.target.value)}
              >
                <option value="DEPENDS_ON">DEPENDS_ON (Impact Flow)</option>
                <option value="HOSTED_ON">HOSTED_ON (Containment)</option>
                <option value="CONNECTS_TO">CONNECTS_TO (Network)</option>
              </select>
            </div>

            {/* 2. Target Selection (Multi-select) */}
            <div className="space-y-3 p-4 bg-white/5 rounded-xl border border-white/5 flex-1 flex flex-col min-h-[200px]">
              <div className="flex items-center gap-2 text-accent-cyan font-bold text-xs uppercase tracking-widest">
                <span className="material-symbols-outlined text-sm">input</span>
                2. Select Targets (Deepents)
              </div>
              <div className="flex-1 overflow-y-auto custom-scrollbar bg-black/20 rounded-lg p-2 border border-white/5">
                {targetNodes.map((n) => (
                  <div
                    key={n.id}
                    onClick={() => toggleTarget(n.id)}
                    className={`p-2 rounded cursor-pointer text-xs flex items-center justify-between transition-colors ${targetNodeIds.includes(n.id) ? "bg-accent-cyan/20 text-accent-cyan" : "text-neutral-400 hover:bg-white/5"}`}
                  >
                    <RelationshipTooltip ciId={n.id} relationships={relationshipMap}>
                      <span>{n.label}</span>
                    </RelationshipTooltip>
                    <RelationshipBadge ciId={n.id} relationships={relationshipMap} />
                    {targetNodeIds.includes(n.id) && (
                      <span className="material-symbols-outlined text-sm">check</span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <button
              onClick={handleCreate}
              disabled={loading || !sourceNodeId || targetNodeIds.length === 0}
              className="w-full bg-brand-600 text-white font-bold py-3 rounded-xl uppercase tracking-wider text-xs"
            >
              {loading ? "Processing..." : `Create ${targetNodeIds.length} Links`}
            </button>
          </>
        ) : (
          <>
            {/* Metrics Selection */}
            <div className="space-y-3 p-4 bg-blue-900/10 rounded-xl border border-blue-500/20 flex-1 flex flex-col min-h-[200px]">
              <div className="flex items-center gap-2 text-blue-400 font-bold text-xs uppercase tracking-widest">
                <span className="material-symbols-outlined text-sm">list</span>
                2. Select Metrics to Promote
              </div>
              {!sourceNodeId ? (
                <div className="text-center text-neutral-500 p-4 text-xs">
                  Select a Source Node first
                </div>
              ) : availableMetrics.length === 0 ? (
                <div className="text-center text-neutral-500 p-4 text-xs">
                  No metrics found for this CI
                </div>
              ) : (
                <div className="flex-1 overflow-y-auto custom-scrollbar bg-black/20 rounded-lg p-2 border border-white/5 space-y-1">
                  {availableMetrics.map((m) => (
                    <div
                      key={m.name}
                      onClick={() => {
                        if (selectedMetrics.includes(m.name))
                          setSelectedMetrics((prev) => prev.filter((x) => x !== m.name));
                        else setSelectedMetrics((prev) => [...prev, m.name]);
                      }}
                      className={`p-2 rounded cursor-pointer text-xs flex items-center justify-between transition-colors ${selectedMetrics.includes(m.name) ? "bg-blue-500/20 text-blue-400 border border-blue-500/30" : "text-neutral-400 hover:bg-white/5"}`}
                    >
                      <div className="flex flex-col">
                        <span className="font-bold">{m.name}</span>
                        <span className="opacity-70 text-[10px]">{m.description}</span>
                      </div>
                      {selectedMetrics.includes(m.name) && (
                        <span className="material-symbols-outlined text-sm">check_circle</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <button
              onClick={handlePromoteMetrics}
              disabled={loading || selectedMetrics.length === 0}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl uppercase tracking-wider text-xs flex items-center justify-center gap-2"
            >
              <span className="material-symbols-outlined">upgrade</span>
              Promote {selectedMetrics.length} Metrics
            </button>
          </>
        )}
      </div>

      {/* Right Panel: List/Graph View */}
      <div className="flex-1 glass p-6 rounded-2xl border border-white/5 overflow-hidden flex flex-col gap-6">
        {/* CI Relationships Table */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex items-center justify-between mb-4 gap-4">
            <h3 className="text-sm font-bold text-white uppercase flex items-center gap-2">
              <span className="material-symbols-outlined text-brand-500">hub</span>
              CI Relationships ({filteredCiLinks.length})
            </h3>
            <Link
              to="/admin/relationships/visual-editor"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary text-xs"
            >
              <span className="material-symbols-outlined text-sm">account_tree</span>
              Visual editor
            </Link>
            <div className="relative">
              <span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-neutral-500 text-sm">
                search
              </span>
              <input
                type="text"
                placeholder="Search links..."
                value={searchCiLinks}
                onChange={(e) => setSearchCiLinks(e.target.value)}
                className="bg-black/40 border border-white/10 rounded-lg pl-8 pr-3 py-1.5 text-xs text-neutral-300 placeholder-neutral-600 focus:outline-none focus:border-brand-500/50 w-48 transition-colors"
              />
              {searchCiLinks && (
                <button
                  onClick={() => setSearchCiLinks("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-white"
                >
                  <span className="material-symbols-outlined text-sm">close</span>
                </button>
              )}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar border border-white/5 rounded-lg bg-black/20">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="text-xs text-neutral-500 border-b border-white/10 sticky top-0 bg-surface-900 z-10">
                  <th className="p-3 uppercase tracking-wider">Source</th>
                  <th className="p-3 uppercase tracking-wider text-center">Relationship</th>
                  <th className="p-3 uppercase tracking-wider">Target</th>
                  <th className="p-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {filteredCiLinks.map((link, i) => {
                  const readOnly = isReadOnlyRelationship(link.relationship);
                  const tunnelVisual = isTunnelMedium(link.medium)
                    ? resolveTunnelVisual(link, link.tunnel_health ?? undefined)
                    : null;

                  return (
                    <tr
                      key={i}
                      className="border-b border-white/5 hover:bg-white/5 transition-colors group"
                    >
                      <td className="p-3 font-mono text-brand-400" title={link.source}>
                        {link.source_label || link.source}
                      </td>
                      <td className="p-3 text-center">
                        <span className="text-[10px] font-bold bg-white/10 px-2 py-1 rounded text-neutral-300 uppercase">
                          {link.relationship}
                        </span>
                        {readOnly && (
                          <span className="ml-2 text-[10px] font-bold bg-amber-400/10 px-2 py-1 rounded text-amber-200 uppercase">
                            Read-only
                          </span>
                        )}
                        {tunnelVisual && (
                          <div className="mt-2">
                            <TunnelVisualSummary visual={tunnelVisual} />
                          </div>
                        )}
                      </td>
                      <td className="p-3 font-mono text-accent-cyan" title={link.target}>
                        {link.target_label || link.target}
                      </td>
                      <td className="p-3 text-right flex items-center justify-end gap-2">
                        <button
                          onClick={() => {
                            // Smart Root Selection: Select the "Superior" node as Root
                            // For dependencies, the Target is the Provider (Superior)
                            if (["DEPENDS_ON", "HOSTED_ON"].includes(link.relationship)) {
                              setVisualizationTarget(link.target);
                            } else {
                              setVisualizationTarget(link.source);
                            }
                          }}
                          className="text-neutral-500 hover:text-brand-400 transition-colors"
                          title="Visualize Correlation"
                        >
                          <span className="material-symbols-outlined text-lg">hub</span>
                        </button>
                        {canDeleteRelationship(link.relationship) && (
                          <button
                            onClick={() => handleDelete(link)}
                            className="text-neutral-600 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                          >
                            <span className="material-symbols-outlined text-lg">delete</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {filteredCiLinks.length === 0 && (
                  <tr>
                    <td colSpan={4} className="p-8 text-center text-neutral-500 text-xs">
                      {searchCiLinks
                        ? `No links match "${searchCiLinks}"`
                        : "No CI-to-CI relationships found."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Metric Relationships Table */}
        <div className="flex-1 flex flex-col min-h-0 border-t border-white/10 pt-4">
          <h3 className="text-sm font-bold text-blue-400 uppercase mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined">bar_chart</span>
            Promoted Metrics ({metricLinks.length})
          </h3>
          <div className="flex-1 overflow-y-auto custom-scrollbar border border-white/5 rounded-lg bg-black/20">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="text-xs text-neutral-500 border-b border-white/10 sticky top-0 bg-surface-900 z-10">
                  <th className="p-3 uppercase tracking-wider">Host CI</th>
                  <th className="p-3 uppercase tracking-wider">Metric Node</th>
                  <th className="p-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {metricLinks.map((link, i) => (
                  <tr
                    key={i}
                    className="border-b border-white/5 hover:bg-white/5 transition-colors group"
                  >
                    <td className="p-3 font-mono text-white" title={link.source}>
                      {link.source_label || link.source}
                    </td>
                    <td
                      className="p-3 font-mono text-blue-400 flex items-center gap-2"
                      title={link.target}
                    >
                      <span className="material-symbols-outlined text-xs">analytics</span>
                      {link.target_label || link.target}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => handleDelete(link)}
                        className="text-neutral-600 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                        title="Demote Metric (Delete Node)"
                      >
                        <span className="material-symbols-outlined text-lg">delete</span>
                      </button>
                    </td>
                  </tr>
                ))}
                {metricLinks.length === 0 && (
                  <tr>
                    <td
                      colSpan={3}
                      className="p-8 text-center text-neutral-500 text-xs text-italic"
                    >
                      No promoted metrics found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Visualization Modal */}
      {visualizationTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-xl p-8">
          <div className="w-full h-full max-w-6xl flex flex-col relative">
            <button
              onClick={() => setVisualizationTarget(null)}
              className="absolute top-0 right-0 p-4 text-white hover:text-red-500 z-50"
            >
              <span className="material-symbols-outlined text-3xl">close</span>
            </button>
            <h2 className="text-2xl font-black text-white uppercase tracking-tight flex items-center gap-2 mb-4 absolute top-0 left-0">
              <span className="material-symbols-outlined text-brand-500">hub</span>
              Correlation Explorer
            </h2>
            <div className="flex-1 mt-12 bg-black/20 rounded-2xl border border-white/5 overflow-hidden">
              {/* Uses the extracted TopologyViewer Component */}
              <TopologyViewer rootId={visualizationTarget} nodes={nodes} links={links} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default RelationshipManager;
