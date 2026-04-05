
import { useEffect, useRef, RefObject } from 'react';
import { createPortal } from 'react-dom';
import * as d3 from 'd3';
import { GraphNode, GraphLink } from '../types';
import { STATUS_COLORS } from '../utils/status';
import { api } from '../services/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TopologyResponse {
  nodes: GraphNode[];
  links: GraphLink[];
}

interface GraphCMDBProps {
  nodes: GraphNode[];
  links: GraphLink[];
  onNodeClick: (node: GraphNode) => void;
}

interface AnimatedLinksLayerProps {
  svgRef: RefObject<SVGSVGElement | null>;
  /** Stable ref that holds the latest graph data — never causes re-renders */
  dataRef: RefObject<TopologyResponse | null>;
  /** Callback ref set by GraphCMDB so AnimatedLinksLayer can register its D3 updater */
  onD3UpdaterReady: RefObject<((links: GraphLink[]) => void) | null>;
}

// ---------------------------------------------------------------------------
// useGraphData — polling hook
// ---------------------------------------------------------------------------

/**
 * useGraphData
 *
  * Polls /api/graph/full every `intervalMs` milliseconds.
 * Data is stored exclusively in a Ref — no React state is ever updated,
 * so polling never triggers a component re-render.
 *
 * The `onNewData` callback ref is called with the fresh payload so that
 * D3 visualizations can update their DOM directly.
 *
 * @param onNewData - Stable RefObject pointing to a D3 updater fn (or null)
 * @param intervalMs - Polling interval in milliseconds (default 30 000)
 * @returns dataRef — a Ref always containing the latest topology data
 */
function useGraphData(
  onNewData: RefObject<((data: TopologyResponse) => void) | null>,
  intervalMs = 30_000,
): RefObject<TopologyResponse | null> {
  const dataRef = useRef<TopologyResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchTopology = async () => {
      try {
        const data = await api.get<TopologyResponse>('/graph/full');
        if (cancelled || !data) return;

        // Store latest data in ref — no setState, no re-render
        dataRef.current = data;

        // Notify D3 updater if one is registered
        onNewData.current?.(data);
      } catch (err) {
        // Network / auth errors are handled by api.ts (401 → redirect, etc.)
        console.error('[useGraphData] fetch error:', err);
      }
    };

    // Kick off immediately, then repeat on interval
    fetchTopology();
    const intervalId = setInterval(fetchTopology, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [onNewData, intervalMs]); // onNewData is a stable ref, intervalMs is a primitive

  return dataRef;
}

/**
 * AnimatedLinksLayer Component
 *
 * Renders animated D3 link overlays via React Portal into #d3-portal-root.
 * This component is intentionally decoupled from React's render cycle:
 * - useRef provides direct DOM access without triggering re-renders
 * - useEffect with empty dependency array initializes D3 animations once on mount
 *
 * Portal ensures the SVG overlay sits outside the React component tree,
 * preventing React reconciliation from interfering with D3 mutations.
 *
 * Polling integration:
 * - onD3UpdaterReady receives a D3 update function after mount.
 * - When useGraphData fetches new data it calls that function directly,
 *   updating pulse circle counts via DOM mutation — zero React re-renders.
 */
