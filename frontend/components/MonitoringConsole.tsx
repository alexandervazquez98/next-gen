import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap, CircleMarker, Circle } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { AntPath } from 'leaflet-ant-path';
import { GraphNode, Event } from '../types';
import { STATUS_COLORS } from '../utils/status';
import DependencyMiniMap from './DependencyMiniMap';
import { useEventCorrelation } from '../hooks/useEventCorrelation';
import L from 'leaflet';

/**
 * Configure Leaflet Default Icon
 */
const DefaultIcon = L.icon({
    iconUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41]
});

L.Marker.prototype.options.icon = DefaultIcon;

// Custom Icons for Map
const CriticalIcon = L.icon({
    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41]
});
const WarningIcon = L.icon({
    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-gold.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41]
});

/**
 * AnimatedPolyline Component
 * Bypasses React-Leaflet's virtual DOM by deterministically appending a declarative SVG <animate> tag.
 */
const AnimatedPolyline: React.FC<any> = ({ positions, pathOptions, animationConfig }) => {
    const polyRef = React.useRef<any>(null);

    React.useEffect(() => {
        if (polyRef.current && polyRef.current._path && animationConfig) {
            const path: SVGElement = polyRef.current._path;

            // Prevent duplicate animate tags on re-renders
            if (path.querySelector('animate')) return;

            const animateTag = document.createElementNS('http://www.w3.org/2000/svg', 'animate');
            animateTag.setAttribute('attributeName', 'stroke-dashoffset');
            animateTag.setAttribute('from', animationConfig.from);
            animateTag.setAttribute('to', animationConfig.to);
            animateTag.setAttribute('dur', animationConfig.dur);
            animateTag.setAttribute('repeatCount', 'indefinite');

            path.appendChild(animateTag);
        }
    }, [polyRef.current, animationConfig]);

    return <Polyline ref={polyRef} positions={positions} pathOptions={pathOptions} />;
};

/**
 * Auto-Zoom Component used inside MapContainer to fit bounds of nodes.
 */
const MapBounds = ({ nodes }: { nodes: GraphNode[] }) => {
    const map = useMap();
    const hasZoomed = React.useRef(false); // Guard to prevent re-zooming on updates

    useEffect(() => {
        if (nodes.length > 0 && !hasZoomed.current) {
            const validNodes = nodes.filter(n => n.location?.lat && n.location?.long);
            if (validNodes.length > 0) {
                const bounds = L.latLngBounds(validNodes.map(n => [n.location!.lat, n.location!.long]));
                map.fitBounds(bounds, { padding: [50, 50] });
                hasZoomed.current = true;
            }
        }
    }, [nodes, map]);
    return null;
};

/**
 * MonitoringConsole Component
 * 
 * Provides a real-time event stream and a geospatial view of infrastructure.
 * Handles event acknowledgement, closing, and diagnostic execution.
 */
