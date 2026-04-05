import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, useMap, CircleMarker, Circle, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { GraphNode, Event } from '../types';
import { STATUS_COLORS } from '../utils/status';
import DependencyMiniMap from './DependencyMiniMap';
import { useEventCorrelation } from '../hooks/useEventCorrelation';
import L from 'leaflet';
import { useAuth } from '../context/AuthContext';
import { useEventMutations } from '../hooks/queries/useEventMutations';
import { useMonitoringConsoleData } from '../hooks/queries/useMonitoringConsoleData';
import { useRelatedEventsQuery } from '../hooks/queries/useRelatedEventsQuery';

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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LinkRenderConfig {
    color: string;
    weight: number;
    opacity: number;
    dashArray?: string;
    animate: boolean;
    animFrom: string;
    animTo: string;
    animDur: string;
    showTrafficPulse: boolean;
}

export interface NodeRenderConfig {
    color: string;
    pixelRadius: number;
    fillOpacity: number;
    weight: number;
    showAura: boolean;
    auraRadius: number;
}

// ---------------------------------------------------------------------------
// Pure helpers — exported for unit tests
// ---------------------------------------------------------------------------

/**
 * buildLinkConfig
 *
 * Determines how to render a map link based on relationship type and
 * the status of the target node. Pure function — no side effects.
 */
export function buildLinkConfig(
    link: { relationship?: string },
    source: { hasCritical?: boolean; hasWarning?: boolean },
    target: { hasCritical?: boolean; hasWarning?: boolean }
): LinkRenderConfig {
    // Use the worst status across BOTH endpoints so that a CRITICAL source
    // (e.g. an alarmed CI connecting toward the root) is always reflected in
    // the line color — not just when the target is the alarmed node.
    const isCritical = Boolean(source.hasCritical) || Boolean(target.hasCritical);
    const isWarning  = !isCritical && (Boolean(source.hasWarning) || Boolean(target.hasWarning));

    // Resolve base color from worst-endpoint status
    const color = isCritical
        ? STATUS_COLORS.CRITICAL   // '#ef4444'
        : isWarning
            ? STATUS_COLORS.WARNING    // '#f59e0b'
            : STATUS_COLORS.OK;        // '#10b981'

    const relationship = link.relationship ?? 'DEPENDS_ON';

    switch (relationship) {
        case 'CONNECTS_TO':
            return {
                color,
                weight: isCritical ? 5 : isWarning ? 4 : 3,
                opacity: 0.85,
                dashArray: undefined,
                animate: false,
                animFrom: '0',
                animTo: '0',
                animDur: '0s',
                showTrafficPulse: true,
            };

        case 'HOSTED_ON':
            return {
                // Keep subtle for HOSTED_ON but still reflect critical state
                color: isCritical ? STATUS_COLORS.CRITICAL : isWarning ? STATUS_COLORS.WARNING : 'rgba(156,163,175,0.5)',
                weight: isCritical ? 3 : isWarning ? 2 : 1.5,
                opacity: isCritical ? 0.6 : 0.45,
                dashArray: '2, 5',
                animate: false,
                animFrom: '0',
                animTo: '0',
                animDur: '0s',
                showTrafficPulse: false,
            };

        case 'DEPENDS_ON':
        default: {
            // +20% speed vs original: 1s→0.8s, 2s→1.6s, 3s→2.4s
            const dur = isCritical ? '0.8s' : isWarning ? '1.6s' : '2.4s';
            return {
                color,
                weight: isCritical ? 5 : isWarning ? 4 : 3,
                opacity: 0.9,
                dashArray: '6, 8',
                animate: true,
                animFrom: '28',
                animTo: '0',
                animDur: dur,
                showTrafficPulse: false,
            };
        }
    }
}

/**
 * getNodeRenderConfig
 *
 * Determines how to render a CI node marker on the map. Pure function.
 * Does NOT use Tailwind animate-pulse / animate-ping — those caused
 * full-map red flashing on critical events.
 */