const AnimatedLinksLayer = ({ svgRef, dataRef, onD3UpdaterReady }: AnimatedLinksLayerProps) => {
  const portalSvgRef = useRef<SVGSVGElement>(null);

  // Initialize D3 animations once — intentionally empty dep array
  // to prevent D3 from being re-initialized on every React render
  useEffect(() => {
    const portalRoot = document.getElementById('d3-portal-root');
    if (!portalRoot || !portalSvgRef.current || !svgRef.current) return;

    // Mirror the host SVG dimensions via direct DOM access (no React state)
    const hostRect = svgRef.current.getBoundingClientRect();
    const portalSvg = d3.select(portalSvgRef.current)
      .attr('width', hostRect.width)
      .attr('height', hostRect.height)
      .style('position', 'absolute')
      .style('top', `${hostRect.top + window.scrollY}px`)
      .style('left', `${hostRect.left + window.scrollX}px`)
      .style('pointer-events', 'none')
      .style('overflow', 'visible');

    // D3 pulse animation group — lives entirely outside React tree
    const pulseGroup = portalSvg.append('g').attr('class', 'd3-pulse-layer');

    /**
     * renderPulseMarkers
     *
     * Performs a D3 data-join on CONNECTS_TO links.
     * Called once on mount (with initial links from dataRef) and then
     * directly from the polling callback whenever new data arrives —
     * without ever going through React's render cycle.
     */
    const renderPulseMarkers = (links: GraphLink[]) => {
      const CONNECTS_TO = links.filter((l: any) => l.relationship === 'CONNECTS_TO');

      // D3 key-join so existing circles are reused, new ones are added,
      // removed ones are cleaned up — all as direct DOM mutations.
      pulseGroup
        .selectAll<SVGCircleElement, GraphLink>('circle')
        .data(CONNECTS_TO, (d: any) => d.id)
        .join(
          enter => enter.append('circle')
            .attr('r', 5)
            .attr('fill', '#10b981')
            .attr('opacity', 0.8),
          update => update, // no attribute change needed on update
          exit => exit.remove(),
        );
    };

    // Seed with whatever data is already in the ref (may be null on very first render)
    const initialLinks = dataRef.current?.links ?? [];
    renderPulseMarkers(initialLinks);

    // Register the D3 updater so useGraphData can call it directly on poll
    onD3UpdaterReady.current = (links: GraphLink[]) => renderPulseMarkers(links);

    // Sync portal SVG position on window resize via direct DOM — no React state
    const handleResize = () => {
      if (!svgRef.current || !portalSvgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      d3.select(portalSvgRef.current)
        .attr('width', rect.width)
        .attr('height', rect.height)
        .style('top', `${rect.top + window.scrollY}px`)
        .style('left', `${rect.left + window.scrollX}px`);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      // Unregister updater and clean up DOM — bypasses React reconciliation intentionally
      onD3UpdaterReady.current = null;
      portalSvg.selectAll('*').remove();
    };
  }, []); // Empty array: D3 owns this DOM subtree after mount

  const portalRoot = document.getElementById('d3-portal-root');
  if (!portalRoot) return null;

  return createPortal(
    <svg ref={portalSvgRef} style={{ position: 'absolute', pointerEvents: 'none' }} />,
    portalRoot
  );
};

/**
 * GraphCMDB Component
 *
 * Visualizes the topology of Configuration Items (CIs) and their relationships using D3.js.
 * Implements force-directed graph with auto-centering and status-based coloring.
 *
 * Polling architecture:
  * - useGraphData polls /api/graph/full every 30 s and stores data in a Ref.
 * - d3UpdaterRef is a callback ref bridging useGraphData → AnimatedLinksLayer.
 *   When new data arrives, useGraphData calls d3UpdaterRef.current(data) which
 *   updates the pulse markers directly in the D3 DOM — no React state, no re-renders.
 * - The force-simulation (nodes / links props) can still be driven externally;
 *   the polling data augments it without replacing the prop-driven flow.
 */
const GraphCMDB = ({ nodes, links, onNodeClick }: GraphCMDBProps) => {
  const svgRef = useRef<SVGSVGElement>(null);

  // Ref that AnimatedLinksLayer will populate with its D3 updater function
  const d3UpdaterRef = useRef<((links: GraphLink[]) => void) | null>(null);

  // Adapter: useGraphData calls back with TopologyResponse; we forward only links to D3.
  // Assigned inline (not in useEffect) so it always captures the latest d3UpdaterRef
  // without creating a new function reference on every render (React Compiler handles this).
  const onNewDataRef = useRef<((data: TopologyResponse) => void) | null>(null);
  onNewDataRef.current = (data: TopologyResponse) => {
    d3UpdaterRef.current?.(data.links);
  };

  // Start polling — dataRef holds the latest snapshot without triggering re-renders
  const dataRef = useGraphData(onNewDataRef);

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
        if (d.relationship === 'HOSTED_ON') return "opacity-50";
        return "";
      })
      .attr("opacity", 0.6)
      .style("pointer-events", "none");

    // Declarative SVG Animate - DEPENDS_ON Flow
    link.filter((d: any) => d.relationship === 'DEPENDS_ON')
      .append("animate")
      .attr("attributeName", "stroke-dashoffset")
      .attr("from", "26")
      .attr("to", "0")
      .attr("dur", "1s")
      .attr("repeatCount", "indefinite");
    const trafficLink = svg.append("g")
      .selectAll("line")
      .data(validLinks.filter((d: any) => d.relationship === 'CONNECTS_TO'))
      .join("line")
      .attr("stroke-width", 3)
      .attr("stroke", "#10b981") // Traffic blast
      .attr("stroke-dasharray", "5, 50")
      .attr("opacity", 0.7)
      .style("pointer-events", "none");

    // Declarative SVG Animate - CONNECTS_TO Traffic
    trafficLink.append("animate")
      .attr("attributeName", "stroke-dashoffset")
      .attr("from", "0")
      .attr("to", "110")
      .attr("dur", "2.5s")
      .attr("repeatCount", "indefinite");

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
      <AnimatedLinksLayer
        svgRef={svgRef}
        dataRef={dataRef}
        onD3UpdaterReady={d3UpdaterRef}
      />
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