const MonitoringConsole: React.FC = () => {
    const [viewMode, setViewMode] = useState<'DASHBOARD' | 'MAP'>('DASHBOARD');
    const [events, setEvents] = useState<Event[]>([]);
    const [nodes, setNodes] = useState<GraphNode[]>([]);
    const [links, setLinks] = useState<any[]>([]);
    const [filterCategory, setFilterCategory] = useState<string>('ALL');
    const [categories, setCategories] = useState<string[]>([]);

    // Auto-refresh interval (10s)
    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 10000);
        return () => clearInterval(interval);
    }, []);

    /**
     * Fetch all necessary data for the monitoring console.
     * Retrieving Nodes, Links, and Active Events in parallel.
     */
    const fetchData = async () => {
        try {
            const [dataNodes, dataLinks, dataEvents] = await Promise.all([
                api.get<GraphNode[]>('/nodes'),
                api.get<any[]>('/links'),
                api.get<Event[]>('/events?status=ACTIVE')
            ]);

            if (Array.isArray(dataNodes)) {
                setNodes(dataNodes);
                const cats = Array.from(new Set(dataNodes.map((n: GraphNode) => n.type))).sort();
                setCategories(cats as string[]);
            }

            if (Array.isArray(dataLinks)) setLinks(dataLinks);
            if (Array.isArray(dataEvents)) setEvents(dataEvents);

        } catch (e) {
            console.error("Failed to fetch monitoring data", e);
        }
    };

    // --- Actions ---

    /**
     * Ackowledge an event (Operator is working on it).
     */
    const handleAck = async (id: string) => {
        await api.post(`/events/${id}/ack`, {});
        fetchData();
    };

    /**
     * Close an event (Resolved/False Positive).
     */
    const handleClose = async (id: string) => {
        await api.post(`/events/${id}/close`, {});
        fetchData();
    };

    // --- Comment / Modal State ---

    const [commentModalOpen, setCommentModalOpen] = useState(false);
    const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
    const [commentText, setCommentText] = useState("");
    const [isDiagnosing, setIsDiagnosing] = useState(false);

    const handleOpenComment = (id: string) => {
        setSelectedEventId(id);
        setCommentText("");
        setCommentModalOpen(true);
    };

    const submitComment = async () => {
        if (!selectedEventId || !commentText.trim()) return;

        await api.post(`/events/${selectedEventId}/comment`, {
            message: commentText,
            user: 'Admin'
        });

        setCommentModalOpen(false);
        fetchData();
    };

    // --- Data Processing for Visualization ---

    const filteredNodes = filterCategory === 'ALL'
        ? nodes
        : nodes.filter(n => n.type === filterCategory);

    // Enriched Nodes with Event Status
    const nodesWithEvents = filteredNodes.map(node => {
        const nodeEvents = events.filter(e => e.ci_id === node.id);
        const critical = nodeEvents.some(e => e.severity === 'CRITICAL');
        const warning = nodeEvents.some(e => e.severity === 'WARNING');
        return { ...node, hasCritical: critical, hasWarning: warning, events: nodeEvents };
    });

    const openEvents = events.filter(e => e.status === 'OPEN');
    const ackEvents = events.filter(e => e.status === 'ACK');

    const kpiCritical = openEvents.filter(e => e.severity === 'CRITICAL').length;
    const kpiWarning = openEvents.filter(e => e.severity === 'WARNING').length;
    const kpiAck = ackEvents.length;

    // Helper for Cleanup Button Logic
    const cleanableCount = events.filter(e =>
        e.status === 'RECOVERED' && !e.ack && (!e.comments || e.comments.length === 0)
    ).length;

    // --- Event Correlation & Grouping Engine ---
    const groupedEvents = useEventCorrelation(events, links);

    const activeEventsDisplay = groupedEvents;

    return (
        <div className="h-full flex flex-col bg-surface-950 overflow-hidden relative">
            {/* Header / Toolbar */}
            <div className="h-16 px-8 flex items-center justify-between border-b border-white/5 glass z-10">
                <div className="flex items-center gap-4">
                    <h2 className="text-xl font-black text-white uppercase tracking-tighter flex items-center gap-2">
                        <span className="material-symbols-outlined text-brand-400">notifications_active</span>
                        Event Console
                    </h2>

                    <div className="flex bg-black/20 p-1 rounded-lg border border-white/5">
                        <button onClick={() => setViewMode('DASHBOARD')} className={`px-4 py-1.5 rounded-md text-xs font-bold uppercase transition-all ${viewMode === 'DASHBOARD' ? 'bg-brand-600 text-white shadow-lg' : 'text-neutral-500 hover:text-white'}`}>Stream</button>
                        <button onClick={() => setViewMode('MAP')} className={`px-4 py-1.5 rounded-md text-xs font-bold uppercase transition-all ${viewMode === 'MAP' ? 'bg-brand-600 text-white shadow-lg' : 'text-neutral-500 hover:text-white'}`}>Geo View</button>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                    <button
                        onClick={async () => {
                            if (cleanableCount === 0) return;
                            if (!window.confirm(`About to close ${cleanableCount} RECOVERED events that have no Acks or Comments. Proceed?`)) return;
                            const res: any = await api.post('/events/prune', {});
                            alert(res.message);
                            fetchData();
                        }}
                        disabled={cleanableCount === 0}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold uppercase flex items-center gap-2 transition-all ${cleanableCount > 0 ? 'bg-brand-600 hover:bg-brand-500 text-white animate-pulse' : 'bg-white/5 text-neutral-600 opacity-30 cursor-not-allowed'}`}
                    >
                        <span className="material-symbols-outlined text-sm">cleaning_services</span>
                        Clean recovered ({cleanableCount})
                    </button>

                    <div className="h-6 w-px bg-white/10 mx-2"></div>

                    <div className="flex items-center gap-3">
                        <span className="text-xs font-bold text-neutral-500 uppercase">Filter:</span>
                        <select
                            className="bg-black/40 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white outline-none focus:border-brand-500"
                            value={filterCategory}
                            onChange={e => setFilterCategory(e.target.value)}
                        >
                            <option value="ALL">Global Infrastructure</option>
                            {categories.map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                    </div>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 relative overflow-hidden">
                {viewMode === 'DASHBOARD' ? (
                    <div className="h-full p-8 overflow-y-auto custom-scrollbar space-y-8">
                        {/* KPI Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                            <StatCard label="Critical Events" value={kpiCritical} icon="dangerous" color="text-red-500" bg="bg-red-500/10" animate={kpiCritical > 0} />
                            <StatCard label="Warnings" value={kpiWarning} icon="warning" color="text-yellow-500" bg="bg-yellow-500/10" />
                            <StatCard label="Acknowledged" value={kpiAck} icon="thumb_up" color="text-blue-400" bg="bg-blue-500/10" />
                            <StatCard label="Total Active" value={events.length} icon="dns" color="text-white" />
                        </div>

                        {/* Event Stream Table */}
                        <div className="glass p-6 rounded-2xl border border-white/5 flex flex-col h-[600px]">
                            <h3 className="text-sm font-bold text-neutral-400 uppercase mb-4 flex items-center gap-2">
                                <span className="material-symbols-outlined text-brand-400">history</span>
                                Live Event Stream
                            </h3>
                            <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
                                <table className="w-full text-left border-collapse">
                                    <thead className="sticky top-0 bg-neutral-900/90 backdrop-blur z-10">
                                        <tr className="text-xs text-neutral-500 uppercase border-b border-white/10">
                                            <th className="p-3 w-16">Sev</th>
                                            <th className="p-3">Time</th>
                                            <th className="p-3">CI Name</th>
                                            <th className="p-3">Message</th>
                                            <th className="p-3">Status</th>
                                            <th className="p-3 text-right">Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody className="text-sm divide-y divide-white/5">
                                        {activeEventsDisplay.length === 0 ? (
                                            <tr>
                                                <td colSpan={6} className="p-8 text-center text-neutral-600 italic">No active alarms. System healthy.</td>
                                            </tr>
                                        ) : (
                                            activeEventsDisplay.map(evt => (
                                                <tr key={evt.id} className="hover:bg-white/5 transition-colors group">
                                                    <td className="p-3">
                                                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${evt.severity === 'CRITICAL' ? 'bg-red-500/20 text-red-500 animate-pulse' : evt.severity === 'WARNING' ? 'bg-yellow-500/20 text-yellow-500' : 'bg-blue-500/20 text-blue-500'}`}>
                                                            <span className="material-symbols-outlined text-lg">{evt.severity === 'CRITICAL' ? 'dangerous' : evt.severity === 'WARNING' ? 'warning' : 'info'}</span>
                                                        </div>
                                                    </td>
                                                    <td className="p-3 text-xs text-neutral-400 whitespace-nowrap">
                                                        {new Date(evt.created_at).toLocaleTimeString()}
                                                        <div className="text-[10px] opacity-50">{new Date(evt.created_at).toLocaleDateString()}</div>
                                                    </td>
                                                    <td className="p-3 font-bold text-white">{evt.ci_name || evt.ci_id}</td>
                                                    <td className="p-3 text-neutral-300">
                                                        <div className="flex flex-col">
                                                            <span>{evt.message}</span>
                                                            {evt.relatedEvents && evt.relatedEvents.length > 0 && (
                                                                <div className="flex items-center gap-2 mt-1">
                                                                    <span className="px-2 py-0.5 rounded bg-black/40 border border-white/10 text-[10px] text-neutral-400 font-bold uppercase flex items-center gap-1">
                                                                        <span className="material-symbols-outlined text-[10px]">hub</span>
                                                                        {evt.relatedEvents.length} Correlated Events
                                                                    </span>
                                                                </div>
                                                            )}
                                                            {evt.comments && evt.comments.length > 0 && (
                                                                <div className="mt-1 text-xs text-neutral-500 flex items-center gap-1">
                                                                    <span className="material-symbols-outlined text-[10px]">chat</span>
                                                                    {evt.comments.length} updates
                                                                </div>
                                                            )}
                                                        </div>
                                                    </td>
                                                    <td className="p-3">
                                                        <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${evt.status === 'OPEN' ? 'bg-red-500 text-white' : evt.status === 'ACK' ? 'bg-blue-500 text-white' : 'bg-green-500 text-white'}`}>
                                                            {evt.status}
                                                        </span>
                                                    </td>
                                                    <td className="p-3 text-right">
                                                        <div className="flex justify-end gap-2 transition-opacity">
                                                            <button onClick={() => handleOpenComment(evt.id)} className="px-3 py-1 bg-neutral-700 hover:bg-neutral-600 text-brand-400 border border-brand-500/30 rounded text-xs font-bold uppercase flex items-center gap-1">
                                                                <span className="material-symbols-outlined text-[10px]">visibility</span> Details
                                                            </button>
                                                            {evt.status === 'OPEN' && (
                                                                <button onClick={() => handleAck(evt.id)} className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-bold uppercase">Ack</button>
                                                            )}
                                                            <button onClick={() => handleClose(evt.id)} className="px-3 py-1 bg-neutral-700 hover:bg-neutral-600 text-white rounded text-xs font-bold uppercase">Close</button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="h-full w-full relative">
                        <MapContainer center={[20.5937, -100.3906]} zoom={5} scrollWheelZoom={true} className="h-full w-full z-0" zoomControl={false} attributionControl={false}>
                            <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}" />
                            <MapBounds nodes={nodesWithEvents} />

                            {links.map((link, i) => {
                                const source = nodesWithEvents.find(n => n.id === link.source);
                                const target = nodesWithEvents.find(n => n.id === link.target);

                                if (source?.location?.lat && target?.location?.lat) {
                                    const latlngs: [number, number][] = [
                                        [source.location.lat, source.location.long],
                                        [target.location.lat, target.location.long]
                                    ];

                                    const status = target.hasCritical ? 'critical' : target.hasWarning ? 'warning' : 'normal';
                                    const type = link.relationship;

                                    const antPathOptions = status === 'critical'
                                        ? { delay: 1000, pulseColor: '#ff0000', weight: 4, color: STATUS_COLORS.CRITICAL, opacity: 0.8 }
                                        : status === 'warning'
                                            ? { delay: 2000, pulseColor: '#ffa500', weight: 3, color: STATUS_COLORS.WARNING, opacity: 0.7 }
                                            : { delay: 3000, pulseColor: '#3388ff', weight: 2, color: STATUS_COLORS.OK || '#3388ff', opacity: 0.6 };

                                    return (
                                        <AntPath
                                            key={`link-${i}`}
                                            latlngs={latlngs}
                                            status={status}
                                            type={type}
                                            options={antPathOptions}
                                        />
                                    );
                                }
                                return null;
                            })}

                            {nodesWithEvents.filter(n => n.location && n.location.lat).map(node => {
                                const isCritical = node.hasCritical;
                                const isWarning = node.hasWarning;
                                const isHealthy = !isCritical && !isWarning;

                                const critEvents = node.events?.filter(e => e.severity === 'CRITICAL').length || 0;
                                const warnEvents = node.events?.filter(e => e.severity === 'WARNING').length || 0;

                                const basePixelRadius = 6;
                                const pixelRadius = isCritical ? basePixelRadius * 1.5 + (critEvents * 2) :
                                    isWarning ? basePixelRadius * 1.2 + (warnEvents * 1.5) : basePixelRadius;

                                const color = isCritical ? '#ef4444' : isWarning ? '#eab308' : '#3b82f6';
                                const opacity = isHealthy ? 0.35 : 1;
                                const className = isHealthy ? '' : 'animate-pulse';

                                // Optional: Geographical aura rendering
                                const geoAuraRadius = isCritical ? 20000 + (critEvents * 10000) : isWarning ? 10000 + (warnEvents * 5000) : 0;

                                return (
                                    <React.Fragment key={node.id}>
                                        {/* Geographical aura for the 'blast radius' */}
                                        {!isHealthy && (
                                            <Circle
                                                center={[node.location!.lat, node.location!.long]}
                                                radius={geoAuraRadius}
                                                pathOptions={{ color: color, fillColor: color, fillOpacity: 0.1, weight: 0, className: 'animate-ping' }}
                                            />
                                        )}
                                        {/* Core point */}
                                        <CircleMarker
                                            center={[node.location!.lat, node.location!.long]}
                                            radius={pixelRadius}
                                            pathOptions={{ color: color, fillColor: color, fillOpacity: opacity, weight: isHealthy ? 1 : 2, opacity: opacity, className: className }}
                                        >
                                            <Popup>
                                                <div className="p-1 min-w-[200px]">
                                                    <h3 className="font-bold text-sm mb-1">{node.label}</h3>
                                                    <p className="text-xs text-neutral-500 mb-2">{node.ip}</p>
                                                    {node.events && node.events.length > 0 ? (
                                                        <div className="space-y-1">
                                                            {node.events.map(e => (
                                                                <div key={e.id} className={`text-xs p-1 rounded ${e.severity === 'CRITICAL' ? 'bg-red-100 text-red-800' : 'bg-yellow-100 text-yellow-800'}`}>
                                                                    {e.message}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    ) : (
                                                        <div className="text-green-500 text-xs font-bold">Status OK</div>
                                                    )}
                                                </div>
                                            </Popup>
                                        </CircleMarker>
                                    </React.Fragment>
                                );
                            })}
                        </MapContainer>

                        {/* Status Overlay */}
                        <div className="absolute top-4 right-4 p-4 glass rounded-xl border border-white/5 shadow-2xl z-[1000] min-w-[250px]">
                            <h4 className="text-xs font-bold text-neutral-400 uppercase mb-2">Live Status</h4>
                            <div className="space-y-2">
                                <div className="flex justify-between items-center">
                                    <span className="text-sm text-red-400">Critical Alerts</span>
                                    <span className="text-lg font-black text-white">{kpiCritical}</span>
                                </div>
                                <div className="flex justify-between items-center">
                                    <span className="text-sm text-yellow-400">Warnings</span>
                                    <span className="text-lg font-black text-white">{kpiWarning}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {commentModalOpen && selectedEventId && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 md:p-8">
                    <div className="bg-surface-900 border border-white/10 rounded-2xl w-full max-w-[95%] 2xl:max-w-[85%] h-full max-h-[90vh] shadow-2xl flex flex-col overflow-hidden animate-in fade-in zoom-in duration-200">
                        {/* Modal Header */}
                        <div className="p-6 border-b border-white/10 flex justify-between items-start bg-black/20">
                            <div>
                                <h3 className="text-2xl font-black text-white uppercase tracking-tight flex items-center gap-3">
                                    <span className={`px-3 py-1 rounded text-sm font-bold ${events.find(e => e.id === selectedEventId)?.severity === 'CRITICAL' ? 'bg-red-500' : events.find(e => e.id === selectedEventId)?.severity === 'WARNING' ? 'bg-yellow-500 text-black' : 'bg-blue-500'}`}>
                                        {events.find(e => e.id === selectedEventId)?.severity}
                                    </span>
                                    Event Details
                                </h3>
                                <div className="mt-2 text-neutral-400 text-sm flex gap-4">
                                    <span><strong>CI:</strong> {events.find(e => e.id === selectedEventId)?.ci_name}</span>
                                    <span><strong>Metric:</strong> {events.find(e => e.id === selectedEventId)?.metric_name}</span>
                                    <span><strong>Protocol:</strong> {events.find(e => e.id === selectedEventId)?.metric_protocol || 'N/A'}</span>
                                </div>
                            </div>
                            <button onClick={() => setCommentModalOpen(false)} className="text-neutral-500 hover:text-white transition-colors">
                                <span className="material-symbols-outlined">close</span>
                            </button>
                        </div>

                        <div className="flex-1 flex overflow-hidden">
                            {/* Left: Timeline (Fixed Width - Responsive) */}
                            <div className="w-[250px] lg:w-[300px] xl:w-[350px] flex-shrink-0 p-4 md:p-6 overflow-y-auto custom-scrollbar border-r border-white/10 flex flex-col bg-surface-900 transition-all">
                                <h4 className="text-sm font-bold text-neutral-400 uppercase mb-4 flex items-center gap-2">
                                    <span className="material-symbols-outlined text-brand-400">history</span>
                                    Investigation Timeline
                                </h4>
                                <div className="space-y-4 flex-1">
                                    <div className="relative pl-6 border-l-2 border-red-500/30 pb-4">
                                        <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-surface-900 border-2 border-red-500 flex items-center justify-center">
                                            <div className="w-1.5 h-1.5 bg-red-500 rounded-full"></div>
                                        </div>
                                        <div className="text-xs text-neutral-500 mb-1">{new Date(events.find(e => e.id === selectedEventId)?.created_at || '').toLocaleString()}</div>
                                        <div className="bg-white/5 p-3 rounded-lg border border-white/5 text-sm text-neutral-200">
                                            <span className="text-red-400 font-bold">EVENT TRIGGERED:</span> {events.find(e => e.id === selectedEventId)?.message}
                                        </div>
                                    </div>
                                    {events.find(e => e.id === selectedEventId)?.comments?.map((c, i) => (
                                        <div key={i} className="relative pl-6 border-l-2 border-brand-500/30 pb-4">
                                            <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-surface-900 border-2 border-brand-500 flex items-center justify-center">
                                                <span className="material-symbols-outlined text-[10px] text-brand-400">chat</span>
                                            </div>
                                            <div className="bg-black/30 p-3 rounded-lg border border-white/5 text-sm text-neutral-300 whitespace-pre-wrap font-mono">
                                                {c}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Middle: Topology Mini-Map (Fluid - Takes remaining space) */}
                            <div className="flex-1 border-r border-white/10 bg-black/20 flex flex-col min-w-[200px]">
                                <div className="p-4 md:p-6 border-b border-white/10 flex-1 flex flex-col min-h-0">
                                    <h4 className="text-sm font-bold text-neutral-400 uppercase mb-4 flex items-center gap-2 flex-shrink-0">
                                        <span className="material-symbols-outlined text-brand-400">hub</span>
                                        Dependency Impact
                                    </h4>
                                    <div className="flex-1 min-h-0 w-full relative">
                                        <DependencyMiniMap
                                            ciId={events.find(e => e.id === selectedEventId)?.ci_id}
                                            nodes={nodesWithEvents}
                                            links={links}
                                            event={events.find(e => e.id === selectedEventId)}
                                        />
                                    </div>
                                    <div className="mt-4 text-xs text-neutral-500 text-center italic flex-shrink-0">
                                        Visualizing direct dependencies and impact propagation.
                                    </div>
                                </div>
                            </div>

                            {/* Right: Actions & Related (Fixed Width - Responsive) */}
                            <div className="w-[250px] lg:w-[300px] xl:w-[320px] flex-shrink-0 bg-black/20 p-4 md:p-6 flex flex-col gap-6 dark-scroll-area overflow-y-auto transition-all">
                                <RelatedAlarmsPanel ciId={events.find(e => e.id === selectedEventId)?.ci_id} currentEventId={selectedEventId} />

                                <div className="border-t border-white/5 pt-4">
                                    <h4 className="text-xs font-bold text-neutral-500 uppercase mb-3">Quick Actions</h4>
                                    <div className="flex flex-col gap-2">
                                        {events.find(e => e.id === selectedEventId)?.status === 'OPEN' && (
                                            <button onClick={() => handleAck(selectedEventId!)} className="w-full py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-bold text-white flex items-center justify-center gap-2"><span className="material-symbols-outlined text-lg">check_circle</span>Acknowledge</button>
                                        )}
                                        <button onClick={() => handleClose(selectedEventId!)} className="w-full py-2 bg-neutral-700 hover:bg-neutral-600 rounded text-sm font-bold text-white flex items-center justify-center gap-2"><span className="material-symbols-outlined text-lg">cancel</span>Force Close</button>
                                    </div>
                                </div>
                                <div className="flex-1">
                                    <h4 className="text-xs font-bold text-neutral-500 uppercase mb-3 text-brand-400">Troubleshooting Tools</h4>
                                    <div className="bg-surface-950 rounded-xl p-1 shadow-inner border border-white/5">
                                        <div className="p-3">
                                            <div className="text-xs font-bold text-white mb-2">Automated Diagnostics</div>
                                            <button
                                                onClick={async () => {
                                                    setIsDiagnosing(true);
                                                    try {
                                                        await api.post(`/events/${selectedEventId}/diagnose`, {});
                                                        await fetchData();
                                                    } catch (e) {
                                                        console.error(e);
                                                    } finally {
                                                        setIsDiagnosing(false);
                                                    }
                                                }}
                                                disabled={isDiagnosing}
                                                className={`w-full py-2 border border-brand-500/30 rounded-lg text-xs font-bold uppercase transition-all flex items-center justify-center gap-2 ${isDiagnosing ? 'bg-brand-900/20 text-brand-500 cursor-wait' : 'bg-brand-900/50 hover:bg-brand-900 text-brand-400'}`}
                                            >
                                                <span className={`material-symbols-outlined text-sm ${isDiagnosing ? 'animate-spin' : ''}`}>
                                                    {isDiagnosing ? 'progress_activity' : 'build'}
                                                </span>
                                                {isDiagnosing ? 'Running Checks...' : 'Run Check'}
                                            </button>
                                        </div>
                                    </div>
                                </div>

                                <div>
                                    <h4 className="text-xs font-bold text-neutral-500 uppercase mb-3">Add Note</h4>
                                    <textarea className="w-full bg-black/50 border border-white/10 rounded-lg p-3 text-xs text-white outline-none focus:border-brand-500 h-24 resize-none mb-2" placeholder="Enter investigation notes..." value={commentText} onChange={e => setCommentText(e.target.value)} />
                                    <button onClick={submitComment} className="w-full py-2 bg-white/10 hover:bg-white/20 text-white rounded text-sm font-bold">Save Note</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )
            }
        </div >
    );
};

/**
 * StatCard Component
 * Displays a single KPI with an icon and optional animation.
 */
const StatCard = ({ label, value, icon, color, bg, animate }: any) => (
    <div className={`glass p-6 rounded-2xl border border-white/5 flex items-center justify-between group transform transition-all hover:scale-[1.02] ${bg || 'bg-white/5'} ${animate ? 'animate-pulse border-red-500/50' : ''}`}>
        <div>
            <p className="text-xs font-bold text-neutral-400 uppercase tracking-widest mb-1">{label}</p>
            <h3 className={`text-3xl font-black ${color}`}>{value}</h3>
        </div>
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${color} bg-black/20`}>
            <span className="material-symbols-outlined text-2xl">{icon}</span>
        </div>
    </div>
);

