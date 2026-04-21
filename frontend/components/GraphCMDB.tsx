import { type RefObject, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import * as d3 from 'd3';
import { GraphLink, GraphNode } from '../types';
import { STATUS_COLORS } from '../utils/status';
import { useGraphTopologyQuery } from '../hooks/queries/useGraphTopologyQuery';
import { useCategoriesQuery } from '../hooks/queries/useCategoriesQuery';
import { useOwnersQuery } from '../hooks/queries/useOwnersQuery';

interface GraphCMDBProps {
  onNodeClick: (node: GraphNode) => void;
}

const AnimatedLinksLayer = ({ svgRef, links }: { svgRef: RefObject<SVGSVGElement | null>; links: GraphLink[] }) => {
  const portalSvgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const portalRoot = document.getElementById('d3-portal-root');
    if (!portalRoot || !portalSvgRef.current || !svgRef.current) {
      return;
    }

    const rect = svgRef.current.getBoundingClientRect();
    const portalSvg = d3.select(portalSvgRef.current)
      .attr('width', rect.width)
      .attr('height', rect.height)
      .style('position', 'absolute')
      .style('top', `${rect.top + window.scrollY}px`)
      .style('left', `${rect.left + window.scrollX}px`)
      .style('pointer-events', 'none')
      .style('overflow', 'visible');

    const pulseGroup = portalSvg.append('g').attr('class', 'd3-pulse-layer');
    pulseGroup
      .selectAll('circle')
      .data(links.filter((link: any) => link.relationship === 'CONNECTS_TO'), (link: any) => link.id)
      .join(
        (enter) => enter.append('circle').attr('r', 5).attr('fill', '#10b981').attr('opacity', 0.8),
        (update) => update,
        (exit) => exit.remove(),
      );

    return () => {
      portalSvg.selectAll('*').remove();
    };
  }, [links, svgRef]);

  const portalRoot = document.getElementById('d3-portal-root');
  if (!portalRoot) {
    return null;
  }

  return createPortal(
    <svg ref={portalSvgRef} style={{ position: 'absolute', pointerEvents: 'none' }} />,
    portalRoot,
  );
};

