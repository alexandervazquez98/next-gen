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
  const [groupByLocation, setGroupByLocation] = useState<boolean>(true);
  const [searchLocation, setSearchLocation] = useState<string>('');

  const svgRef = useRef<SVGSVGElement>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
  const nodeStateRef = useRef<Map<string, {x: number, y: number, vx: number, vy: number}>>(new Map());

  const { data, isLoading } = useGraphTopologyQuery({ 
    layer: filterLayer, 
    location: filterLocation, 
    owner: filterOwner 
  });
  
  const { data: fullData } = useGraphTopologyQuery({});
  const { data: categories } = useCategoriesQuery();
  const { data: owners } = useOwnersQuery();

  const nodes = data?.nodes ?? [];
  const links = data?.links ?? [];

  const allLocations = Array.from(new Set((fullData?.nodes ?? []).map(n => n.location_name).filter(Boolean))).sort();
  const filteredLocations = allLocations.filter(loc => loc.toLowerCase().includes(searchLocation.toLowerCase()));

  useEffect(() => {
    if (!svgRef.current) return;

    const width = svgRef.current.clientWidth || 1200;
    const height = svgRef.current.clientHeight || 800;
    const svg = d3.select(svgRef.current);
    
    // PERSIST ZOOM: Read current transform before clearing
    const currentTransform = d3.zoomTransform(svgRef.current);
    svg.selectAll('*').remove();

    const container = svg.append('g').attr('class', 'main-container');

    const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.01, 12])
      .on('zoom', (event) => {
        zoomTransformRef.current = event.transform;
        container.attr('transform', event.transform);
      });

    svg.call(zoomBehavior);
    
    // RESTORE ZOOM: Re-apply the transform
    svg.call(zoomBehavior.transform, currentTransform);

    // Calculate cluster centers if grouped
    const locationCenters: Record<string, { x: number; y: number }> = {};
    if (groupByLocation) {
      const uniqueLocs = Array.from(new Set(nodes.map(n => n.location_name).filter(Boolean)));
      uniqueLocs.forEach((loc, i) => {
        const angle = (i / uniqueLocs.length) * 2 * Math.PI;
        const radius = Math.min(width, height) * 0.4;
        locationCenters[loc] = {
          x: width / 2 + Math.cos(angle) * radius,
          y: height / 2 + Math.sin(angle) * radius
        };
      });
    }

    const defs = container.append('defs');
    Object.values(STATUS_COLORS).forEach((color) => {
      const idColor = color.replace('#', '');
      defs.append('marker')
        .attr('id', `arrow-${idColor}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 28).attr('refY', 0)
        .attr('markerWidth', 6).attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', color);
    });

    const validLinks = links.filter((link) => {
      const sourceId = typeof link.source === 'object' ? (link.source as any).id : link.source;
      const targetId = typeof link.target === 'object' ? (link.target as any).id : link.target;
      return nodes.some((node) => node.id === sourceId) && nodes.some((node) => node.id === targetId);
    }).map((link) => Object.create(link));

    const cachedNodesExist = nodes.some(n => nodeStateRef.current.has(n.id));

    const validNodes = nodes.map((node) => {
      const n = Object.create(node);
      const cached = nodeStateRef.current.get(node.id);
      
      if (cached) {
        n.x = cached.x;
        n.y = cached.y;
        n.vx = cached.vx;
        n.vy = cached.vy;
      } else if (node.location?.lat && node.location?.long) {
          n.x = (node.location.long + 180) * (width / 360);
          n.y = (90 - node.location.lat) * (height / 180);
      }
      return n;
    });

    const simulation = d3.forceSimulation<GraphNode>(validNodes)
      .force('link', d3.forceLink<GraphNode, GraphLink>(validLinks).id((node) => node.id).distance(150))
      .force('charge', d3.forceManyBody().strength((d: any) => d.type === 'CI' ? -1000 : -2000))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius((d: any) => d.type === 'CI' ? 50 : 100))
      .alpha(cachedNodesExist ? 0.2 : 1.0);

    if (groupByLocation) {
      simulation.force('x', d3.forceX().x((d: any) => {
        if (d.location?.long) return (d.location.long + 180) * (width / 360);
        return locationCenters[d.location_name]?.x || width / 2;
      }).strength(0.05));
      simulation.force('y', d3.forceY().y((d: any) => {
        if (d.location?.lat) return (90 - d.location.lat) * (height / 180);
        return locationCenters[d.location_name]?.y || height / 2;
      }).strength(0.05));
    } else {
        // STRONG ANCHOR for Lat/Long when NOT grouped
        simulation.force('x', d3.forceX().x((d: any) => {
            if (d.location?.long) return (d.location.long + 180) * (width / 360);
            return width / 2;
        }).strength((d: any) => d.location?.long ? 0.3 : 0.05));
        simulation.force('y', d3.forceY().y((d: any) => {
            if (d.location?.lat) return (90 - d.location.lat) * (height / 180);
            return height / 2;
        }).strength((d: any) => d.location?.lat ? 0.3 : 0.05));
    }

    const linkSelection = container.append('g')
      .selectAll('line').data(validLinks).join('line')
      .attr('stroke-opacity', 0.6).attr('stroke-width', 2)
      .attr('stroke', (link: any) => {
        const targetStatus = link.target?.status || 'UNKNOWN';
        if (targetStatus === 'CRITICAL') return STATUS_COLORS.CRITICAL;
        if (targetStatus === 'WARNING') return STATUS_COLORS.WARNING;
        return (targetStatus === 'ACTIVE' || targetStatus === 'OK') ? STATUS_COLORS.OK : STATUS_COLORS.UNKNOWN;
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

    const trafficLink = container.append('g')
      .selectAll('line').data(validLinks.filter((link: any) => link.relationship === 'CONNECTS_TO')).join('line')
      .attr('stroke-width', 3).attr('stroke', '#10b981').attr('stroke-dasharray', '4, 16').attr('opacity', 0.7);

    trafficLink.append('animate')
      .attr('attributeName', 'stroke-dashoffset')
      .attr('from', '20')
      .attr('to', '0')
      .attr('dur', '1s')
      .attr('repeatCount', 'indefinite');

    const nodeSelection = container.append('g')
      .selectAll('g').data(validNodes).join('g')
      .attr('class', 'cursor-pointer group')
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
        return '#345bf2';
      })
      .attr('stroke-width', (node) => node.status === 'CRITICAL' ? 4 : 2);

    nodeSelection.append('text')
      .attr('dy', '.35em').attr('text-anchor', 'middle').attr('fill', 'white').attr('font-size', '10px').attr('font-weight', 'bold')
      .text((node) => node.label.substring(0, 3).toUpperCase());

    nodeSelection.append('text')
      .attr('dy', '3.5em').attr('text-anchor', 'middle').attr('fill', '#a3a3a3').attr('font-size', '11px')
      .text((node) => node.label);

    simulation.on('tick', () => {
      linkSelection
        .attr('x1', (link: any) => link.source.x).attr('y1', (link: any) => link.source.y)
        .attr('x2', (link: any) => link.target.x).attr('y2', (link: any) => link.target.y);
      trafficLink
        .attr('x1', (link: any) => link.source.x).attr('y1', (link: any) => link.source.y)
        .attr('x2', (link: any) => link.target.x).attr('y2', (link: any) => link.target.y);
      nodeSelection.attr('transform', (node: any) => `translate(${node.x},${node.y})`);

      // SAVE STATE: Persistent Cartesian Plane
      validNodes.forEach((n: any) => {
        nodeStateRef.current.set(n.id, { x: n.x, y: n.y, vx: n.vx, vy: n.vy });
      });
    });

    function dragstarted(event: any) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }
    function dragged(event: any) { event.subject.fx = event.x; event.subject.fy = event.y; }
    function dragended(event: any) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }

    return () => simulation.stop();
  }, [links, nodes, onNodeClick, groupByLocation]);

  return (
    <div className='w-full h-full relative overflow-hidden bg-surface-950 grid-bg flex'>
      {/* Filter Sidebar */}
      <div className="w-64 bg-neutral-900/80 backdrop-blur border-r border-white/5 p-6 flex flex-col space-y-6 z-20 overflow-y-auto custom-scrollbar">
        <div>
          <h3 className="text-xs font-black text-neutral-500 uppercase tracking-widest mb-4">Discovery Filters</h3>
          
          <div className="space-y-4">
            <label className="block">
                <span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">Group by Location</span>
                <button 
                    onClick={() => setGroupByLocation(!groupByLocation)}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg border transition-all ${groupByLocation ? 'bg-brand-500/10 border-brand-500 text-brand-400' : 'bg-neutral-950 border-white/5 text-neutral-500'}`}
                >
                    <span className="text-[10px] font-black uppercase tracking-tighter">{groupByLocation ? 'Enabled' : 'Disabled'}</span>
                    <span className="material-symbols-outlined text-sm">{groupByLocation ? 'group_work' : 'blur_off'}</span>
                </button>
            </label>

            <label className="block">
              <span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">Technology</span>
              <select 
                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
                value={filterLayer}
                onChange={(e) => setFilterLayer(e.target.value)}
              >
                <option value="">All Layers</option>
                {categories?.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
              </select>
            </label>

            <label className="block">
              <span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">Location Search</span>
              <div className="relative mb-2">
                  <input 
                    type="text"
                    className="w-full bg-neutral-950 border border-white/5 rounded-lg pl-8 pr-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
                    placeholder="Search locations..."
                    value={searchLocation}
                    onChange={(e) => setSearchLocation(e.target.value)}
                  />
                  <span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-sm text-neutral-600">search</span>
              </div>
              <select 
                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
                value={filterLocation}
                onChange={(e) => setFilterLocation(e.target.value)}
              >
                <option value="">All Locations ({filteredLocations.length})</option>
                {filteredLocations.map(loc => <option key={loc} value={loc}>{loc}</option>)}
              </select>
            </label>

            <label className="block">
              <span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">Owner Group</span>
              <select 
                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500 transition-colors"
                value={filterOwner}
                onChange={(e) => setFilterOwner(e.target.value)}
              >
                <option value="">All Owners</option>
                {owners?.map(o => <option key={o.name} value={o.name}>{o.name}</option>)}
              </select>
            </label>

            <button 
              onClick={() => {
                setFilterLayer('');
                setFilterLocation('');
                setFilterOwner('');
                setSearchLocation('');
              }}
              className="w-full py-2 text-[10px] font-black text-neutral-500 hover:text-white transition-colors uppercase tracking-widest"
            >
              Reset All
            </button>
          </div>
        </div>

        <div className="pt-6 border-t border-white/5">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full bg-brand-500 shadow-[0_0_8px_rgba(52,91,242,0.5)]"></div>
            <span className="text-[10px] font-bold text-neutral-300 uppercase">Visible Nodes: {nodes.length}</span>
          </div>
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
              <span className="text-xs font-black text-brand-500 uppercase tracking-widest">Calculating Topology...</span>
            </div>
          </div>
        )}

        <div className='absolute bottom-4 left-4 flex flex-col gap-2 p-3 glass rounded-lg text-xs pointer-events-none select-none'>
          <div className='flex items-center gap-2'><div className='w-3 h-3 bg-brand-500 rounded-full'></div> Operational</div>
          <div className='flex items-center gap-2'><div className='w-3 h-3 bg-orange-500 rounded-full'></div> Degraded</div>
          <div className='flex items-center gap-2'><div className='w-3 h-3 bg-red-500 rounded-full'></div> Critical</div>
          <div className='h-px bg-white/10 my-1'></div>
          <p className="text-[8px] text-neutral-500 uppercase font-black">Controls</p>
          <p className="text-[9px] text-neutral-400">Wheel: Zoom | Drag: Pan | Click: Detail</p>
        </div>
      </div>
    </div>
  );
};

export default GraphCMDB;