// --- Visualizations ---

// DependencyMiniMap moved to ./DependencyMiniMap

/**
 * RelatedAlarmsPanel Component
 * Shows other active alarms for the same CI, excluding the currently selected one.
 * Useful for spotting correlated issues (e.g. CPU High + Latency High).
 */
const RelatedAlarmsPanel = ({ ciId, currentEventId }: { ciId?: string, currentEventId?: string | null }) => {
    const [related, setRelated] = useState<any[]>([]);

    useEffect(() => {
        if (ciId) {
            api.get<any[]>(`/events/related/${ciId}`)
                .then(data => setRelated(data))
                .catch(err => console.error("Failed to load related events", err));
        }
    }, [ciId]);

    // Filter out current event
    const displayed = related.filter(e => e.id !== currentEventId);

    if (displayed.length === 0) return null;

    const getEventIcon = (msg: string) => {
        if (msg.includes("PING") || msg.includes("Unreachable")) return "wifi_off";
        if (msg.includes("SNMP") || msg.includes("Timeout")) return "sensors_off";
        if (msg.includes("CPU")) return "memory";
        if (msg.includes("Disk")) return "hard_drive";
        return "error"; // default
    };

    return (
        <div className="mb-2">
            <h4 className="text-xs font-bold text-neutral-500 uppercase mb-3 flex items-center gap-2">
                <span className="material-symbols-outlined text-orange-400 text-sm">warning</span>
                Related Alarms ({displayed.length})
            </h4>
            <div className="space-y-2">
                {displayed.map(evt => (
                    <div key={evt.id} className="bg-surface-950 p-2 rounded-lg border border-white/5 flex gap-3 text-xs items-center hover:bg-white/5 transition-colors cursor-default">
                        <div className={`w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0 ${evt.severity === 'CRITICAL' ? 'bg-red-500/10 text-red-500' : 'bg-yellow-500/10 text-yellow-500'}`}>
                            <span className="material-symbols-outlined text-lg">{getEventIcon(evt.message)}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="font-bold text-white mb-0.5 truncate">{evt.metric_name || 'System Alert'}</div>
                            <div className="text-neutral-400 leading-tight truncate">{evt.message}</div>
                        </div>
                        <div className="text-[10px] text-neutral-600 font-mono">
                            {new Date(evt.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default MonitoringConsole;