const GraphCMDB = ({ onNodeClick }: GraphCMDBProps) => {
  const [filterLayer, setFilterLayer] = useState<string>('');
  const [filterLocation, setFilterLocation] = useState<string>('');
  const [filterOwner, setFilterOwner] = useState<string>('');

  const svgRef = useRef<SVGSVGElement>(null);
  const { data, isLoading } = useGraphTopologyQuery({ 
    layer: filterLayer, 
    location: filterLocation, 
    owner: filterOwner 
  });
  
  // UX Trap Fix: Fetch full topology once to extract ALL locations for the filter
  const { data: fullData } = useGraphTopologyQuery({});

  const { data: categories } = useCategoriesQuery();
  const { data: owners } = useOwnersQuery();

  const nodes = data?.nodes ?? [];
  const links = data?.links ?? [];

  // Extract unique locations from FULL nodes to populate filter, so it doesn't collapse
  const locations = Array.from(new Set((fullData?.nodes ?? []).map(n => n.location_name).filter(Boolean))).sort();

  useEffect(() => {
    if (!svgRef.current) {
      return;
    }

    const width = svgRef.current.clientWidth || 1200;
    const height = svgRef.current.clientHeight || 800;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const defs = svg.append('defs');
    Object.values(STATUS_COLORS).forEach((color) => {
      const idColor = color.replace('#', '');
      defs.append('marker')
        .attr('id', `arrow-${idColor}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 28)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', color);
    });

    const validLinks = links.filter((link) => {
      const sourceId = typeof link.source === 'object' ? (link.source as any).id : link.source;
      const targetId = typeof link.target === 'object' ? (link.target as any).id : link.target;
      return nodes.some((node) => node.id === sourceId) && nodes.some((node) => node.id === targetId);
    }).map((link) => Object.create(link));

    const validNodes = nodes.map((node) => Object.create(node));
    const criticalNodeIds = validNodes
      .filter((node) => node.status === 'CRITICAL' || node.status === 'WARNING')
      .map((node) => node.id);

    const affectedSet = new Set<string>(criticalNodeIds);
    let added = true;
    while (added) {
      added = false;
      validLinks.forEach((link) => {
        const sourceId = typeof link.source === 'object' ? (link.source as any).id : link.source;
        const targetId = typeof link.target === 'object' ? (link.target as any).id : link.target;
        if (affectedSet.has(targetId) && !affectedSet.has(sourceId)) {
          affectedSet.add(sourceId);
          added = true;
        }
      });
    }

    const hasGlobalIncidents = criticalNodeIds.length > 0;
    const simulation = d3.forceSimulation<GraphNode>(validNodes)
      .force('link', d3.forceLink<GraphNode, GraphLink>(validLinks).id((node) => node.id).distance(150))
      .force('charge', d3.forceManyBody().strength(-500))
      .force('center', d3.forceCenter(width / 2, height / 2));

    const linkSelection = svg.append('g')
      .selectAll('line')
      .data(validLinks)
      .join('line')
      .attr('stroke-opacity', (link: any) => {
        if (!hasGlobalIncidents) {
          return 0.6;
        }
        const sourceId = typeof link.source === 'object' ? (link.source as any).id : link.source;
        const targetId = typeof link.target === 'object' ? (link.target as any).id : link.target;
        return affectedSet.has(sourceId) || affectedSet.has(targetId) ? 0.9 : 0.2;
      })
      .attr('stroke-width', 2)
      .attr('stroke', (link: any) => {
        const targetStatus = link.target?.status || 'UNKNOWN';
        if (targetStatus === 'CRITICAL') return STATUS_COLORS.CRITICAL;
        if (targetStatus === 'WARNING') return STATUS_COLORS.WARNING;
        if (targetStatus === 'ACTIVE' || targetStatus === 'OK') return STATUS_COLORS.OK;
        return STATUS_COLORS.UNKNOWN;
      })
      .attr('marker-end', (link: any) => {
        const targetStatus = link.target?.status || 'UNKNOWN';
        let color = STATUS_COLORS.UNKNOWN;
        if (targetStatus === 'CRITICAL') color = STATUS_COLORS.CRITICAL;
        else if (targetStatus === 'WARNING') color = STATUS_COLORS.WARNING;
        else if (targetStatus === 'ACTIVE' || targetStatus === 'OK') color = STATUS_COLORS.OK;
        return `url(#arrow-${color.replace('#', '')})`;
      })
      .attr('stroke-dasharray', (link: any) => {
        if (link.relationship === 'DEPENDS_ON') return '5, 8';
        if (link.relationship === 'HOSTED_ON') return '2, 2';
        return 'none';
      })
      .style('pointer-events', 'none');

    const trafficLink = svg.append('g')
      .selectAll('line')
      .data(validLinks.filter((link: any) => link.relationship === 'CONNECTS_TO'))
      .join('line')
      .attr('stroke-width', 3)
      .attr('stroke', '#10b981')
      .attr('stroke-dasharray', '5, 50')
      .attr('opacity', 0.7)
      .style('pointer-events', 'none');

    trafficLink.append('animate')
      .attr('attributeName', 'stroke-dashoffset')
      .attr('from', '0')
      .attr('to', '110')
      .attr('dur', '2.5s')
      .attr('repeatCount', 'indefinite');

    const nodeSelection = svg.append('g')
      .selectAll('g')
      .data(validNodes)
      .join('g')
      .attr('class', 'cursor-pointer group')
      .attr('opacity', (node) => {
        if (!hasGlobalIncidents) {
          return 1;
        }
        return affectedSet.has(node.id) ? 1 : 0.4;
      })
      .on('click', (_event, node) => onNodeClick(node))
      .call(d3.drag<SVGGElement, GraphNode>()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended) as any);

    nodeSelection.append('circle')
      .attr('r', (node) => node.status === 'CRITICAL' ? 32 : node.status === 'WARNING' ? 28 : 24)
      .attr('fill', '#1a1a1a')
      .attr('stroke', (node) => {
        if (node.status === 'CRITICAL') return STATUS_COLORS.CRITICAL;
        if (node.status === 'WARNING') return STATUS_COLORS.WARNING;
        if (affectedSet.has(node.id)) return '#f97316';
        return '#345bf2';
      })
      .attr('stroke-width', (node) => affectedSet.has(node.id) || node.status === 'CRITICAL' ? 4 : 2)
      .attr('class', (node) => affectedSet.has(node.id) ? 'animate-pulse' : '');

    nodeSelection.append('text')
      .attr('dy', '.35em')
      .attr('text-anchor', 'middle')
      .attr('fill', 'white')
      .attr('font-size', '10px')
      .attr('font-weight', 'bold')
      .text((node) => node.label.substring(0, 3).toUpperCase());

    nodeSelection.append('text')
      .attr('dy', '3.5em')
      .attr('text-anchor', 'middle')
      .attr('fill', '#a3a3a3')
      .attr('font-size', '11px')
      .text((node) => node.label);

    simulation.on('tick', () => {
      linkSelection
        .attr('x1', (link: any) => link.source.x)
        .attr('y1', (link: any) => link.source.y)
        .attr('x2', (link: any) => link.target.x)
        .attr('y2', (link: any) => link.target.y);

      trafficLink
        .attr('x1', (link: any) => link.source.x)
        .attr('y1', (link: any) => link.source.y)
        .attr('x2', (link: any) => link.target.x)
        .attr('y2', (link: any) => link.target.y);

      nodeSelection.attr('transform', (node: any) => `translate(${node.x},${node.y})`);
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
  }, [links, nodes, onNodeClick]);

  return (
    <div className='w-full h-full relative overflow-hidden bg-surface-950 grid-bg flex'>
      {/* Filter Sidebar */}
      <div className="w-64 bg-neutral-900/80 backdrop-blur border-r border-white/5 p-6 flex flex-col space-y-6 z-20 overflow-y-auto custom-scrollbar">
        <div>
          <h3 className="text-xs font-black text-neutral-500 uppercase tracking-widest mb-4">Filters</h3>
          
          <div className="space-y-4">
            <label className="block">
              <span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">Technology</span>
              <select 
                aria-label="Filter by Technology"
                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
                value={filterLayer}
                onChange={(e) => setFilterLayer(e.target.value)}
              >
                <option value="">All Layers</option>
                {categories?.map(c => (
                  <option key={c.name} value={c.name}>{c.name}</option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">Location</span>
              <select 
                aria-label="Filter by Location"
                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
                value={filterLocation}
                onChange={(e) => setFilterLocation(e.target.value)}
              >
                <option value="">All Locations</option>
                {locations.map(loc => (
                  <option key={loc} value={loc}>{loc}</option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">Owner</span>
              <select 
                aria-label="Filter by Owner"
                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
                value={filterOwner}
                onChange={(e) => setFilterOwner(e.target.value)}
              >
                <option value="">All Owners</option>
                {owners?.map(o => (
                  <option key={o.name} value={o.name}>{o.name}</option>
                ))}
              </select>
            </label>

            <button 
              onClick={() => {
                setFilterLayer('');
                setFilterLocation('');
                setFilterOwner('');
              }}
              className="w-full py-2 text-[10px] font-black text-neutral-500 hover:text-white transition-colors uppercase tracking-widest"
            >
              Reset Filters
            </button>
          </div>
        </div>

        <div className="pt-6 border-t border-white/5">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full bg-brand-500 shadow-[0_0_8px_rgba(52,91,242,0.5)]"></div>
            <span className="text-[10px] font-bold text-neutral-300 uppercase">Visible Nodes: {nodes.length}</span>
          </div>
          <p className="text-[10px] text-neutral-500 leading-relaxed">
            Technical topology showing CI dependencies. Filters scope the data from the server.
          </p>
        </div>
      </div>

      {/* Graph Canvas */}
      <div className="flex-1 relative">
        <svg ref={svgRef} className='w-full h-full' />
        <AnimatedLinksLayer svgRef={svgRef} links={links} />
        
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/20 backdrop-blur-sm z-10">
            <div className="flex flex-col items-center gap-4">
              <div className="w-12 h-12 border-4 border-brand-500/20 border-t-brand-500 rounded-full animate-spin"></div>
              <span className="text-xs font-black text-brand-500 uppercase tracking-widest">Querying Graph...</span>
            </div>
          </div>
        )}

        <div className='absolute bottom-4 left-4 flex flex-col gap-2 p-3 glass rounded-lg text-xs pointer-events-none select-none'>
          <div className='flex items-center gap-2'><div className='w-3 h-3 bg-brand-500 rounded-full'></div> Healthy CI</div>
          <div className='flex items-center gap-2'><div className='w-3 h-3 bg-orange-500 rounded-full'></div> Performance Warning</div>
          <div className='flex items-center gap-2'><div className='w-3 h-3 bg-red-500 rounded-full'></div> Critical Impact</div>
          <div className='h-px bg-white/10 my-1'></div>
          <div className='flex items-center gap-2'><div className='w-8 h-0.5 bg-emerald-500'></div> Connection OK</div>
          <div className='flex items-center gap-2'><div className='w-8 h-0.5 bg-red-500'></div> Critical Path</div>
        </div>
      </div>
    </div>
  );
};

export default GraphCMDB;
