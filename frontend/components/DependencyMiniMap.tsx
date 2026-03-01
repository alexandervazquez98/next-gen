import React, { useState, useEffect, useRef } from 'react';
import { GraphNode, Event } from '../types';

interface DependencyMiniMapProps {
    ciId?: string;
    nodes: GraphNode[];
    links: any[];
    event?: Event;
}

/**
 * DependencyMiniMap Component
 * 
 * Visualizes the immediate topology surrounding a specific CI (Configuration Item).
 * Used primarily in the Event Details modal to show Impact/Root Cause.
 * 
 * Layout: Hierarchical Linear + Radial Satellites for Metrics.
 */
const DependencyMiniMap: React.FC<DependencyMiniMapProps> = ({ ciId, nodes, links, event }) => {
    const [transform, setTransform] = useState({ x: 0, y: 0, k: 0.65 });
    const [isDragging, setIsDragging] = useState(false);
    const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
    const [lastPos, setLastPos] = useState({ x: 0, y: 0 });
    const containerRef = useRef<HTMLDivElement>(null);

    // Graph State
    const [graphData, setGraphData] = useState<{ nodes: any[], links: any[], maxLevel?: number }>({ nodes: [], links: [] });

    useEffect(() => {
        if (!ciId) return;

        // --- Impact & Root Cause Analysis (Bidirectional) ---
        const impactedNodes = new Map<string, { node: GraphNode, level: number }>();
        const impactedLinks = new Set<any>();
        const visited = new Set<string>();

        // 1. Root Detection
        let rootId = ciId;
        const parentLink = links.find(l => {
            const sId = typeof l.source === 'object' ? (l.source as any).id : l.source;
            const tId = typeof l.target === 'object' ? (l.target as any).id : l.target;
            return sId === ciId && ['DEPENDS_ON', 'HOSTED_ON', 'RUNS_ON', 'CATEGORIZED_AS'].includes(l.relationship);
        });

        if (parentLink) {
            rootId = typeof parentLink.target === 'object' ? (parentLink.target as any).id : parentLink.target;

            // Grandparent check
            const grandParentLink = links.find(l => {
                const sId = typeof l.source === 'object' ? (l.source as any).id : l.source;
                return sId === rootId && ['DEPENDS_ON', 'HOSTED_ON', 'RUNS_ON', 'CATEGORIZED_AS'].includes(l.relationship);
            });

            if (grandParentLink) {
                rootId = typeof grandParentLink.target === 'object' ? (grandParentLink.target as any).id : grandParentLink.target;
            }
        }

        // Level 0: The Calculated Root (Provider)
        const centralNode = nodes.find(n => n.id === rootId);
        if (centralNode) {
            impactedNodes.set(rootId, { node: centralNode, level: 0 });
            visited.add(rootId);
        }

        // 2. BFS Traversal
        let queue = [{ id: rootId, level: 0 }];
        const MAX_DEPTH = 3;

        while (queue.length > 0) {
            const current = queue.shift()!;
            if (current.level >= MAX_DEPTH) continue;

            // Find ALL connected neighbors 
            const neighborLinks = links.filter(l => {
                const sId = typeof l.source === 'object' ? l.source.id : l.source;
                const tId = typeof l.target === 'object' ? l.target.id : l.target;
                return sId === current.id || tId === current.id;
            });

            const unvisitedLinks = neighborLinks.filter(l => {
                const sId = typeof l.source === 'object' ? l.source.id : l.source;
                const tId = typeof l.target === 'object' ? l.target.id : l.target;
                const neighborId = sId === current.id ? tId : sId;
                return !visited.has(neighborId);
            });

            const count = unvisitedLinks.length;
            if (count === 0) continue;

            unvisitedLinks.forEach((link) => {
                const sId = typeof link.source === 'object' ? link.source.id : link.source;
                const tId = typeof link.target === 'object' ? link.target.id : link.target;
                const neighborId = sId === current.id ? tId : sId;

                const node = nodes.find(n => n.id === neighborId);
                if (node) {
                    visited.add(neighborId);
                    impactedLinks.add(link);

                    impactedNodes.set(neighborId, {
                        node,
                        level: current.level + 1
                    });

                    queue.push({
                        id: neighborId,
                        level: current.level + 1
                    });
                }
            });
        }

        // 3. Layout Calculation
        const width = 800;
        const centerX = width / 2;
        const START_Y = 80;
        const LEVEL_HEIGHT = 160;   // Vertical space between rows
        const NODE_SPACING_X = 180; // Horizontal space between nodes

        const finalNodes: any[] = [];
        let maxLevelFound = 0;

        // Group by Level to calculate X positions
        const levels = new Map<number, any[]>();
        impactedNodes.forEach((val, key) => {
            if (val.level > maxLevelFound) maxLevelFound = val.level;
            if (!levels.has(val.level)) levels.set(val.level, []);
            levels.get(val.level)!.push(val);
        });

        levels.forEach((levelNodes, level) => {
            const count = levelNodes.length;
            levelNodes.forEach((val, index) => {
                // Center alignment: (index - (count-1)/2) * spacing
                const xOffset = (index - (count - 1) / 2) * NODE_SPACING_X;

                // Process Metrics for Satellite View (Radial Anomaly Ring)
                const satellites: any[] = [];

                // 1. From active events on this Node
                if (val.node.events && Array.isArray(val.node.events)) {
                    val.node.events.forEach((e: Event) => {
                        if (e.metric_name && !satellites.some(s => s.name === e.metric_name)) {
                            satellites.push({ name: e.metric_name, status: e.severity, type: 'METRIC' });
                        }
                    });
                }

                // 2. From node metrics array
                if (val.node.metrics && Array.isArray(val.node.metrics)) {
                    val.node.metrics.forEach((m: any) => {
                        // Only show metrics that are NOT OK to reduce clutter, or always show if explicit request.
                        // Assuming user wants to see what's wrong mainly.
                        if ((m.status === 'CRITICAL' || m.status === 'WARNING') && !satellites.some(s => s.name === m.name)) {
                            satellites.push({ name: m.name, status: m.status, type: 'METRIC' });
                        }
                    });
                }

                // If this is the alarmed CI and NO metrics found, maybe show generic alert satellite?
                // skipping for now to keep clean.

                finalNodes.push({
                    ...val.node,
                    x: centerX + xOffset,
                    y: START_Y + (level * LEVEL_HEIGHT),
                    level: level,
                    initialY: START_Y + (level * LEVEL_HEIGHT), // Store initial Y to lock vertical movement
                    satellites: satellites
                });
            });
        });

        setGraphData({
            nodes: finalNodes,
            links: Array.from(impactedLinks),
            maxLevel: maxLevelFound
        });

    }, [ciId, nodes, links]);


    if (!ciId) return null;

    const getIcon = (type: string) => {
        if (type === 'SERVER') return 'dns';
        if (type === 'DATABASE') return 'database';
        if (type === 'APPLICATION') return 'apps';
        if (type === 'ROUTER' || type === 'SWITCH') return 'router';
        return 'circle';
    };

    // Determine Alarm Type Details
    const isPingFailure = event?.message.includes("Unreachable") || event?.message.includes("PING") || event?.message.includes("Down");
    const isMetricHigh = event?.message.includes("Threshold") || event?.message.includes("CPU") || event?.message.includes("Memory");

    // Interaction Handlers
    const handleWheel = (e: React.WheelEvent) => {
        e.preventDefault();
        const scaleAmount = -e.deltaY * 0.001;
        const newScale = Math.min(Math.max(0.2, transform.k * (1 + scaleAmount)), 4);
        setTransform(prev => ({ ...prev, k: newScale }));
    };

    const handleMouseDown = (e: React.MouseEvent, nodeId?: string) => {
        if (nodeId) {
            e.stopPropagation();
            setDraggingNodeId(nodeId);
            setLastPos({ x: e.clientX, y: e.clientY });
        } else {
            setIsDragging(true);
            setLastPos({ x: e.clientX, y: e.clientY });
        }
    };

    const handleMouseMove = (e: React.MouseEvent) => {
        if (draggingNodeId) {
            const dx = (e.clientX - lastPos.x) / transform.k;
            // Lock Y axis movement by not using dy for nodes to maintain hierarchy tiers

            setGraphData(prev => ({
                ...prev,
                nodes: prev.nodes.map(n =>
                    n.id === draggingNodeId ? { ...n, x: n.x + dx } : n // Only update X
                )
            }));
            setLastPos({ x: e.clientX, y: e.clientY });
            return;
        }

        if (!isDragging) return;
        const dx = e.clientX - lastPos.x;
        const dy = e.clientY - lastPos.y;
        setTransform(prev => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
        setLastPos({ x: e.clientX, y: e.clientY });
    };

    const handleMouseUp = () => {
        setIsDragging(false);
        setDraggingNodeId(null);
    };

    return (
        <div
            ref={containerRef}
            className="w-full h-full min-h-[400px] flex-1 bg-black/40 rounded-lg border border-white/5 relative overflow-hidden flex items-center justify-center cursor-move"
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
        >
            <div className="absolute top-2 left-2 text-[10px] uppercase font-bold text-neutral-500 flex items-center gap-1 z-10 pointer-events-none">
                <span className="material-symbols-outlined text-xs">hub</span>
                Impact Blast Radius (Levels: {(graphData as any).maxLevel + 1 || 1})
            </div>

            <div className="absolute bottom-2 right-2 flex gap-1 z-10">
                <button onClick={() => setTransform({ x: 0, y: 0, k: 0.65 })} className="p-1 bg-black/50 text-white rounded hover:bg-white/10" title="Reset View">
                    <span className="material-symbols-outlined text-xs">center_focus_strong</span>
                </button>
            </div>

            <svg width="100%" height="100%" viewBox="0 0 800 600" className="w-full h-full pointer-events-none">
                <defs>
                    <marker id="arrow-default" markerWidth="10" markerHeight="10" refX="28" refY="3" orient="auto" markerUnits="strokeWidth">
                        <path d="M0,0 L0,6 L9,3 z" fill="#666" />
                    </marker>
                    <marker id="arrow-red" markerWidth="10" markerHeight="10" refX="28" refY="3" orient="auto" markerUnits="strokeWidth">
                        <path d="M0,0 L0,6 L9,3 z" fill="#ef4444" />
                    </marker>
                    <marker id="arrow-yellow" markerWidth="10" markerHeight="10" refX="28" refY="3" orient="auto" markerUnits="strokeWidth">
                        <path d="M0,0 L0,6 L9,3 z" fill="#eab308" />
                    </marker>
                    <marker id="arrow-green" markerWidth="10" markerHeight="10" refX="28" refY="3" orient="auto" markerUnits="strokeWidth">
                        <path d="M0,0 L0,6 L9,3 z" fill="#10b981" />
                    </marker>
                </defs>

                <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`} style={{ transformOrigin: 'center' }}>

                    {/* Level Bands (Subtle Background) */}
                    {Array.from({ length: ((graphData as any).maxLevel || 0) + 1 }).map((_, i) => (
                        <line key={`grid-${i}`} x1="-2000" y1={80 + (i * 160)} x2="3000" y2={80 + (i * 160)} stroke="#ffffff" strokeOpacity="0.03" strokeWidth="1" strokeDasharray="10,10" />
                    ))}

                    {/* Links */}
                    {graphData.links.map((link: any, i: number) => {
                        const source = graphData.nodes.find(n => n.id === link.source);
                        const target = graphData.nodes.find(n => n.id === link.target);
                        if (!source || !target) return null;

                        const isAffectedLink = source.id === ciId || target.id === ciId;

                        let strokeColor = '#52525b';
                        let marker = "url(#arrow-default)";
                        let strokeWidth = "2";
                        let dashArray = "";

                        // Connection Type logic
                        if (link.relationship === 'DEPENDS_ON') {
                            dashArray = "5,5";
                        } else if (link.relationship === 'HOSTED_ON') {
                            dashArray = "2,2";
                            strokeWidth = "1.5";
                        }

                        // Status Color Overlay
                        if (isAffectedLink) {
                            if (isPingFailure) {
                                strokeColor = '#ef4444'; // Red
                                marker = "url(#arrow-red)";
                                dashArray = "4,4";
                            } else if (isMetricHigh) {
                                strokeColor = '#eab308'; // Yellow
                                marker = "url(#arrow-yellow)";
                            }
                        }

                        return (
                            <g key={`link-${i}`}>
                                <line
                                    x1={source.x} y1={source.y}
                                    x2={target.x} y2={target.y}
                                    stroke={strokeColor}
                                    strokeWidth={strokeWidth}
                                    strokeDasharray={dashArray}
                                    markerEnd={marker}
                                    className={isAffectedLink && isPingFailure ? "animate-pulse" : "transition-colors duration-500"}
                                />
                                {isAffectedLink && isPingFailure && (
                                    <g transform={`translate(${(source.x + target.x) / 2}, ${(source.y + target.y) / 2})`}>
                                        <circle r="10" fill="#1a1a1a" stroke="#ef4444" strokeWidth="1" />
                                        <text x="-5" y="4" className="material-symbols-outlined text-[12px] fill-red-500 font-bold">wifi_off</text>
                                    </g>
                                )}
                                {isAffectedLink && isMetricHigh && (
                                    <g transform={`translate(${(source.x + target.x) / 2}, ${(source.y + target.y) / 2})`}>
                                        <circle r="10" fill="#1a1a1a" stroke="#eab308" strokeWidth="1" />
                                        <text x="-5" y="4" className="material-symbols-outlined text-[12px] fill-yellow-500 font-bold">warning</text>
                                    </g>
                                )}
                            </g>
                        );
                    })}

                    {/* Nodes Layer - Main CIs */}
                    {graphData.nodes.map((n) => {
                        let fillColor = '#10b981'; // Default Green (Healthy)
                        let strokeColor = '#059669'; // Darker Green Border

                        // 1. Status Check
                        if (n.hasCritical) {
                            fillColor = '#7f1d1d'; // Red Dark
                            strokeColor = '#ef4444'; // Red Bright
                        } else if (n.hasWarning) {
                            fillColor = '#78350f'; // Amber Dark
                            strokeColor = '#d97706'; // Amber Bright
                        } else {
                            fillColor = '#064e3b'; // Emerald 900
                            strokeColor = '#10b981'; // Emerald 500
                        }

                        // 2. Specific Alarmed Node Override
                        const isAlarmSource = n.id === ciId;
                        if (isAlarmSource) {
                            if (event?.severity === 'CRITICAL') {
                                fillColor = '#7f1d1d'; strokeColor = '#ef4444';
                            } else if (event?.severity === 'WARNING') {
                                fillColor = '#78350f'; strokeColor = '#d97706';
                            }
                        }

                        const isRoot = n.level === 0;
                        const size = isRoot ? 45 : 32;
                        const fontSize = isRoot ? 28 : 22;

                        return (
                            <g key={n.id} transform={`translate(${n.x},${n.y})`}>

                                {/* Satellites Ring (Metrics) */}
                                {n.satellites && n.satellites.map((sat: any, idx: number) => {
                                    const total = n.satellites.length;
                                    // Distribute around the node (Radial Layout)
                                    // Start from top (-PI/2) and go around
                                    const angle = (idx / total) * Math.PI * 2 - (Math.PI / 2);
                                    const radius = size + 50;
                                    const sx = Math.cos(angle) * radius;
                                    const sy = Math.sin(angle) * radius;

                                    const satColor = sat.status === 'CRITICAL' ? '#ef4444' : '#eab308';

                                    return (
                                        <g key={`sat-${idx}`} className="animate-in fade-in zoom-in duration-500">
                                            {/* Link to Satellite */}
                                            <line x1={0} y1={0} x2={sx} y2={sy} stroke={satColor} strokeWidth="1" strokeDasharray="2,2" opacity="0.6" />

                                            {/* Satellite Node */}
                                            <g transform={`translate(${sx},${sy})`}>
                                                <circle r="14" fill="#171717" stroke={satColor} strokeWidth="2" />
                                                <text y="5" textAnchor="middle" className="material-symbols-outlined text-[14px] fill-white" fill={satColor}>
                                                    {sat.name.includes('CPU') ? 'memory' : sat.name.includes('Disk') ? 'hard_drive' : 'speed'}
                                                </text>

                                                {/* Satellite Label (Small Pill) */}
                                                <g transform={`translate(0, 24)`}>
                                                    <rect x="-35" y="-8" width="70" height="14" rx="4" fill="rgba(0,0,0,0.85)" stroke={satColor} strokeWidth="1" />
                                                    <text y="2" textAnchor="middle" fill="#fff" fontSize="8" fontWeight="bold">{sat.name}</text>
                                                </g>
                                            </g>
                                        </g>
                                    );
                                })}

                                {/* Core Node Visuals */}
                                <g
                                    onMouseDown={(e) => handleMouseDown(e, n.id)}
                                    className="cursor-ew-resize active:cursor-grabbing transition-colors"
                                >
                                    {/* Pulse Animation for Alarmed Node */}
                                    {isAlarmSource && (
                                        <circle r={size} fill="none" stroke={strokeColor} strokeWidth="2" opacity="0.5">
                                            <animate attributeName="r" from={size} to={size + 25} dur="1.5s" repeatCount="indefinite" />
                                            <animate attributeName="opacity" from="0.5" to="0" dur="1.5s" repeatCount="indefinite" />
                                        </circle>
                                    )}

                                    <circle r={size} fill={fillColor} stroke={strokeColor} strokeWidth={isAlarmSource ? 3 : 2} className="shadow-2xl" />
                                    <text x="0" y={isRoot ? 11 : 8} textAnchor="middle" className="material-symbols-outlined text-white pointer-events-none select-none" style={{ fontSize: fontSize + 'px' }}>{getIcon(n.type)}</text>
                                </g>
                            </g>
                        );
                    })}

                    {/* Labels Layer (Rendered Last ensures they are on top of lines and nodes) */}
                    {graphData.nodes.map((n) => {
                        const isRoot = n.level === 0;
                        const size = isRoot ? 45 : 32;

                        // Determine label position based on hierarchy or preference
                        // Standard: Below the node

                        return (
                            <g key={`label-${n.id}`} transform={`translate(${n.x},${n.y}) pointer-events-none`}>
                                <g transform={`translate(0, ${size + 22})`}>
                                    {/* Pill Background for Readability */}
                                    <rect x="-60" y="-12" width="120" height="20" rx="6" fill="rgba(0,0,0,0.85)" stroke={n.hasCritical ? '#ef4444' : n.hasWarning ? '#eab308' : '#3f3f46'} strokeWidth="1" />
                                    <text y="2" textAnchor="middle" fill="#fff" fontSize="10" fontWeight="bold" className="select-none tracking-wide">{n.label}</text>
                                </g>

                                {/* Root Badge */}
                                {isRoot && (
                                    <g transform={`translate(0, ${-size - 18})`}>
                                        <rect x="-35" y="-10" width="70" height="16" rx="4" fill="#3b82f6" stroke="#3b82f6" strokeWidth="1" />
                                        <text y="2" textAnchor="middle" fill="#fff" fontSize="9" fontWeight="bold">ROOT CI</text>
                                    </g>
                                )}
                            </g>
                        );
                    })}

                </g>
            </svg>
        </div>
    );
};

export default DependencyMiniMap;
