
import React, { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import { GraphNode, GraphLink } from '../types';
import { STATUS_COLORS } from '../utils/status';

interface GraphCMDBProps {
  nodes: GraphNode[];
  links: GraphLink[];
  onNodeClick: (node: GraphNode) => void;
}

/**
 * GraphCMDB Component
 * 
 * Visualizes the topology of Configuration Items (CIs) and their relationships using D3.js.
 * Implements force-directed graph with auto-centering and status-based coloring.
 */
const GraphCMDB: React.FC<GraphCMDBProps> = ({ nodes, links, onNodeClick }) => {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current) return;

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    // Define Arrow Markers
    const defs = svg.append("defs");
    Object.values(STATUS_COLORS).forEach(color => {
      const idColor = color.replace('#', '');
      defs.append("marker")
        .attr("id", `arrow-${idColor}`)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 28) // Position at edge of node (r=24 + padding)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", color);
    });

    // Filter links to ensure valid source/target
    const validLinks = links.filter(l => {
      const sourceId = typeof l.source === 'object' ? (l.source as any).id : l.source;
      const targetId = typeof l.target === 'object' ? (l.target as any).id : l.target;
      return nodes.some(n => n.id === sourceId) && nodes.some(n => n.id === targetId);
    }).map(d => Object.create(d)); // Create shallow copy for D3 mutation

    const validNodes = nodes.map(d => Object.create(d)); // Create shallow copy for D3 mutation

    // --- Calculate Impact Analysis (Affected Derived Tree) ---
    const criticalNodeIds = validNodes.filter(n => n.status === 'CRITICAL' || n.status === 'WARNING').map(n => n.id);
    const affectedSet = new Set<string>(criticalNodeIds);
    let added = true;
    while (added) {
      added = false;
      validLinks.forEach(l => {
        const sId = typeof l.source === 'object' ? (l.source as any).id : l.source;
        const tId = typeof l.target === 'object' ? (l.target as any).id : l.target;

        // In typical CMDB dependencies, Target failing impacts the Source that depends on it
        if (affectedSet.has(tId) && !affectedSet.has(sId)) {
          affectedSet.add(sId);
          added = true;
        }
      });
    }
    const hasGlobalIncidents = criticalNodeIds.length > 0;

    const simulation = d3.forceSimulation<GraphNode>(validNodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(validLinks).id(d => d.id).distance(150))
      .force("charge", d3.forceManyBody().strength(-500))
      .force("center", d3.forceCenter(width / 2, height / 2));

    const link = svg.append("g")
      .selectAll("line")
      .data(validLinks)
      .join("line")
      .attr("stroke-opacity", (d: any) => {
        if (!hasGlobalIncidents) return 0.6;
        const sId = typeof d.source === 'object' ? (d.source as any).id : d.source;
        const tId = typeof d.target === 'object' ? (d.target as any).id : d.target;
        return (affectedSet.has(sId) || affectedSet.has(tId)) ? 0.9 : 0.2;
      })
      .attr("stroke-width", 2)
      .attr("stroke", (d: any) => {
        // Color link based on TARGET node status for dependency impact visualization
        const targetStatus = d.target?.status || 'UNKNOWN';
        if (targetStatus === 'CRITICAL') return STATUS_COLORS.CRITICAL;
        if (targetStatus === 'WARNING') return STATUS_COLORS.WARNING;
        if (targetStatus === 'ACTIVE' || targetStatus === 'OK') return STATUS_COLORS.OK;
        return STATUS_COLORS.UNKNOWN;
      })
      .attr("marker-end", (d: any) => {
        const targetStatus = d.target?.status || 'UNKNOWN';
        let color = STATUS_COLORS.UNKNOWN;
        if (targetStatus === 'CRITICAL') color = STATUS_COLORS.CRITICAL;
        else if (targetStatus === 'WARNING') color = STATUS_COLORS.WARNING;
        else if (targetStatus === 'ACTIVE' || targetStatus === 'OK') color = STATUS_COLORS.OK;

        return `url(#arrow-${color.replace('#', '')})`;
      })
      .attr("stroke-dasharray", (d: any) => {
        if (d.relationship === 'DEPENDS_ON') return "5, 8";
        if (d.relationship === 'CONNECTS_TO') return "none"; // Base is solid now
        if (d.relationship === 'HOSTED_ON') return "2, 2";
        return "none";
      })
      .attr("class", (d: any) => {
        if (d.relationship === 'DEPENDS_ON') return "flow-animation";
        return "";
      });

    // Extra layer for Traffic connecting lines
    const trafficLink = svg.append("g")
      .selectAll("line")
      .data(validLinks.filter((d: any) => d.relationship === 'CONNECTS_TO'))
      .join("line")
      .attr("stroke-width", 3)
      .attr("stroke", "#10b981") // Traffic blast
      .attr("stroke-dasharray", "5, 50")
      .attr("class", "traffic-animation")
      .attr("opacity", 0.7)
      .style("pointer-events", "none");

    const node = svg.append("g")
      .selectAll("g")
      .data(validNodes)
      .join("g")
      .attr("class", "cursor-pointer group")
      .attr("opacity", d => {
        if (!hasGlobalIncidents) return 1;
        return affectedSet.has(d.id) ? 1 : 0.4; // Expose healthy nodes at 40% instead of 5%
      })
      .on("click", (event, d) => onNodeClick(d))
      .call(d3.drag<SVGGElement, GraphNode>()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended) as any);

    // Node circles with health indicators
    node.append("circle")
      .attr("r", d => d.status === 'CRITICAL' ? 32 : d.status === 'WARNING' ? 28 : 24)
      .attr("fill", "#1a1a1a")
      .attr("stroke", d => {
        if (d.status === 'CRITICAL') return STATUS_COLORS.CRITICAL;
        if (d.status === 'WARNING') return STATUS_COLORS.WARNING;
        if (affectedSet.has(d.id)) return '#f97316'; // Orange for derived affected tree
        return '#345bf2'; // Brand Color for safe nodes
      })
      .attr("stroke-width", d => affectedSet.has(d.id) || d.status === 'CRITICAL' ? 4 : 2)
      .attr("class", d => affectedSet.has(d.id) ? 'animate-pulse' : '');

    // Node icons (simplified labels for now)
    node.append("text")
      .attr("dy", ".35em")
      .attr("text-anchor", "middle")
      .attr("fill", "white")
      .attr("font-size", "10px")
      .attr("font-weight", "bold")
      .text(d => d.label.substring(0, 3).toUpperCase());

    // Labels
    node.append("text")
      .attr("dy", "3.5em")
      .attr("text-anchor", "middle")
      .attr("fill", "#a3a3a3")
      .attr("font-size", "11px")
      .text(d => d.label);

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);

      trafficLink
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);

      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    function dragstarted(event: any) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }

    function dragged(event: any) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }

    function dragended(event: any) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }

    return () => simulation.stop();
  }, [nodes, links, onNodeClick]);

  return (
    <div className="w-full h-full relative overflow-hidden bg-surface-950 grid-bg">
      <svg ref={svgRef} className="w-full h-full" />
      <div className="absolute bottom-4 left-4 flex flex-col gap-2 p-3 glass rounded-lg text-xs pointer-events-none select-none">
        <div className="flex items-center gap-2"><div className="w-3 h-3 bg-brand-500 rounded-full"></div> Healthy CI</div>
        <div className="flex items-center gap-2"><div className="w-3 h-3 bg-orange-500 rounded-full"></div> Performance Warning</div>
        <div className="flex items-center gap-2"><div className="w-3 h-3 bg-red-500 rounded-full"></div> Critical Impact</div>
        <div className="h-px bg-white/10 my-1"></div>
        <div className="flex items-center gap-2"><div className="w-8 h-0.5 bg-emerald-500"></div> Connection OK</div>
        <div className="flex items-center gap-2"><div className="w-8 h-0.5 bg-red-500"></div> Critical Path</div>
      </div>
    </div>
  );
};

export default GraphCMDB;