export function getNodeRenderConfig(node: {
    hasCritical?: boolean;
    hasWarning?: boolean;
    events?: { severity: string }[];
}): NodeRenderConfig {
    const isCritical = Boolean(node.hasCritical);
    const isWarning = Boolean(node.hasWarning);
    const critCount = node.events?.filter(e => e.severity === 'CRITICAL').length ?? 0;
    const warnCount = node.events?.filter(e => e.severity === 'WARNING').length ?? 0;

    const BASE_RADIUS = 6;

    if (isCritical) {
        return {
            color: '#ef4444',
            pixelRadius: BASE_RADIUS * 1.5 + critCount * 2,
            fillOpacity: 1,
            weight: 2,
            showAura: true,
            auraRadius: 20000 + critCount * 10000,
        };
    }
    if (isWarning) {
        return {
            color: '#eab308',
            pixelRadius: BASE_RADIUS * 1.2 + warnCount * 1.5,
            fillOpacity: 1,
            weight: 2,
            showAura: true,
            auraRadius: 10000 + warnCount * 5000,
        };
    }
    return {
        color: '#3b82f6',
        pixelRadius: BASE_RADIUS,
        fillOpacity: 0.35,
        weight: 1,
        showAura: false,
        auraRadius: 0,
    };
}

/**
 * AnimatedPolyline
 *
 * Renders a Leaflet Polyline and optionally injects a declarative SVG <animate>
 * tag for stroke-dashoffset animation. Bypasses React-Leaflet's virtual DOM
 * intentionally — D3/SVG owns this DOM subtree after mount.
 *
 * Guard: `if (path.querySelector('animate')) return;` prevents duplicate tags
 * on the 10s re-render cycle triggered by MonitoringConsole's data polling.
 */
interface AnimationConfig {
    from: string;
    to: string;
    dur: string;
}

