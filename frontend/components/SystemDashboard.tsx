import React from 'react';
import Tooltip from './Tooltip';
import { useSystemStatusQuery } from '../hooks/queries/useSystemStatusQuery';
import { useSystemStatusHistoryQuery } from '../hooks/queries/useSystemStatusHistoryQuery';
import type { DiskIoStatus } from '../services/queryResources';

const formatBytesPerSecond = (value?: number | null) => {
    if (value == null) return '—';
    if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB/s`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KB/s`;
    return `${value.toFixed(0)} B/s`;
};

const formatDiskIoBusy = (diskIo?: DiskIoStatus | null) => {
    if (!diskIo?.supported) return 'N/A';
    return diskIo.busy_percentage == null ? 'Sampling' : `${diskIo.busy_percentage}%`;
};

const formatDiskIoRates = (diskIo?: DiskIoStatus | null) => {
    if (!diskIo?.supported) return 'Disk I/O unsupported on this host';
    if (diskIo.read_bytes_per_sec == null || diskIo.write_bytes_per_sec == null) {
        return 'Collecting baseline sample';
    }
    return `${formatBytesPerSecond(diskIo.read_bytes_per_sec)} read / ${formatBytesPerSecond(diskIo.write_bytes_per_sec)} write`;
};

const formatMetricPercent = (value?: number | null) => value == null ? '—' : `${value.toFixed(1)}%`;

const formatHistoryTimestamp = (value: string) => new Date(value).toLocaleString();

const getServiceBadgeClass = (status?: string | null) => {
    if (status === 'CONNECTED' || status === 'RUNNING') return 'text-emerald-400';
    if (status === 'UNKNOWN') return 'text-amber-400';
    return 'text-red-500';
};

const SystemDashboard: React.FC = () => {
    const { data: status, isLoading: loading } = useSystemStatusQuery();
    const { data: history, isLoading: historyLoading, error: historyError } = useSystemStatusHistoryQuery({ hours: 168, limit: 24 });

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
            <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">

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

                {/* Disk I/O Card */}
                <div className="glass p-8 rounded-3xl relative group">
                    <div className="absolute inset-0 rounded-3xl overflow-hidden pointer-events-none">
                        <div className="absolute top-0 right-0 p-8 opacity-10 group-hover:opacity-20 transition-opacity">
                            <span className="material-symbols-outlined text-9xl">speed</span>
                        </div>
                    </div>
                    <div className="relative z-10">
                        <div className="flex items-center mb-4">
                            <h3 className="text-sm font-black text-neutral-400 uppercase tracking-widest">Disk I/O Throughput</h3>
                            <Tooltip text="Read/write throughput and busy time sampled from the backend host diskstats." />
                        </div>
                        <div className="flex items-end gap-2 mb-2">
                            <span className={`text-4xl font-black tracking-tighter ${status.disk_io?.busy_percentage == null ? 'text-neutral-400' : getStatusColor(status.disk_io.busy_percentage)}`}>{formatDiskIoBusy(status.disk_io)}</span>
                            <span className="text-xs font-bold text-neutral-500 mb-2">BUSY</span>
                        </div>
                        <p className="mb-3 min-h-5 text-xs font-bold uppercase tracking-wide text-neutral-500">{formatDiskIoRates(status.disk_io)}</p>
                        <div className="w-full bg-black/40 h-2 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full transition-all duration-1000 ${getBarColor(status.disk_io?.busy_percentage ?? 0)}`} style={{ width: `${status.disk_io?.busy_percentage ?? 0}%` }}></div>
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

            {/* Operational History */}
            <section className="flex-1 glass rounded-3xl p-8 border border-white/5 flex flex-col">
                <div className="mb-6 flex items-start justify-between gap-4">
                    <div>
                        <h3 className="text-sm font-black text-white uppercase tracking-widest flex items-center gap-2">
                            <span className="material-symbols-outlined text-lg text-brand-400">history</span>
                            7-Day Operational History
                        </h3>
                        <p className="mt-1 text-xs text-neutral-500">Persisted system health snapshots, newest first.</p>
                    </div>
                    <span className="rounded-full border border-white/10 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-neutral-500">
                        {history?.rows.length ?? 0} snapshots
                    </span>
                </div>

                <div className="flex-1 overflow-y-auto rounded-xl border border-white/5 bg-black/40 custom-scrollbar">
                    {historyLoading && !history ? (
                        <div className="p-4 font-mono text-xs text-neutral-500">Loading operational history...</div>
                    ) : historyError ? (
                        <div className="p-4 font-mono text-xs text-red-300">Operational history unavailable.</div>
                    ) : !history?.rows.length ? (
                        <div className="p-4 font-mono text-xs text-neutral-500">No persisted operational snapshots yet. A snapshot is recorded at most every five minutes.</div>
                    ) : (
                        <div className="divide-y divide-white/5 font-mono text-xs">
                            {history.rows.map((row) => (
                                <div key={row.recorded_at} className="grid gap-3 p-4 text-neutral-300 md:grid-cols-[190px_1fr]">
                                    <div>
                                        <p className="font-bold text-neutral-100">{formatHistoryTimestamp(row.recorded_at)}</p>
                                        <p className="mt-1 text-[10px] uppercase tracking-widest text-neutral-600">Snapshot</p>
                                    </div>
                                    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                                        <div>
                                            <p className="text-[10px] uppercase tracking-widest text-neutral-600">Resources</p>
                                            <p>CPU {formatMetricPercent(row.cpu)} / RAM {formatMetricPercent(row.ram)} / Disk {formatMetricPercent(row.disk)}</p>
                                        </div>
                                        <div>
                                            <p className="text-[10px] uppercase tracking-widest text-neutral-600">Disk I/O</p>
                                            <p>{formatDiskIoRates(row.disk_io)}</p>
                                        </div>
                                        <div>
                                            <p className="text-[10px] uppercase tracking-widest text-neutral-600">Services</p>
                                            <p><span className={getServiceBadgeClass(row.neo4j)}>Neo4j {row.neo4j ?? 'UNKNOWN'}</span> / <span className={getServiceBadgeClass(row.postgres)}>PG {row.postgres ?? 'UNKNOWN'}</span></p>
                                        </div>
                                        <div>
                                            <p className="text-[10px] uppercase tracking-widest text-neutral-600">Collector</p>
                                            <p><span className={getServiceBadgeClass(row.collector.status)}>{row.collector.status ?? 'UNKNOWN'}</span> · {row.collector.stats.metrics_collected ?? 0} metrics · {row.collector.stats.metrics_failed ?? 0} failed</p>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </section>
        </div>
    );
};



export default SystemDashboard;
