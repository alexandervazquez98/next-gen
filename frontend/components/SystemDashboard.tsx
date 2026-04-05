import React from 'react';
import Tooltip from './Tooltip';
import { useSystemStatusQuery } from '../hooks/queries/useSystemStatusQuery';

const SystemDashboard: React.FC = () => {
    const { data: status, isLoading: loading } = useSystemStatusQuery();

    const getStatusColor = (val: number) => {
        if (val >= 90) return 'text-red-500';
        if (val >= 70) return 'text-amber-400';
        return 'text-emerald-400';
    };

    const getBarColor = (val: number) => {
        if (val >= 90) return 'bg-red-500';
        if (val >= 70) return 'bg-amber-400';
        return 'bg-emerald-400';
    };

    if (loading && !status) return <div className="p-8 text-neutral-500 animate-pulse">Initializing System Telemetry...</div>;

    if (!status) return <div className="p-8 text-red-500">System Telemetry Unavailable</div>;

    return (
        <div className="h-full flex flex-col p-8 space-y-8 overflow-y-auto custom-scrollbar">

            <header className="flex justify-between items-end border-b border-white/5 pb-6">
                <div>
                    <h2 className="text-3xl font-black text-white uppercase tracking-tighter">System Architecture</h2>
                    <p className="text-xs text-neutral-400 font-bold uppercase tracking-widest mt-1">Platform Self-Monitoring & Health</p>
                </div>
                <div className="flex gap-4">
                    <div className={`px-4 py-2 rounded-lg border flex items-center gap-3 ${status.neo4j === 'CONNECTED' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-red-500/10 border-red-500/20 text-red-500'}`}>
                        <span className="material-symbols-outlined text-lg">database</span>
                        <div className="text-left">
                            <p className="text-[10px] font-black uppercase opacity-70">Neo4j Graph DB</p>
                            <p className="text-xs font-bold">{status.neo4j}</p>
                        </div>
                    </div>
                    <div className={`px-4 py-2 rounded-lg border flex items-center gap-3 ${status.collector.status === 'RUNNING' ? 'bg-accent-cyan/10 border-accent-cyan/20 text-accent-cyan' : 'bg-red-500/10 border-red-500/20 text-red-500'}`}>
                        <span className="material-symbols-outlined text-lg">settings_input_antenna</span>
                        <div className="text-left">
                            <p className="text-[10px] font-black uppercase opacity-70">SNMP Collector</p>
                            <p className="text-xs font-bold">{status.collector.status}</p>
                        </div>
                    </div>
                </div>
            </header>

            {/* Resources Grid */}
            <section className="grid grid-cols-1 md:grid-cols-3 gap-6">

                {/* CPU Card */}
                <div className="glass p-8 rounded-3xl relative group">
                    <div className="absolute inset-0 rounded-3xl overflow-hidden pointer-events-none">
                        <div className="absolute top-0 right-0 p-8 opacity-10 group-hover:opacity-20 transition-opacity">
                            <span className="material-symbols-outlined text-9xl">memory</span>
                        </div>
                    </div>
                    <div className="relative z-10">
                        <div className="flex items-center mb-4">
                            <h3 className="text-sm font-black text-neutral-400 uppercase tracking-widest">CPU Utilization</h3>
                            <Tooltip text="Current processor load average of the backend server." />
                        </div>
                        <div className="flex items-end gap-2 mb-2">
                            <span className={`text-6xl font-black tracking-tighter ${getStatusColor(status.cpu)}`}>{status.cpu}%</span>
                            <span className="text-xs font-bold text-neutral-500 mb-2">AVG LOAD</span>
                        </div>
                        <div className="w-full bg-black/40 h-2 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full transition-all duration-1000 ${getBarColor(status.cpu)}`} style={{ width: `${status.cpu}%` }}></div>
                        </div>
                    </div>
                </div>

                {/* RAM Card */}
                <div className="glass p-8 rounded-3xl relative group">
                    <div className="absolute inset-0 rounded-3xl overflow-hidden pointer-events-none">
                        <div className="absolute top-0 right-0 p-8 opacity-10 group-hover:opacity-20 transition-opacity">
                            <span className="material-symbols-outlined text-9xl">memory_alt</span>
                        </div>
                    </div>
                    <div className="relative z-10">
                        <div className="flex items-center mb-4">
                            <h3 className="text-sm font-black text-neutral-400 uppercase tracking-widest">Memory Usage</h3>
                            <Tooltip text="Percentage of physical RAM currently in use by the system." />
                        </div>
                        <div className="flex items-end gap-2 mb-2">
                            <span className={`text-6xl font-black tracking-tighter ${getStatusColor(status.ram)}`}>{status.ram}%</span>
                            <span className="text-xs font-bold text-neutral-500 mb-2">USED</span>
                        </div>
                        <div className="w-full bg-black/40 h-2 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full transition-all duration-1000 ${getBarColor(status.ram)}`} style={{ width: `${status.ram}%` }}></div>
                        </div>
                    </div>
                </div>

                {/* Disk Card */}
                <div className="glass p-8 rounded-3xl relative group">
                    <div className="absolute inset-0 rounded-3xl overflow-hidden pointer-events-none">
                        <div className="absolute top-0 right-0 p-8 opacity-10 group-hover:opacity-20 transition-opacity">
                            <span className="material-symbols-outlined text-9xl">hard_drive</span>
                        </div>
                    </div>
                    <div className="relative z-10">
                        <div className="flex items-center mb-4">
                            <h3 className="text-sm font-black text-neutral-400 uppercase tracking-widest">Storage (Root)</h3>
                            <Tooltip text="Disk space usage on the primary partition." />
                        </div>
                        <div className="flex items-end gap-2 mb-2">
                            <span className={`text-6xl font-black tracking-tighter ${getStatusColor(status.disk)}`}>{status.disk}%</span>
                            <span className="text-xs font-bold text-neutral-500 mb-2">USED</span>
                        </div>
                        <div className="w-full bg-black/40 h-2 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full transition-all duration-1000 ${getBarColor(status.disk)}`} style={{ width: `${status.disk}%` }}></div>
                        </div>
                    </div>
                </div>

            </section>

            {/* Collector Performance Stats */}
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="glass p-6 rounded-2xl flex flex-col justify-between border-l-4 border-l-brand-500">
                    <div className="flex justify-between items-start">
                        <span className="text-[10px] font-black uppercase text-neutral-500 tracking-widest">Active Monitored CIs</span>
                        <Tooltip text="Total number of Configuration Items (CIs) currently being polled." />
                    </div>
                    <span className="text-4xl font-black text-white">{status.collector.stats?.cis_monitored ?? 0}</span>
                </div>
                <div className="glass p-6 rounded-2xl flex flex-col justify-between border-l-4 border-l-brand-400">
                    <div className="flex justify-between items-start">
                        <span className="text-[10px] font-black uppercase text-neutral-500 tracking-widest">Metrics Collected</span>
                        <Tooltip text="Total data points gathered in the last polling cycle." />
                    </div>
                    <span className="text-4xl font-black text-white">{status.collector.stats?.metrics_collected ?? 0}</span>
                </div>
                <div className="glass p-6 rounded-2xl flex flex-col justify-between border-l-4 border-l-accent-cyan">
                    <div className="flex justify-between items-start">
                        <span className="text-[10px] font-black uppercase text-neutral-500 tracking-widest">Throughput (RPM)</span>
                        <Tooltip text="Rate of metrics processed per minute (Requests Per Minute)." />
                    </div>
                    <span className="text-4xl font-black text-accent-cyan">{status.collector.stats?.jobs_per_min ?? 0}</span>
                </div>
                <div className="glass p-6 rounded-2xl flex flex-col justify-between border-l-4 border-l-emerald-400">
                    <div className="flex justify-between items-start">
                        <span className="text-[10px] font-black uppercase text-neutral-500 tracking-widest">Last Cycle Time</span>
                        <Tooltip text="Duration of the most recent polling cycle in seconds." />
                    </div>
                    <span className="text-4xl font-black text-emerald-400">{status.collector.stats?.cycle_duration ?? 0}s</span>
                </div>
            </section>

            {/* System Details / Logs */}
            <section className="flex-1 glass rounded-3xl p-8 border border-white/5 flex flex-col">
                <h3 className="text-sm font-black text-white uppercase tracking-widest mb-6 flex items-center gap-2">
                    <span className="material-symbols-outlined text-lg text-brand-400">terminal</span>
                    System Messages & Logs
                </h3>

                <div className="flex-1 bg-black/40 rounded-xl p-4 font-mono text-xs overflow-y-auto custom-scrollbar border border-white/5">
                    <div className="space-y-2">
                        <div className="flex gap-4 opacity-50">
                            <span className="text-neutral-500">{new Date().toLocaleTimeString()}</span>
                            <span className="text-blue-400">INFO</span>
                            <span>System Dashboard Initialized.</span>
                        </div>
                        {status.collector.last_run && (
                            <div className="flex gap-4">
                                <span className="text-neutral-500">{new Date(status.collector.last_run).toLocaleTimeString()}</span>
                                <span className="text-emerald-400">SUCCESS</span>
                                <span>SNMP Collector Cycle Completed.</span>
                            </div>
                        )}
                        {status.neo4j === 'CONNECTED' ? (
                            <div className="flex gap-4">
                                <span className="text-neutral-500">{new Date().toLocaleTimeString()}</span>
                                <span className="text-emerald-400">SUCCESS</span>
                                <span>Database Connection Verified (Bolt Protocol).</span>
                            </div>
                        ) : (
                            <div className="flex gap-4">
                                <span className="text-neutral-500">{new Date().toLocaleTimeString()}</span>
                                <span className="text-red-500">ERROR</span>
                                <span>Database Connection Failed.</span>
                            </div>
                        )}
                    </div>
                </div>
            </section>
        </div>
    );
};



export default SystemDashboard;
