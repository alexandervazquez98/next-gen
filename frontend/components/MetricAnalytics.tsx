import React, { useState, useEffect } from 'react';
import { GraphNode, MetricDef } from '../types';
import MetricHistoryChart from './MetricHistoryChart';
import { api } from '../services/api';

const MetricAnalytics: React.FC = () => {
    const [nodes, setNodes] = useState<GraphNode[]>([]);
    const [selectedNodeId, setSelectedNodeId] = useState<string>('');
    const [selectedMetric, setSelectedMetric] = useState<any | null>(null);
    const [loading, setLoading] = useState(true);
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');

    // Fetch Nodes on Mount
    useEffect(() => {
        const fetchData = async () => {
            try {
                const data = await api.get<GraphNode[]>('/nodes');
                if (Array.isArray(data)) {
                    setNodes(data);
                    // Default select first one if available
                    if (data.length > 0) setSelectedNodeId(data[0].id);
                }
            } catch (err) {
                console.error("Failed to fetch nodes for Analytics", err);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, []);

    const selectedNode = nodes.find(n => n.id === selectedNodeId);

    // Update available metrics when node changes
    useEffect(() => {
        if (selectedNode && selectedNode.metrics && selectedNode.metrics.length > 0) {
            setSelectedMetric(selectedNode.metrics[0]);
        } else {
            setSelectedMetric(null);
        }
    }, [selectedNodeId, nodes]);

    const handleResetDateRange = () => {
        setStartDate('');
        setEndDate('');
    };

    return (
        <div className="flex flex-col h-full bg-surface-950 text-white p-8 overflow-hidden">
            <header className="mb-8 flex justify-between items-end">
                <div>
                    <h1 className="text-3xl font-black uppercase tracking-tighter">Metric Analytics</h1>
                    <p className="text-neutral-500 font-mono text-sm mt-1">Historical Telemetry Visualization</p>
                </div>
            </header>

            <div className="grid grid-cols-12 gap-8 h-full">
                {/* Controls Sidebar */}
                <div className="col-span-12 lg:col-span-3 space-y-6 flex flex-col h-full overflow-hidden">
                    {/* Node Selector */}
                    <div className="bg-surface-900 border border-white/5 rounded-xl p-5 mb-0">
                        <label className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2 block">Select Resource (CI)</label>
                        <select
                            value={selectedNodeId}
                            onChange={(e) => setSelectedNodeId(e.target.value)}
                            className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-3 text-sm text-white focus:border-brand-500 outline-none transition-colors appearance-none"
                        >
                            <option value="" disabled>Select a CI...</option>
                            {nodes.map(n => (
                                <option key={n.id} value={n.id}>
                                    {n.label || n.id} ({n.ip || 'No IP'})
                                </option>
                            ))}
                        </select>
                        {selectedNode && (
                            <div className="mt-4 p-3 bg-white/5 rounded-lg border border-white/5">
                                <div className="flex items-center gap-2 mb-2">
                                    <span className={`w-2 h-2 rounded-full ${selectedNode.status === 'OK' ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
                                    <span className="text-xs font-bold">{selectedNode.status}</span>
                                </div>
                                <p className="text-[10px] text-neutral-500 font-mono break-all">{selectedNode.id}</p>
                            </div>
                        )}
                    </div>

                    {/* Date Range Selector */}
                    <div className="bg-surface-900 border border-white/5 rounded-xl p-5">
                        <label className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2 block">Custom Time Range</label>
                        <div className="space-y-3">
                            <div>
                                <label className="text-[10px] text-neutral-400 block mb-1">Start Date</label>
                                <input
                                    type="datetime-local"
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-xs text-white outline-none focus:border-brand-500"
                                    value={startDate}
                                    onChange={(e) => setStartDate(e.target.value)}
                                />
                            </div>
                            <div>
                                <label className="text-[10px] text-neutral-400 block mb-1">End Date</label>
                                <input
                                    type="datetime-local"
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-xs text-white outline-none focus:border-brand-500"
                                    value={endDate}
                                    onChange={(e) => setEndDate(e.target.value)}
                                />
                            </div>
                            {startDate && endDate && (
                                <button
                                    onClick={handleResetDateRange}
                                    className="w-full mt-2 bg-white/5 hover:bg-white/10 text-neutral-300 text-xs font-bold py-2 rounded-lg uppercase transition-colors"
                                >
                                    Reset to Live View
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Metric Selector */}
                    <div className="bg-surface-900 border border-white/5 rounded-xl p-5 flex-1 overflow-y-auto min-h-0">
                        <label className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3 block">Available Metrics</label>
                        <div className="space-y-2">
                            {selectedNode?.metrics?.map((m, idx) => (
                                <button
                                    key={idx}
                                    onClick={() => setSelectedMetric(m)}
                                    className={`w-full text-left p-3 rounded-lg border transition-all flex items-center justify-between ${selectedMetric?.name === m.name
                                        ? 'bg-brand-500/20 border-brand-500/50 text-white'
                                        : 'bg-white/5 border-transparent text-neutral-400 hover:bg-white/10'
                                        }`}
                                >
                                    <div>
                                        <p className="text-xs font-bold uppercase">{m.name}</p>
                                        <p className="text-[10px] opacity-60 font-mono mt-0.5">{m.protocol}</p>
                                    </div>
                                    <span className={`w-2 h-2 rounded-full ${m.status === 'OK' ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
                                </button>
                            ))}
                            {(!selectedNode?.metrics || selectedNode.metrics.length === 0) && (
                                <p className="text-xs text-neutral-600 text-center py-4">No metrics available for this CI.</p>
                            )}
                        </div>
                    </div>
                </div>

                {/* Main Chart Area */}
                <div className="col-span-12 lg:col-span-9 flex flex-col gap-6 h-full overflow-hidden pb-8">
                    {selectedNode && selectedMetric ? (
                        <div className="flex-1 bg-surface-900 border border-white/5 rounded-xl p-8 relative overflow-hidden flex flex-col">
                            {/* Background Pattern */}
                            <div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none">
                                <span className="material-symbols-outlined text-9xl">monitoring</span>
                            </div>

                            <div className="relative z-10 flex-1 flex flex-col min-h-0">
                                <MetricHistoryChart
                                    nodeId={selectedNode.id}
                                    metricId={selectedMetric.name}
                                    metricName={selectedMetric.name}
                                    unit={selectedMetric.unit}
                                    customRange={startDate && endDate ? { start: new Date(startDate).toISOString(), end: new Date(endDate).toISOString() } : null}
                                />

                                <div className="mt-8 grid grid-cols-3 gap-6 flex-shrink-0">
                                    <StatCard label="Current Value" value={selectedMetric.value} unit={selectedMetric.unit} />
                                    <StatCard label="Status" value={selectedMetric.status} isStatus />
                                    <StatCard label="Last Updated" value={selectedMetric.last_updated} isDate />
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="flex-1 bg-surface-900 border border-dashed border-white/10 rounded-xl flex items-center justify-center flex-col text-neutral-600">
                            <span className="material-symbols-outlined text-6xl mb-4 opacity-20">analytics</span>
                            <p className="font-bold uppercase tracking-widest">Select a CI and Metric</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

const StatCard: React.FC<{ label: string, value: any, unit?: string, isStatus?: boolean, isDate?: boolean }> = ({ label, value, unit, isStatus, isDate }) => {
    let displayValue = value ?? '--';
    let colorClass = 'text-white';

    if (isStatus) {
        if (value === 'OK') colorClass = 'text-emerald-500';
        else if (value === 'CRITICAL') colorClass = 'text-red-500';
        else if (value === 'WARNING') colorClass = 'text-orange-500';
    } else if (isDate && value) {
        displayValue = new Date(value).toLocaleString();
        colorClass = 'text-neutral-300 text-sm';
    }

    return (
        <div className="bg-black/20 rounded-lg p-4 border border-white/5">
            <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-1">{label}</p>
            <p className={`text-2xl font-black tracking-tight ${colorClass}`}>
                {displayValue} <span className="text-xs text-neutral-500 font-normal">{unit}</span>
            </p>
        </div>
    );
};

export default MetricAnalytics;
