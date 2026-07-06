/* eslint-disable @typescript-eslint/no-explicit-any, no-console */
import React, { useState, useEffect, useRef, useMemo } from "react";
import ForceGraph3D from "react-force-graph-3d";
import CategoryIcon from "./CategoryIcon";
import { useVisibleTunnelHealth } from "../hooks/queries/useVisibleTunnelHealth";
import { encodeTunnelLinkId, isTunnelMedium, resolveTunnelVisual } from "../utils/tunnelVisuals";
import TunnelVisualSummary from "./TunnelVisualSummary";
// import SpriteText from 'three-spritetext'; // Optional for text labels if needed

const NetworkVisualizer: React.FC = () => {
  const [nodes, setNodes] = useState<any[]>([]); // Using any[] to support diverse node types
  const [links, setLinks] = useState<any[]>([]);
  const [showCIs, setShowCIs] = useState(false); // Default: Hide CIs
  const fgRef = useRef<any>(null);

  const isZoomed = useRef(false);

  const fetchData = () => {
    fetch("/api/graph/full")
      .then((res) => res.json())
      .then((data) => {
        setNodes((prevNodes) => {
          if (JSON.stringify(prevNodes) === JSON.stringify(data.nodes)) return prevNodes;
          return data.nodes;
        });
        setLinks((prevLinks) => {
          if (JSON.stringify(prevLinks) === JSON.stringify(data.links)) return prevLinks;
          return data.links;
        });
      })
      .catch((err) => console.error("Failed to load graph data:", err));
  };

  useEffect(() => {
    fetchData(); // Initial Fetch
    const interval = setInterval(fetchData, 5000); // Poll every 5s
    return () => clearInterval(interval);
  }, []);

  const graphData = useMemo(() => {
    if (showCIs) return { nodes, links };

    // Filter logic: Hide CIs if showCIs is false
    const activeNodes = nodes.filter((n) => n.type !== "CI");
    const activeNodeIds = new Set(activeNodes.map((n) => n.id));
    const activeLinks = links.filter((l) => {
      const sourceId = typeof l.source === "object" ? l.source.id : l.source;
      const targetId = typeof l.target === "object" ? l.target.id : l.target;
      return activeNodeIds.has(sourceId) && activeNodeIds.has(targetId);
    });

    return { nodes: activeNodes, links: activeLinks };
  }, [nodes, links, showCIs]);

  const technologyNodes = useMemo(() => {
    return graphData.nodes.filter(
      (node) =>
        node.category_icon_key || node.category || node.type === "Category" || node.type === "CI",
    );
  }, [graphData.nodes]);

  const tunnelHealth = useVisibleTunnelHealth(graphData.links);
  const tunnelVisuals = useMemo(() => {
    return graphData.links
      .filter((link) => isTunnelMedium(link.medium))
      .map((link) => {
        const linkId = encodeTunnelLinkId(link);
        const visual =
          tunnelHealth.visualByLinkId[linkId] ??
          resolveTunnelVisual(link, link.tunnel_health ?? undefined);
        return { link, visual };
      });
  }, [graphData.links, tunnelHealth.visualByLinkId]);

  const getTechnologyCategoryName = (node: any) => {
    if (node.category) return node.category;
    if (node.type === "Category") return node.label;
    return node.type;
  };

  // Apply custom forces when graph loads
  useEffect(() => {
    if (fgRef.current) {
      // Apply compactness forces
      fgRef.current.d3Force("charge").strength(-120);
      fgRef.current.d3Force("link").distance(50);
      fgRef.current.d3Force("center").strength(1.2);
    }
  }, [graphData]);

  // Node Color by Type (NEON PALETTE)
  const getNodeColor = (node: any) => {
    switch (node.type) {
      case "CI":
        if (node.status === "CRITICAL") return "#ff0055"; // Neon Red
        if (node.status === "WARNING") return "#ffcc00"; // Neon Yellow
        return "#00ff99"; // Neon Green
      case "Category":
        return "#00d4ff"; // Neon Cyan
      case "Owner":
        return "#bf00ff"; // Neon Purple
      case "Metric":
        return "#ff00aa"; // Neon Pink
      case "Hardware":
        return "#ff6600"; // Neon Orange
      case "User":
        return "#00ffcc"; // Electric Teal
      default:
        return "#888888"; // Silver
    }
  };

  // Node Size by Type
  const getNodeVal = (node: any) => {
    switch (node.type) {
      case "Category":
        return 40; // Much larger Hubs
      case "Owner":
        return 30;
      case "Hardware":
        return 25;
      case "Metric":
        return 20;
      case "User":
        return 20;
      case "CI":
        return 15;
      default:
        return 10;
    }
  };

  return (
    <div className="h-full w-full bg-black relative">
      <div className="absolute top-8 left-8 z-50 pointer-events-none">
        <h2
          className="text-3xl font-black text-white tracking-widest uppercase mb-2"
          style={{ textShadow: "0 0 20px rgba(0,255,255,0.5)" }}
        >
          NEURAL TOPOLOGY
        </h2>
        <p className="text-xs text-cyan-400 font-mono tracking-widest bg-black/50 p-2 rounded border border-cyan-900/30 backdrop-blur-sm inline-block">
          NODES: {graphData.nodes.length} | LINKS: {graphData.links.length}
        </p>

        <div className="mt-4 pointer-events-auto">
          <button
            onClick={() => setShowCIs(!showCIs)}
            className={`px-4 py-2 text-xs font-bold uppercase tracking-widest border rounded transition-all ${
              showCIs
                ? "bg-emerald-500/20 border-emerald-500 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.4)]"
                : "bg-neutral-800/80 border-neutral-600 text-neutral-400 hover:border-neutral-400"
            }`}
          >
            {showCIs ? "HIDE INFRASTRUCTURE (CIs)" : "SHOW INFRASTRUCTURE (CIs)"}
          </button>
        </div>
      </div>

      {tunnelVisuals.length > 0 && (
        <div className="absolute left-8 bottom-8 z-50 max-w-sm space-y-2 pointer-events-none">
          {tunnelHealth.pollingDisabled && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 p-2 text-xs font-bold text-amber-200">
              Live tunnel health disabled
            </div>
          )}
          {tunnelVisuals.map(({ link, visual }) => (
            <TunnelVisualSummary
              key={link.id ?? `${link.source}-${link.target}-${link.relationship}`}
              title={`${link.source} → ${link.target}`}
              visual={visual}
            />
          ))}
        </div>
      )}

      <ForceGraph3D
        ref={fgRef}
        graphData={graphData}
        nodeLabel="label"
        nodeColor={getNodeColor}
        nodeVal={getNodeVal}
        nodeRelSize={1.5} // Slightly larger relative size
        nodeOpacity={1.0}
        nodeResolution={32} // Higher quality spheres
        // Force Engine Configuration
        d3VelocityDecay={0.3}
        cooldownTicks={100}
        onEngineStop={() => {
          // Zoom to fit ONLY ONCE (initial load)
          if (!isZoomed.current) {
            fgRef.current?.zoomToFit(1000, 50);
            isZoomed.current = true;
          }
        }}
        // Links
        linkDirectionalParticles={4}
        linkDirectionalParticleSpeed={() => 0.005}
        linkDirectionalParticleWidth={3}
        linkColor={() => "rgba(255,255,255,0.3)"} // Brighter links
        linkWidth={1.5}
        // Environment
        backgroundColor="#050510" // Deep Navy/Black (Better contrast than pure black)
        showNavInfo={false}
      />

      <div className="absolute bottom-8 right-8 z-50 text-right pointer-events-none">
        <div className="flex flex-col gap-2 bg-black/60 p-4 rounded-lg backdrop-blur-md border border-white/10">
          <h4 className="text-xs font-bold text-white uppercase mb-2 border-b border-white/10 pb-1">
            Legend
          </h4>

          <div className="flex items-center justify-end gap-2">
            <span className="w-3 h-3 rounded-full bg-[#00d4ff] shadow-[0_0_10px_#00d4ff]"></span>
            <span className="text-[10px] font-bold text-neutral-300 uppercase">Category</span>
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="w-3 h-3 rounded-full bg-[#00ff99] shadow-[0_0_10px_#00ff99]"></span>
            <span className="text-[10px] font-bold text-neutral-300 uppercase">CI (Active)</span>
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="w-3 h-3 rounded-full bg-[#bf00ff] shadow-[0_0_10px_#bf00ff]"></span>
            <span className="text-[10px] font-bold text-neutral-300 uppercase">Owner Group</span>
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="w-3 h-3 rounded-full bg-[#ff6600] shadow-[0_0_10px_#ff6600]"></span>
            <span className="text-[10px] font-bold text-neutral-300 uppercase">Hardware Model</span>
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="w-3 h-3 rounded-full bg-[#ff00aa] shadow-[0_0_10px_#ff00aa]"></span>
            <span className="text-[10px] font-bold text-neutral-300 uppercase">Metric Def</span>
          </div>

          {technologyNodes.length > 0 && (
            <div className="mt-3 border-t border-white/10 pt-2">
              <h5 className="mb-2 text-[10px] font-bold uppercase text-cyan-300">
                Technology Icons
              </h5>
              <div className="flex max-h-32 flex-col gap-1 overflow-hidden">
                {technologyNodes.map((node) => (
                  <div
                    key={`technology-${node.id}`}
                    className="flex items-center justify-end gap-2"
                  >
                    <span className="max-w-28 truncate text-[10px] font-bold uppercase text-neutral-300">
                      {node.label}
                    </span>
                    <CategoryIcon
                      iconKey={node.category_icon_key}
                      categoryName={getTechnologyCategoryName(node)}
                      className="text-[16px] leading-none text-cyan-300"
                    />
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

export default NetworkVisualizer;