const AnimatedPolyline: React.FC<{
    positions: [number, number][];
    pathOptions: Record<string, unknown>;
    animationConfig: AnimationConfig | null;
}> = ({ positions, pathOptions, animationConfig }) => {
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
    }, [animationConfig]);

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
    const [filterCategory, setFilterCategory] = useState<string>('ALL');
    const { nodes, links, events, categories } = useMonitoringConsoleData();
    const eventMutations = useEventMutations();

    // --- Actions ---

    /**
     * Ackowledge an event (Operator is working on it).
     */
    const handleAck = async (id: string) => {
        await eventMutations.ackEvent(id);
    };

    // --- Comment / Modal State ---

    const [commentModalOpen, setCommentModalOpen] = useState(false);
    const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
    const [commentText, setCommentText] = useState("");
    const [isDiagnosing, setIsDiagnosing] = useState(false);

    // M5: Close flow state
    const [closeFlowOpen, setCloseFlowOpen] = useState(false);
    const [closeRootCause, setCloseRootCause] = useState('');
    const [closeNote, setCloseNote] = useState('');
    const [closeForcedMode, setCloseForcedMode] = useState(false);
    const [closeForcedReason, setCloseForcedReason] = useState('');

    // M2: Ownership — driven by real auth context
    const { user, hasPermission } = useAuth();
    const CURRENT_USER = user?.username ?? 'unknown';
    const CURRENT_TIER = user?.tier ?? 'T1';

    const handleOpenComment = (id: string) => {
        setSelectedEventId(id);
        setCommentText("");
        setCloseFlowOpen(false);
        setCloseRootCause('');
        setCloseNote('');
        setCloseForcedMode(false);
        setCloseForcedReason('');
        setCommentModalOpen(true);
    };

    const submitComment = async () => {
        if (!selectedEventId || !commentText.trim()) return;
        await eventMutations.commentEvent(selectedEventId, {
            message: commentText,
            user: CURRENT_USER
        });
        setCommentText("");
    };

    // M2: Take ownership
    const handleTakeCase = async (id: string) => {
        await eventMutations.takeEvent(id, {
            user: CURRENT_USER,
            tier: CURRENT_TIER,
        });
    };

    // M5: Structured close
    const handleStructuredClose = async () => {
        if (!selectedEventId) return;
        if (closeForcedMode) {
            if (!closeForcedReason.trim()) return;
            await eventMutations.commentEvent(selectedEventId, {
                message: `[CIERRE FORZADO — ${CURRENT_TIER}] Motivo: ${closeForcedReason}`,
                user: CURRENT_USER
            });
        } else {
            if (!closeRootCause || closeNote.trim().length < 20) return;
            await eventMutations.commentEvent(selectedEventId, {
                message: `[CIERRE] Causa raíz: ${closeRootCause}\nNota: ${closeNote}`,
                user: CURRENT_USER
            });
        }
        await eventMutations.closeEvent(selectedEventId, { forced: closeForcedMode });
        setCommentModalOpen(false);
        setCloseFlowOpen(false);
    };

    // --- Data Processing for Visualization ---

    const filteredNodes = filterCategory === 'ALL'
        ? nodes
        : nodes.filter(n => (n.category ?? n.type) === filterCategory);

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
                            const res: any = await eventMutations.pruneEvents();
                            alert(res.message);
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
                                    const positions: [number, number][] = [
                                        [source.location.lat, source.location.long],
                                        [target.location.lat, target.location.long]
                                    ];

                                    const cfg = buildLinkConfig(link, source, target);

                                    return (
                                        <React.Fragment key={`link-${i}`}>
                                            {/* Base line — animated for DEPENDS_ON, solid for CONNECTS_TO */}
                                            <AnimatedPolyline
                                                positions={positions}
                                                pathOptions={{
                                                    color: cfg.color,
                                                    weight: cfg.weight,
                                                    opacity: cfg.opacity,
                                                    dashArray: cfg.dashArray,
                                                }}
                                                animationConfig={cfg.animate
                                                    ? { from: cfg.animFrom, to: cfg.animTo, dur: cfg.animDur }
                                                    : null
                                                }
                                            />
                                            {/* Traffic-pulse overlay for CONNECTS_TO links — +20% speed (2.5s→2s) */}
                                            {cfg.showTrafficPulse && (
                                                <AnimatedPolyline
                                                    positions={positions}
                                                    pathOptions={{
                                                        color: '#10b981',
                                                        weight: cfg.weight,
                                                        opacity: 0.8,
                                                        dashArray: '5, 50',
                                                    }}
                                                    animationConfig={{ from: '0', to: '110', dur: '2s' }}
                                                />
                                            )}
                                        </React.Fragment>
                                    );
                                }
                                return null;
                            })}

                            {nodesWithEvents.filter(n => n.location && n.location.lat).map(node => {
                                const cfg = getNodeRenderConfig(node);

                                return (
                                    <React.Fragment key={node.id}>
                                        {/* Geographical aura — subtle border ring only, no fill to avoid map tinting */}
                                        {cfg.showAura && (
                                            <Circle
                                                center={[node.location!.lat, node.location!.long]}
                                                radius={cfg.auraRadius}
                                                pathOptions={{
                                                    color: cfg.color,
                                                    fillColor: '#1a1a2e',
                                                    fillOpacity: 0.04,
                                                    weight: 1,
                                                    opacity: 0.25,
                                                    dashArray: '4, 6',
                                                }}
                                            />
                                        )}
                                        {/* Core point — no animate-pulse, color drives urgency */}
                                        <CircleMarker
                                            center={[node.location!.lat, node.location!.long]}
                                            radius={cfg.pixelRadius}
                                            pathOptions={{
                                                color: cfg.color,
                                                fillColor: cfg.color,
                                                fillOpacity: cfg.fillOpacity,
                                                weight: cfg.weight,
                                                opacity: cfg.fillOpacity,
                                            }}
                                        >
                                            <Popup>
                                                <div className="p-1 min-w-[200px]">
                                                    <h3 className="font-bold text-sm mb-1">{node.label}</h3>
                                                    <p className="text-xs text-neutral-500 mb-2">{node.ip}</p>
                                                    {node.events && node.events.length > 0 ? (
                                                        <div className="space-y-1">
                                                            {node.events.map((e: any) => (
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

            {commentModalOpen && selectedEventId && (() => {
                const evt = events.find(e => e.id === selectedEventId);
                if (!evt) return null;

                const node = nodesWithEvents.find(n => n.id === evt.ci_id);
                const isAssigned = evt.ack && evt.ack_by;
                const assignedTo = evt.ack_by || null;

                // SLA calculation (mock — field not in model yet)
                const slaMinutes: number | null = (node?.metadata?.sla_minutes as number) ?? null;
                const ageMs = Date.now() - new Date(evt.created_at).getTime();
                const ageMinutes = Math.floor(ageMs / 60000);
                const slaRemaining = slaMinutes !== null ? slaMinutes - ageMinutes : null;
                const slaCritical = slaRemaining !== null && slaRemaining <= 30;

                // M3: Parse timeline entries from comments[]
                const parseTimelineEntry = (raw: string) => {
                    const diagMatch = raw.match(/^DIAGNOSTIC RUN BY (.+?):\n([\s\S]*)$/);
                    if (diagMatch) return { type: 'diagnostic' as const, user: diagMatch[1], body: diagMatch[2], raw };
                    const ownerMatch = raw.match(/^\[OWNERSHIP\] (.+)$/m);
                    if (ownerMatch) return { type: 'ownership' as const, user: '', body: ownerMatch[1], raw };
                    const closeMatch = raw.match(/^\[CIERRE/);
                    if (closeMatch) return { type: 'close' as const, user: '', body: raw, raw };
                    const forceMatch = raw.match(/^\[CIERRE FORZADO/);
                    if (forceMatch) return { type: 'force_close' as const, user: '', body: raw, raw };
                    // Standard format: "user: message (datetime)"
                    const stdMatch = raw.match(/^(.+?):\s([\s\S]+?)\s\((.+)\)$/);
                    if (stdMatch) return { type: 'note' as const, user: stdMatch[1], body: stdMatch[2], ts: stdMatch[3], raw };
                    return { type: 'note' as const, user: 'Sistema', body: raw, raw };
                };

                const timelineEntries = (evt.comments || []).map(parseTimelineEntry);

                const entryIcon = (type: string) => {
                    if (type === 'diagnostic') return { icon: 'build', color: 'border-brand-500 text-brand-400' };
                    if (type === 'ownership') return { icon: 'person_check', color: 'border-emerald-500 text-emerald-400' };
                    if (type === 'close' || type === 'force_close') return { icon: 'check_circle', color: 'border-neutral-500 text-neutral-400' };
                    return { icon: 'chat', color: 'border-brand-500 text-brand-400' };
                };

                // M5 close button state
                const canClose = closeForcedMode
                    ? closeForcedReason.trim().length > 0
                    : closeRootCause !== '' && closeNote.trim().length >= 20;

                return (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 md:p-6">
                    <div className="bg-[#0f1117] border border-white/10 rounded-2xl w-full max-w-[96%] 2xl:max-w-[88%] h-full max-h-[92vh] shadow-2xl flex flex-col overflow-hidden">

                        {/* ── M1: Header — Banda de Contexto de Negocio ── */}
                        <div className="flex-shrink-0 border-b border-white/10 bg-black/30">
                            {/* Top row: severity badge + title + close */}
                            <div className="px-6 pt-5 pb-3 flex justify-between items-start gap-4">
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-3 flex-wrap">
                                        <span className={`px-3 py-1 rounded text-xs font-black uppercase tracking-wider flex-shrink-0 ${evt.severity === 'CRITICAL' ? 'bg-red-500 text-white' : evt.severity === 'WARNING' ? 'bg-yellow-400 text-black' : 'bg-blue-500 text-white'}`}>
                                            {evt.severity}
                                        </span>
                                        <h3 className="text-xl font-black text-white uppercase tracking-tight truncate">{evt.message}</h3>
                                    </div>
                                     <div className="mt-2 text-neutral-400 text-xs flex flex-wrap gap-x-4 gap-y-1">
                                        <span>
                                            <strong className="text-neutral-300">CI ID:</strong>{' '}
                                            {evt.ci_node_id
                                                ? <span className="font-mono text-brand-400">{evt.ci_node_id}</span>
                                                : <span className="text-neutral-600 italic">—</span>}
                                        </span>
                                        <span>
                                            <strong className="text-neutral-300">Host:</strong>{' '}
                                            {evt.ci_name
                                                ? <span className="text-white">{evt.ci_name}</span>
                                                : <span className="text-neutral-600 italic">—</span>}
                                            {evt.ci_hostname && (
                                                <span className="text-neutral-500 ml-1">({evt.ci_hostname})</span>
                                            )}
                                        </span>
                                        {evt.ci_location_name && (
                                            <span>
                                                <strong className="text-neutral-300">Ubicación:</strong>{' '}
                                                <span className="text-white">{evt.ci_location_name}</span>
                                            </span>
                                        )}
                                        <span><strong className="text-neutral-300">Métrica:</strong> {evt.metric_name || '—'}</span>
                                        <span><strong className="text-neutral-300">Protocolo:</strong> {evt.metric_protocol || 'N/A'}</span>
                                        <span><strong className="text-neutral-300">Inicio:</strong> {new Date(evt.created_at).toLocaleString()}</span>
                                    </div>
                                </div>
                                <button onClick={() => setCommentModalOpen(false)} className="text-neutral-500 hover:text-white transition-colors flex-shrink-0 mt-1">
                                    <span className="material-symbols-outlined">close</span>
                                </button>
                            </div>

                            {/* Business context strip */}
                            <div className="px-6 pb-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                                <div className="bg-white/5 rounded-lg px-3 py-2 text-xs">
                                    <div className="text-neutral-500 uppercase font-bold tracking-wider mb-0.5">Servicio de negocio</div>
                                    <div className="text-white font-semibold truncate">{(node?.metadata?.business_service as string) || <span className="text-neutral-600 italic">No configurado</span>}</div>
                                </div>
                                <div className="bg-white/5 rounded-lg px-3 py-2 text-xs">
                                    <div className="text-neutral-500 uppercase font-bold tracking-wider mb-0.5">Usuarios impactados</div>
                                    <div className="text-white font-semibold">{(node?.metadata?.impacted_users as string) || <span className="text-neutral-600 italic">No configurado</span>}</div>
                                </div>
                                 <div className="bg-white/5 rounded-lg px-3 py-2 text-xs">
                                    <div className="text-neutral-500 uppercase font-bold tracking-wider mb-0.5">Sede</div>
                                     <div className="text-white font-semibold">
                                        {evt.ci_location_name
                                            ? evt.ci_location_name
                                            : node?.locationName
                                                ? node.locationName
                                                : (node?.metadata?.site as string)
                                                    ? (node?.metadata?.site as string)
                                                    : <span className="text-neutral-600 italic">No configurado</span>}
                                    </div>
                                </div>
                                <div className="bg-white/5 rounded-lg px-3 py-2 text-xs">
                                    <div className="text-neutral-500 uppercase font-bold tracking-wider mb-0.5">Categoría CI</div>
                                    <div className="text-white font-semibold">{node?.category || node?.type || <span className="text-neutral-600 italic">No configurado</span>}</div>
                                </div>
                                <div className={`rounded-lg px-3 py-2 text-xs ${slaCritical ? 'bg-red-500/20 border border-red-500/40' : 'bg-white/5'}`}>
                                    <div className={`uppercase font-bold tracking-wider mb-0.5 ${slaCritical ? 'text-red-400' : 'text-neutral-500'}`}>SLA Restante</div>
                                    <div className={`font-black text-sm ${slaCritical ? 'text-red-400' : 'text-white'}`}>
                                        {slaRemaining !== null
                                            ? slaCritical
                                                ? `⚠ ${slaRemaining} min`
                                                : `${slaRemaining} min`
                                            : <span className="text-neutral-600 italic text-xs">No configurado</span>
                                        }
                                    </div>
                                </div>
                            </div>

                            {/* ── M2: Ownership Bar ── */}
                            <div className={`px-6 py-2 border-t border-white/5 flex flex-wrap items-center gap-4 text-xs ${!isAssigned ? 'bg-red-950/30' : 'bg-black/20'}`}>
                                {/* Assigned to */}
                                <div className="flex items-center gap-2">
                                    <span className="material-symbols-outlined text-sm text-neutral-500">person</span>
                                    {isAssigned ? (
                                        <span className="text-white font-bold">{assignedTo}</span>
                                    ) : (
                                        <span className="flex items-center gap-2">
                                            <span className="text-red-400 font-bold animate-pulse">Sin asignar</span>
                                            <button
                                                onClick={() => handleTakeCase(evt.id)}
                                                className="px-2 py-0.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-bold uppercase tracking-wide transition-colors"
                                            >Tomar caso</button>
                                        </span>
                                    )}
                                </div>
                                <div className="w-px h-4 bg-white/10" />
                                {/* Tier */}
                                <div className="flex items-center gap-1.5">
                                    <span className="text-neutral-500 uppercase font-bold">Tier:</span>
                                    <span className="px-2 py-0.5 bg-brand-600/30 border border-brand-500/40 rounded text-brand-300 font-black">{CURRENT_TIER}</span>
                                </div>
                                <div className="w-px h-4 bg-white/10" />
                                {/* Estado */}
                                <div className="flex items-center gap-1.5">
                                    <span className="text-neutral-500 uppercase font-bold">Estado:</span>
                                    <span className={`px-2 py-0.5 rounded font-black uppercase text-[10px] ${
                                        evt.status === 'OPEN' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                                        evt.status === 'ACK'  ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30' :
                                        'bg-neutral-500/20 text-neutral-400 border border-neutral-500/30'
                                    }`}>{
                                        evt.status === 'OPEN' ? 'Nuevo' :
                                        evt.status === 'ACK'  ? 'En atención' :
                                        evt.status === 'CLOSED' ? 'Cerrado' : evt.status
                                    }</span>
                                </div>
                                <div className="w-px h-4 bg-white/10" />
                                {/* Opened by */}
                                <div className="flex items-center gap-1.5">
                                    <span className="text-neutral-500 uppercase font-bold">Abierto por:</span>
                                    <span className="text-neutral-300">Sistema / SNMP Collector</span>
                                </div>
                                <div className="w-px h-4 bg-white/10" />
                                {/* Age */}
                                <div className="flex items-center gap-1.5">
                                    <span className="text-neutral-500 uppercase font-bold">Tiempo activo:</span>
                                    <span className="text-neutral-200 font-mono">{ageMinutes < 60 ? `${ageMinutes}m` : `${Math.floor(ageMinutes/60)}h ${ageMinutes%60}m`}</span>
                                </div>
                            </div>
                        </div>

                        {/* ── Body: 3 columns ── */}
                        <div className="flex-1 flex overflow-hidden min-h-0">

                            {/* Left: M3 Timeline */}
                            <div className="w-[270px] lg:w-[310px] xl:w-[360px] flex-shrink-0 flex flex-col border-r border-white/10 bg-[#0f1117]">
                                <div className="px-5 pt-5 pb-3 flex-shrink-0 border-b border-white/5">
                                    <h4 className="text-xs font-black text-neutral-400 uppercase tracking-widest flex items-center gap-2">
                                        <span className="material-symbols-outlined text-brand-400 text-sm">history</span>
                                        Timeline de Investigación
                                    </h4>
                                    <p className="text-[10px] text-neutral-600 mt-1">Registro append-only · fuente de auditoría</p>
                                </div>
                                <div className="flex-1 overflow-y-auto custom-scrollbar px-5 py-4 space-y-3">
                                    {/* Fixed first entry */}
                                    <div className="relative pl-6 border-l-2 border-red-500/40 pb-3">
                                        <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-[#0f1117] border-2 border-red-500 flex items-center justify-center">
                                            <div className="w-1.5 h-1.5 bg-red-500 rounded-full" />
                                        </div>
                                        <div className="text-[10px] text-neutral-600 font-mono mb-1">{new Date(evt.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · Sistema · Evento disparador</div>
                                        <div className="bg-red-950/30 border border-red-500/20 p-2.5 rounded-lg text-xs text-red-200 leading-relaxed">
                                            <span className="font-black text-red-400">DISPARADOR:</span> {evt.message}
                                        </div>
                                    </div>

                                    {/* Dynamic entries */}
                                    {timelineEntries.map((entry, i) => {
                                        const { icon, color } = entryIcon(entry.type);
                                        return (
                                            <div key={i} className={`relative pl-6 border-l-2 ${color.includes('emerald') ? 'border-emerald-500/30' : color.includes('neutral') ? 'border-neutral-500/30' : 'border-brand-500/30'} pb-3`}>
                                                <div className={`absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-[#0f1117] border-2 ${color.includes('emerald') ? 'border-emerald-500' : color.includes('neutral') ? 'border-neutral-500' : 'border-brand-500'} flex items-center justify-center`}>
                                                    <span className={`material-symbols-outlined text-[8px] ${color.split(' ')[1]}`}>{icon}</span>
                                                </div>
                                                <div className={`text-[10px] font-mono mb-1 ${color.includes('emerald') ? 'text-emerald-600' : color.includes('neutral') ? 'text-neutral-600' : 'text-neutral-600'}`}>
                                                    {entry.ts ? new Date(entry.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'} · {entry.user || CURRENT_USER} · {
                                                        entry.type === 'diagnostic' ? 'Diagnóstico ejecutado' :
                                                        entry.type === 'ownership' ? 'Ownership asignado' :
                                                        entry.type === 'close' ? 'Evento cerrado' :
                                                        entry.type === 'force_close' ? 'Cierre forzado' :
                                                        'Nota de investigación'
                                                    }
                                                </div>
                                                <div className={`p-2.5 rounded-lg text-xs leading-relaxed whitespace-pre-wrap font-mono border ${
                                                    entry.type === 'diagnostic' ? 'bg-brand-950/30 border-brand-500/15 text-brand-200' :
                                                    entry.type === 'ownership' ? 'bg-emerald-950/30 border-emerald-500/15 text-emerald-200' :
                                                    entry.type === 'close' || entry.type === 'force_close' ? 'bg-neutral-900/50 border-neutral-700/30 text-neutral-300' :
                                                    'bg-white/5 border-white/5 text-neutral-300'
                                                }`}>
                                                    {entry.body}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>

                                {/* Add note */}
                                <div className="flex-shrink-0 border-t border-white/5 px-5 py-4">
                                    <h4 className="text-[10px] font-black text-neutral-500 uppercase tracking-widest mb-2">Agregar nota</h4>
                                    <textarea
                                        className="w-full bg-black/50 border border-white/10 rounded-lg p-2.5 text-xs text-white outline-none focus:border-brand-500 h-20 resize-none mb-2"
                                        placeholder="Escribe tus notas de investigación..."
                                        value={commentText}
                                        onChange={e => setCommentText(e.target.value)}
                                    />
                                    <button
                                        onClick={submitComment}
                                        disabled={!commentText.trim()}
                                        className="w-full py-2 bg-brand-700 hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-xs font-bold transition-colors"
                                    >Guardar nota</button>
                                </div>
                            </div>

                            {/* Center: M4 Dependency Impact (dominant) */}
                            <div className="flex-1 flex flex-col min-w-0 bg-black/20 border-r border-white/10">
                                <div className="px-5 pt-5 pb-3 flex-shrink-0 border-b border-white/5 flex items-center justify-between">
                                    <h4 className="text-xs font-black text-neutral-400 uppercase tracking-widest flex items-center gap-2">
                                        <span className="material-symbols-outlined text-brand-400 text-sm">hub</span>
                                        Mapa de Impacto y Dependencias
                                    </h4>
                                    <span className="text-[10px] text-neutral-600">Arrastra para mover · Scroll para zoom</span>
                                </div>
                                <div className="flex-1 min-h-0 p-4">
                                    <DependencyMiniMap
                                        ciId={evt.ci_id}
                                        nodes={nodesWithEvents}
                                        links={links}
                                        event={evt}
                                    />
                                </div>
                                <div className="flex-shrink-0 px-5 pb-3 text-[10px] text-neutral-600 text-center italic">
                                    Blast radius visualizado hasta 3 niveles de dependencia directa
                                </div>
                            </div>

                            {/* Right: Actions */}
                            <div className="w-[260px] lg:w-[300px] xl:w-[330px] flex-shrink-0 flex flex-col bg-[#0f1117] overflow-y-auto custom-scrollbar">

                                {/* Related alarms */}
                                <div className="px-5 pt-5 pb-3 border-b border-white/5">
                                    <RelatedAlarmsPanel ciId={evt.ci_id} currentEventId={selectedEventId} />
                                </div>

                                {/* Quick actions */}
                                <div className="px-5 py-4 border-b border-white/5">
                                    <h4 className="text-[10px] font-black text-neutral-500 uppercase tracking-widest mb-3">Acciones rápidas</h4>
                                    <div className="flex flex-col gap-2">
                                        {evt.status === 'OPEN' && (
                                            <button
                                                onClick={() => handleAck(selectedEventId!)}
                                                className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-bold text-white flex items-center justify-center gap-2 transition-colors"
                                            >
                                                <span className="material-symbols-outlined text-base">check_circle</span>
                                                Reconocer (Ack)
                                            </button>
                                        )}

                                        {/* M5: Close flow */}
                                        {!closeFlowOpen ? (
                                            <button
                                                onClick={() => setCloseFlowOpen(true)}
                                                className="w-full py-2.5 bg-neutral-800 hover:bg-neutral-700 border border-white/10 rounded-lg text-sm font-bold text-neutral-300 flex items-center justify-center gap-2 transition-colors"
                                            >
                                                <span className="material-symbols-outlined text-base">cancel</span>
                                                Cerrar Evento
                                            </button>
                                        ) : (
                                            <div className="bg-neutral-900/80 border border-white/10 rounded-xl p-4 space-y-3">
                                                <div className="flex items-center justify-between">
                                                    <h5 className="text-xs font-black text-white uppercase">Cierre de Evento</h5>
                                                    <button onClick={() => setCloseFlowOpen(false)} className="text-neutral-600 hover:text-white">
                                                        <span className="material-symbols-outlined text-sm">close</span>
                                                    </button>
                                                </div>

                                                {!closeForcedMode ? (
                                                    <>
                                                        {/* Step 1: Root cause */}
                                                        <div>
                                                            <label className="text-[10px] font-bold text-neutral-500 uppercase block mb-1">
                                                                1. Causa raíz <span className="text-red-500">*</span>
                                                            </label>
                                                            <select
                                                                value={closeRootCause}
                                                                onChange={e => setCloseRootCause(e.target.value)}
                                                                className="w-full bg-black/50 border border-white/10 rounded-lg p-2 text-xs text-white outline-none focus:border-brand-500"
                                                            >
                                                                <option value="">Seleccionar causa...</option>
                                                                <option value="Falla de hardware">Falla de hardware</option>
                                                                <option value="Error de configuración">Error de configuración</option>
                                                                <option value="Problema de capacidad / recursos">Problema de capacidad / recursos</option>
                                                                <option value="Falla de proveedor / enlace externo">Falla de proveedor / enlace externo</option>
                                                                <option value="Causa desconocida">Causa desconocida (requiere nota)</option>
                                                            </select>
                                                        </div>

                                                        {/* Step 2: Close note */}
                                                        <div>
                                                            <label className="text-[10px] font-bold text-neutral-500 uppercase block mb-1">
                                                                2. Nota de cierre <span className="text-neutral-600">(mín. 20 chars)</span> <span className="text-red-500">*</span>
                                                            </label>
                                                            <textarea
                                                                value={closeNote}
                                                                onChange={e => setCloseNote(e.target.value)}
                                                                placeholder="Describe la resolución del incidente..."
                                                                className="w-full bg-black/50 border border-white/10 rounded-lg p-2 text-xs text-white outline-none focus:border-brand-500 h-20 resize-none"
                                                            />
                                                            <div className={`text-[10px] mt-0.5 text-right ${closeNote.length < 20 ? 'text-neutral-600' : 'text-emerald-500'}`}>
                                                                {closeNote.length}/20 mín
                                                            </div>
                                                        </div>

                                                        <button
                                                            onClick={handleStructuredClose}
                                                            disabled={!canClose}
                                                            className="w-full py-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg text-xs font-black uppercase transition-colors"
                                                        >Confirmar Cierre</button>

                                                        {/* Forced close — requires EVENT_FORCED_CLOSE permission */}
                                                        {hasPermission('EVENT_FORCED_CLOSE') && (
                                                            <button
                                                                onClick={() => setCloseForcedMode(true)}
                                                                className="w-full py-1.5 text-[10px] text-neutral-600 hover:text-red-400 transition-colors uppercase font-bold"
                                                            >Cierre forzado ({CURRENT_TIER})</button>
                                                        )}
                                                    </>
                                                ) : (
                                                    <>
                                                        <div className="text-[10px] text-red-400 font-bold uppercase bg-red-950/30 border border-red-500/20 rounded px-2 py-1">
                                                            ⚠ Cierre forzado — quedará registrado en el timeline
                                                        </div>
                                                        <textarea
                                                            value={closeForcedReason}
                                                            onChange={e => setCloseForcedReason(e.target.value)}
                                                            placeholder="Motivo del cierre forzado..."
                                                            className="w-full bg-black/50 border border-red-500/30 rounded-lg p-2 text-xs text-white outline-none focus:border-red-500 h-20 resize-none"
                                                        />
                                                        <div className="flex gap-2">
                                                            <button onClick={() => setCloseForcedMode(false)} className="flex-1 py-2 bg-neutral-800 text-neutral-400 rounded-lg text-xs font-bold">Cancelar</button>
                                                            <button
                                                                onClick={handleStructuredClose}
                                                                disabled={!canClose}
                                                                className="flex-1 py-2 bg-red-700 hover:bg-red-600 disabled:opacity-40 text-white rounded-lg text-xs font-black transition-colors"
                                                            >Forzar Cierre</button>
                                                        </div>
                                                    </>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* Diagnostics */}
                                <div className="px-5 py-4">
                                    <h4 className="text-[10px] font-black text-brand-400 uppercase tracking-widest mb-3">Herramientas de Diagnóstico</h4>
                                    <div className="bg-black/40 rounded-xl border border-white/5 p-3">
                                        <div className="text-xs font-bold text-white mb-2">Diagnóstico automatizado</div>
                                        <button
                                            onClick={async () => {
                                                setIsDiagnosing(true);
                                                try {
                                                    await eventMutations.diagnoseEvent(selectedEventId, { user: CURRENT_USER });
                                                } catch (e) { console.error(e); }
                                                finally { setIsDiagnosing(false); }
                                            }}
                                            disabled={isDiagnosing}
                                            className={`w-full py-2.5 border border-brand-500/30 rounded-lg text-xs font-bold uppercase transition-all flex items-center justify-center gap-2 ${isDiagnosing ? 'bg-brand-900/20 text-brand-500 cursor-wait' : 'bg-brand-900/50 hover:bg-brand-900 text-brand-400'}`}
                                        >
                                            <span className={`material-symbols-outlined text-sm ${isDiagnosing ? 'animate-spin' : ''}`}>
                                                {isDiagnosing ? 'progress_activity' : 'build'}
                                            </span>
                                            {isDiagnosing ? 'Ejecutando...' : 'Ejecutar diagnóstico'}
                                        </button>
                                        <p className="text-[10px] text-neutral-600 mt-2 leading-relaxed">El resultado se registrará automáticamente en el timeline.</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                );
            })()}
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
    const { data: related = [] } = useRelatedEventsQuery(ciId);

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
