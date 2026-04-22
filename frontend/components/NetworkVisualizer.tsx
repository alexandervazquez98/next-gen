
import React, { useState, useEffect, useRef, useMemo } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { GraphNode, GraphLink } from '../types';
import { api } from '../services/api';
// import SpriteText from 'three-spritetext'; // Optional for text labels if needed


const NetworkVisualizer: React.FC = () => {
    const [nodes, setNodes] = useState<any[]>([]); // Using any[] to support diverse node types
    const [links, setLinks] = useState<any[]>([]);
    const [showCIs, setShowCIs] = useState(false); // Default: Hide CIs
    const fgRef = useRef<any>(null);

    const isZoomed = useRef(false);

    const fetchData = async () => {
        try {
            const data = await api.get<{ nodes: any[], links: any[] }>('/graph/full');
            setNodes(prevNodes => {
                if (JSON.stringify(prevNodes) === JSON.stringify(data.nodes)) return prevNodes;
                return data.nodes;
            });
            setLinks(prevLinks => {
                if (JSON.stringify(prevLinks) === JSON.stringify(data.links)) return prevLinks;
                return data.links;
            });
        } catch (err) {
            console.error("Failed to load graph data:", err);
        }
    };

    useEffect(() => {
        fetchData(); // Initial Fetch
        const interval = setInterval(fetchData, 5000); // Poll every 5s
        return () => clearInterval(interval);
    }, []);

    const graphData = useMemo(() => {
        if (showCIs) return { nodes, links };

        // Filter logic: Hide CIs if showCIs is false
        const activeNodes = nodes.filter(n => n.type !== 'CI');
        const activeNodeIds = new Set(activeNodes.map(n => n.id));
        const activeLinks = links.filter(l => {
            const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
            const targetId = typeof l.target === 'object' ? l.target.id : l.target;
            return activeNodeIds.has(sourceId) && activeNodeIds.has(targetId);
        });

        return { nodes: activeNodes, links: activeLinks };
    }, [nodes, links, showCIs]);

    // Apply custom forces when graph loads
    useEffect(() => {
        if (fgRef.current) {
            // Apply compactness forces
            fgRef.current.d3Force('charge').strength(-120);
            fgRef.current.d3Force('link').distance(50);
            fgRef.current.d3Force('center').strength(1.2);
        }
    }, [graphData]);


    // Node Color by Type (NEON PALETTE)
    const getNodeColor = (node: any) => {
        switch (node.type) {
            case 'CI':
                if (node.status === 'CRITICAL') return '#ff0055'; // Neon Red
                if (node.status === 'WARNING') return '#ffcc00'; // Neon Yellow
                return '#00ff99'; // Neon Green
            case 'Category': return '#00d4ff'; // Neon Cyan
            case 'Owner': return '#bf00ff'; // Neon Purple
            case 'Metric': return '#ff00aa'; // Neon Pink
            case 'Hardware': return '#ff6600'; // Neon Orange
            case 'User': return '#00ffcc'; // Electric Teal
            default: return '#888888'; // Silver
        }
    };

    // Node Size by Type
    const getNodeVal = (node: any) => {
        switch (node.type) {
            case 'Category': return 40; // Much larger Hubs
            case 'Owner': return 30;
            case 'Hardware': return 25;
            case 'Metric': return 20;
            case 'User': return 20;
            case 'CI': return 15;
            default: return 10;
        }
    };

    return (
        <div className="h-full w-full bg-black relative">
            <div className="absolute top-8 left-8 z-50 pointer-events-none">
                <h2 className="text-3xl font-black text-white tracking-widest uppercase mb-2" style={{ textShadow: '0 0 20px rgba(0,255,255,0.5)' }}>
                    NEURAL TOPOLOGY
                </h2>
                <p className="text-xs text-cyan-400 font-mono tracking-widest bg-black/50 p-2 rounded border border-cyan-900/30 backdrop-blur-sm inline-block">
                    NODES: {graphData.nodes.length} | LINKS: {graphData.links.length}
                </p>

                <div className="mt-4 pointer-events-auto">
                    <button
                        onClick={() => setShowCIs(!showCIs)}
                        className={`px-4 py-2 text-xs font-bold uppercase tracking-widest border rounded transition-all ${showCIs
                            ? 'bg-emerald-500/20 border-emerald-500 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.4)]'
                            : 'bg-neutral-800/80 border-neutral-600 text-neutral-400 hover:border-neutral-400'
                            }`}
                    >
                        {showCIs ? 'HIDE INFRASTRUCTURE (CIs)' : 'SHOW INFRASTRUCTURE (CIs)'}
                    </button>
                </div>
            </div>

            <ForceGraph2D
                ref={fgRef}
                graphData={graphData}
                nodeLabel="label"
                nodeColor={getNodeColor}
                nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2Array, globalScale: number) => {
                    const label = node.label;
                    const fontSize = 12 / globalScale;
                    ctx.font = `${fontSize}px Sans-Serif`;
                    const textWidth = ctx.measureText(label).width;
                    const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.2); // some padding

                    const size = Math.sqrt(getNodeVal(node)) * 2;

                    // Draw Node Circle
                    ctx.beginPath();
                    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI, false);
                    ctx.fillStyle = getNodeColor(node);
                    ctx.fill();

                    // Glow Effect
                    ctx.shadowColor = getNodeColor(node);
                    ctx.shadowBlur = 10;
                    ctx.stroke();
                    ctx.shadowBlur = 0;

                    // Draw Text
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillStyle = 'white';
                    ctx.fillText(label, node.x, node.y + size + 5);
                }}
                nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2Array) => {
                    const size = Math.sqrt(getNodeVal(node)) * 2;
                    ctx.fillStyle = color;
                    ctx.beginPath(); ctx.arc(node.x, node.y, size + 2, 0, 2 * Math.PI, false); ctx.fill();
                }}

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
                linkDirectionalParticleSpeed={d => 0.005}
                linkDirectionalParticleWidth={2}
                linkColor={() => 'rgba(255,255,255,0.2)'}
                linkWidth={1}
            />

            <div className="absolute bottom-8 right-8 z-50 text-right pointer-events-none">
                <div className="flex flex-col gap-2 bg-black/60 p-4 rounded-lg backdrop-blur-md border border-white/10">
                    <h4 className="text-xs font-bold text-white uppercase mb-2 border-b border-white/10 pb-1">Legend</h4>

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
                </div>
            </div>
        </div>
    );
};

export default NetworkVisualizer;
