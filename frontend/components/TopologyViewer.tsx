/* eslint-disable @typescript-eslint/no-explicit-any */
import React, { useState, useEffect, useRef } from "react";
import { GraphLink, GraphNode } from "../types";
import { isTunnelMedium, resolveTunnelVisual } from "../utils/tunnelVisuals";
import TunnelVisualSummary from "./TunnelVisualSummary";

interface TopologyViewerProps {
  rootId: string;
  nodes: GraphNode[];
  links: any[]; // Consider defining a stricter type for links if possible
}

/**
 * TopologyViewer Component
 *
 * Visualizes the correlation between a Root CI, its Dependencies, and Metrics.
 * Uses a force-directed graph with custom radial constraints to organize nodes into concentric rings.
 *
 * Levels:
 * - Level 0: Root Node (Center)
 * - Level 1: Metrics of Root (Inner Ring)
 * - Level 2: Dependents (Middle Ring)
 * - Level 3: Metrics of Dependents (Outer Ring)
 */
const TopologyViewer: React.FC<TopologyViewerProps> = ({ rootId, nodes, links }) => {
  // Zoom and Pan State
  // Initial zoom k=1.1 for a compact, filled view
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1.1 });
  const [isPanning, setIsPanning] = useState(false);
  const [draggedNode, setDraggedNode] = useState<string | null>(null);
  const [lastPos, setLastPos] = useState({ x: 0, y: 0 });

  // Simulation State
  // Use a ref for simulation state to avoid re-renders during high-frequency physics steps
  const simulationRef = useRef<any>(null);
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] }>({
    nodes: [],
    links: [],
  });
  const tunnelVisuals = graphData.links
    .filter((link) => isTunnelMedium(link.medium))
    .map((link) => ({
      link,
      visual: resolveTunnelVisual(link as GraphLink, link.tunnel_health ?? undefined),
    }));

  // --- Lifecycle: Initialize Simulation and Data ---
  useEffect(() => {
    if (!rootId) return;

    // 1. Prepare Data
    const root = nodes.find((n) => n.id === rootId);
    if (!root) return;

    const relevantNodes = new Map<string, any>();
    // Root is fixed at center (500, 400)
    relevantNodes.set(rootId, {
      ...root,
      level: 0,
      type: "Root",
      x: 500,
      y: 400,
      vx: 0,
      vy: 0,
      fixed: true,
    });

    const relevantLinks: any[] = [];

    // 2. Identify Neighbors (Dependents/Providers)
    links.forEach((l) => {
      // Dependencies (Downstream): Root -> Target
      if (l.source === rootId && l.relationship === "DEPENDS_ON") {
        const target = nodes.find((n) => n.id === l.target);
        if (target) {
          // Level 2 (Outer Ring) for Dependents
          relevantNodes.set(l.target, {
            ...target,
            level: 2,
            type: "Dependent",
            x: 500 + (Math.random() - 0.5) * 500,
            y: 400 + (Math.random() - 0.5) * 500,
            vx: 0,
            vy: 0,
          });
          relevantLinks.push(l);
        }
      }
      // Dependencies (Upstream): Source -> Root
      else if (l.target === rootId && l.relationship === "DEPENDS_ON") {
        const source = nodes.find((n) => n.id === l.source);
        if (source) {
          // Level 2 (Outer Ring) for Dependents (even if upstream, visually treated as satellite)
          relevantNodes.set(l.source, {
            ...source,
            level: 2,
            type: "Dependent",
            x: 500 + (Math.random() - 0.5) * 500,
            y: 400 + (Math.random() - 0.5) * 500,
            vx: 0,
            vy: 0,
          });
          relevantLinks.push(l);
        }
      }
    });

    // 3. Find Metrics for Root AND Neighbors
    links.forEach((l) => {
      if (l.relationship === "HAS_METRIC") {
        const sourceNode = relevantNodes.get(l.source); // The Host CI
        if (sourceNode) {
          const target = nodes.find((n) => n.id === l.target); // The Metric Node
          if (target) {
            // Level Logic:
            // If parent is Root (L0) -> Metric is L1 (Inner Ring)
            // If parent is Dependent (L2) -> Metric is L3 (Far Outer Ring)
            const metricLevel = sourceNode.level === 0 ? 1 : 3;

            relevantNodes.set(l.target, {
              ...target,
              level: metricLevel,
              type: "Metric",
              x: sourceNode.x + (Math.random() - 0.5) * 50,
              y: sourceNode.y + (Math.random() - 0.5) * 50,
              vx: 0,
              vy: 0,
            });

            // Reverse Link for Visual Flow: Metric -> CI (Input Flow)
            relevantLinks.push({ ...l, source: l.target, target: l.source });
          }
        }
      }
    });

    const initialNodes = Array.from(relevantNodes.values());

    // 4. Initialize Physics Model (Simple Force Directed)
    const sim = {
      nodes: initialNodes,
      links: relevantLinks,
      running: true,
    };
    simulationRef.current = sim;

    // Physics Loop (Tick)
    const tick = () => {
      if (!simulationRef.current?.running) return;
      const nodes = simulationRef.current.nodes;
      const links = simulationRef.current.links;

      const width = 1000;
      const height = 800;
      const center = { x: width / 2, y: height / 2 };

      // --- Physics Parameters ---
      // Tuned for Compact Layout
      const REPULSION = 2000; // Moderate repulsion to prevent overlap but allow clustering
      const SPRING_K = 0.04; // Spring stiffness
      const RADIAL_K = 0.1; // Strength of radial orbit constraint
      const DAMPING = 0.8; // Velocity decay

      // Target Radius per Level (Ultra Compact concentric rings)
      const getRadius = (level: number) => {
        switch (level) {
          case 0:
            return 0; // Root (Center)
          case 1:
            return 80; // Metrics of Root (Inner Orbit)
          case 2:
            return 160; // Dependents (Middle Orbit)
          case 3:
            return 240; // Metrics of Dependents (Outer Orbit)
          default:
            return 200;
        }
      };

      // 1. Repulsion (Coulomb's Law)
      // Push nodes away from each other
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const distSq = dx * dx + dy * dy || 0.1;
          const force = REPULSION / distSq;
          const dist = Math.sqrt(distSq);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          if (!a.fixed && !a.dragged) {
            a.vx += fx;
            a.vy += fy;
          }
          if (!b.fixed && !b.dragged) {
            b.vx -= fx;
            b.vy -= fy;
          }
        }
      }

      // 2. Radial Force (Orbit Constraints)
      // Pull nodes towards their target radius ring
      nodes.forEach((n: any) => {
        if (n.fixed || n.dragged) return;

        const dx = n.x - center.x;
        const dy = n.y - center.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetR = getRadius(n.level || 0);

        // Spring force towards the target radius
        const force = (targetR - dist) * RADIAL_K;
        const fx = (dx / dist) * force; // Push OUT if targetR > dist, IN if targetR < dist
        const fy = (dy / dist) * force;

        n.vx += fx;
        n.vy += fy;
      });

      // 3. Attraction (Hooke's Law)
      // Pull connected nodes together based on link type
      links.forEach((link: any) => {
        const s = nodes.find((n: any) => n.id === link.source);
        const t = nodes.find((n: any) => n.id === link.target);
        if (!s || !t) return;

        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;

        // Variable Spring Length based on Node Type
        let springLength = 140; // Default Structural

        // If link involves a Metric, keep it extremely close to its Host
        if (s.type === "Metric" || t.type === "Metric") {
          springLength = 100;
        } else {
          springLength = 140;
        }

        // Force calculation
        const force = (dist - springLength) * SPRING_K;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;

        if (!s.fixed && !s.dragged) {
          s.vx += fx;
          s.vy += fy;
        }
        if (!t.fixed && !t.dragged) {
          t.vx -= fx;
          t.vy -= fy;
        }
      });

      // 4. Update Positions & Apply Damping
      nodes.forEach((n: any) => {
        if (n.fixed || n.dragged) return;

        n.vx *= 0.8; // Apply damping to velocity
        n.vy *= 0.8;

        n.x += n.vx;
        n.y += n.vy;

        // Apply global damping constant (if used differently than above, but here matched logic)
        n.vx *= DAMPING;
        n.vy *= DAMPING;
      });

      setGraphData({ nodes: [...nodes], links }); // Trigger React render
      requestAnimationFrame(tick);
    };

    tick();

    return () => {
      if (simulationRef.current) simulationRef.current.running = false;
    };
  }, [rootId, nodes, links]);

  // --- Interaction Handlers ---

  const handleWheel = (e: React.WheelEvent) => {
    const scaleAmount = -e.deltaY * 0.001;
    const newScale = Math.min(Math.max(0.1, transform.k * (1 + scaleAmount)), 4);
    setTransform((prev) => ({ ...prev, k: newScale }));
  };

  const handleNodeMouseDown = (e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    setDraggedNode(nodeId);
    setLastPos({ x: e.clientX, y: e.clientY });

    // Mark node as dragged in simulation so physics doesn't overwrite mouse position
    if (simulationRef.current) {
      const node = simulationRef.current.nodes.find((n: any) => n.id === nodeId);
      if (node) node.dragged = true;
    }
  };

  const handleCanvasMouseDown = (e: React.MouseEvent) => {
    setIsPanning(true);
    setLastPos({ x: e.clientX, y: e.clientY });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    const dx = e.clientX - lastPos.x;
    const dy = e.clientY - lastPos.y;
    setLastPos({ x: e.clientX, y: e.clientY });

    if (draggedNode && simulationRef.current) {
      const node = simulationRef.current.nodes.find((n: any) => n.id === draggedNode);
      if (node) {
        // Update position directly and zero velocity
        node.x += dx / transform.k;
        node.y += dy / transform.k;
        node.vx = 0;
        node.vy = 0;
      }
    } else if (isPanning) {
      setTransform((prev) => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
    }
  };

  const handleMouseUp = () => {
    if (draggedNode && simulationRef.current) {
      const node = simulationRef.current.nodes.find((n: any) => n.id === draggedNode);
      if (node) node.dragged = false;
    }
    setIsPanning(false);
    setDraggedNode(null);
  };

  // --- Render ---
  return (
    <div
      className="w-full h-full bg-black/40 relative overflow-hidden"
      onWheel={handleWheel}
      onMouseDown={handleCanvasMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{ cursor: isPanning ? "grabbing" : "grab" }}
    >
      <svg width="100%" height="100%" viewBox="0 0 1000 800">
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          <defs>
            <style>
              {`
                                @keyframes flow {
                                    to { stroke-dashoffset: -20; }
                                }
                                .flow-animation {
                                    animation: flow 1s linear infinite;
                                }
                            `}
            </style>
            <marker
              id="arrow-blue"
              viewBox="0 -5 10 10"
              refX="22"
              refY="0"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0,-5L10,0L0,5" fill="#3b82f6" />
            </marker>
            <marker
              id="arrow-green"
              viewBox="0 -5 10 10"
              refX="22"
              refY="0"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0,-5L10,0L0,5" fill="#10b981" />
            </marker>
          </defs>

          {/* Ring Guides (Visual Only) */}
          <circle
            cx="500"
            cy="400"
            r="160"
            fill="none"
            stroke="#ffffff"
            strokeOpacity="0.05"
            strokeDasharray="5,5"
            strokeWidth={1}
          />
          <circle
            cx="500"
            cy="400"
            r="240"
            fill="none"
            stroke="#ffffff"
            strokeOpacity="0.02"
            strokeDasharray="5,5"
            strokeWidth={1}
          />

          {/* Links */}
          {graphData.links.map((link, i) => {
            const s = graphData.nodes.find((n) => n.id === link.source);
            const t = graphData.nodes.find((n) => n.id === link.target);
            if (!s || !t) return null;

            let strokeColor = "#fff";
            let markerId = "";

            if (link.relationship === "HAS_METRIC") {
              strokeColor = "#3b82f6";
              markerId = "url(#arrow-blue)";
            } else {
              strokeColor = "#10b981"; // Outgoing
              markerId = "url(#arrow-green)";
            }

            return (
              <g key={i}>
                <line
                  x1={s.x}
                  y1={s.y}
                  x2={t.x}
                  y2={t.y}
                  stroke={strokeColor}
                  strokeOpacity={0.2}
                  strokeWidth={1}
                  markerEnd={markerId}
                />
                <line
                  x1={s.x}
                  y1={s.y}
                  x2={t.x}
                  y2={t.y}
                  stroke={strokeColor}
                  strokeOpacity={0.8}
                  strokeWidth={2}
                  strokeDasharray="4,6"
                  className="flow-animation"
                />
              </g>
            );
          })}
          {/* Nodes */}
          {graphData.nodes.map((node, i) => {
            let color = "#fff";
            if (node.level === 0)
              color = "#ef4444"; // Root
            else if (node.level === 1)
              color = "#10b981"; // Root Metric
            else if (node.level === 3)
              color = "#f59e0b"; // Dependent Metric
            else if (node.level === 2) color = "#3b82f6"; // Dependent

            return (
              <g
                key={i}
                transform={`translate(${node.x},${node.y})`}
                onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
                style={{ cursor: "pointer" }}
              >
                <circle r={node.level === 0 ? 12 : 8} fill={color} stroke="white" strokeWidth={2} />
                <text
                  y={-15}
                  textAnchor="middle"
                  fill="white"
                  fontSize={12}
                  fontWeight="bold"
                  className="pointer-events-none drop-shadow-md select-none"
                >
                  {node.label || node.display_name || node.name || node.id}
                </text>
                <text
                  y={15}
                  textAnchor="middle"
                  fill="rgba(255,255,255,0.6)"
                  fontSize={10}
                  className="pointer-events-none select-none"
                >
                  {node.level === 0
                    ? "ROOT"
                    : node.level === 1
                      ? "METRIC"
                      : node.level === 2
                        ? "DEPENDENT"
                        : "METRIC"}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {tunnelVisuals.length > 0 && (
        <div className="absolute top-4 right-4 max-w-xs space-y-2 pointer-events-none">
          {tunnelVisuals.map(({ link, visual }) => (
            <TunnelVisualSummary
              key={link.id ?? `${link.source}-${link.target}-${link.relationship}`}
              title={`${link.source} → ${link.target}`}
              visual={visual}
            />
          ))}
        </div>
      )}

      {/* Legend Overlay */}
      <div className="absolute top-4 left-4 space-y-2 pointer-events-none">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-red-500 border border-white"></div>
          <span className="text-xs text-white shadow-black drop-shadow-md">Selected CI (Root)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-blue-500 border border-white"></div>
          <span className="text-xs text-white shadow-black drop-shadow-md">
            Downstream (Dependents)
          </span>
        </div>
        {/* <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-amber-500 border border-white"></div>
                    <span className="text-xs text-white shadow-black drop-shadow-md">Related Metrics</span>
                </div> */}
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-emerald-500 border border-white"></div>
          <span className="text-xs text-white shadow-black drop-shadow-md">Attached Metrics</span>
        </div>
      </div>

      <div className="absolute bottom-4 left-4 bg-black/60 p-2 rounded text-xs text-neutral-400 font-mono pointer-events-none">
        Graph Physics Enabled • Drag Nodes to Rearrange
      </div>
    </div>
  );
};

export default TopologyViewer;
