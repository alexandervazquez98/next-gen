import React, { useEffect, useState, useRef, useCallback } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { api } from '../services/api';

interface MetricHistoryChartProps {
    nodeId: string;
    metricId: string;
    metricName: string;
    unit?: string;
    customRange?: { start: string, end: string } | null;
}

interface DataPoint {
    time: string;
    value: number;
}

const MIN_DURATION = 200; // ms before skeleton shows

const MetricHistoryChart: React.FC<MetricHistoryChartProps> = ({ nodeId, metricId, metricName, unit, customRange }) => {
    const [data, setData] = useState<DataPoint[]>([]);
    const [loading, setLoading] = useState(false);
    const [minDurationActive, setMinDurationActive] = useState(false);
    const [period, setPeriod] = useState(24); // hours

    const abortControllerRef = useRef<AbortController | null>(null);
    const minDurationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const fetchData = useCallback(async (signal: AbortSignal) => {
        if (!nodeId || !metricId) return;

        setLoading(true);

        let endpoint = `/metrics/${nodeId}/${metricId}/history?limit=1000`;
        if (customRange) {
            endpoint += `&start_time=${customRange.start}&end_time=${customRange.end}`;
        } else {
            endpoint += `&hours=${period}`;
        }

        try {
            const jsonData = await api.get<any[]>(endpoint, { signal });

            if (!signal.aborted && Array.isArray(jsonData)) {
                const sorted = [...jsonData].sort((a: any, b: any) => new Date(a.time).getTime() - new Date(b.time).getTime());
                const formatted = sorted.map((d: any) => ({
                    ...d,
                    value: typeof d.value === 'string' ? parseFloat(d.value) : d.value,
                    displayTime: new Date(d.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' })
                }));
                setData(formatted);
            } else if (!signal.aborted) {
                console.warn("[MetricHistoryChart] Received non-array data:", jsonData);
                setData([]);
            }
        } catch (err) {
            if (err instanceof Error && err.name === 'AbortError') {
                return; // silent — no state change
            }
            console.error("Failed to fetch metric history", err);
            setData([]);
        } finally {
            setLoading(false);
            setMinDurationActive(false);
        }
    }, [nodeId, metricId, period, customRange]);

    useEffect(() => {
        // Abort any in-flight request
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        // Clear minDuration timer
        if (minDurationTimerRef.current) {
            clearTimeout(minDurationTimerRef.current);
            setMinDurationActive(false);
        }

        // Start minDuration timer — skeleton armed after 200ms
        minDurationTimerRef.current = setTimeout(() => {
            setMinDurationActive(true);
        }, MIN_DURATION);

        // Create new AbortController for new request
        abortControllerRef.current = new AbortController();

        // Clear data immediately (before timer fires)
        setData([]);
        setLoading(true);

        fetchData(abortControllerRef.current.signal);

        return () => {
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }
            if (minDurationTimerRef.current) {
                clearTimeout(minDurationTimerRef.current);
            }
            setMinDurationActive(false);
        };
    }, [fetchData]);

    const renderSkeleton = () => (
        <div
            className="flex-1 flex flex-col items-center justify-center min-h-[300px] animate-pulse"
            aria-label="Loading chart data"
        >
            <div className="w-full h-48 bg-gradient-to-r from-brand-900/20 via-brand-600/10 to-brand-900/20 rounded-lg mb-4" />
            <span className="text-neutral-500 font-mono text-sm uppercase tracking-widest">
                Loading Metrics...
            </span>
        </div>
    );

    const renderContent = () => {
        if (loading && data.length === 0 && minDurationActive) {
            return renderSkeleton();
        }

        if (!loading && data.length === 0) {
            return (
                <div className="flex-1 flex flex-col items-center justify-center text-neutral-500">
                    <span className="material-symbols-outlined text-4xl mb-2 opacity-50">data_loss_prevention</span>
                    <p className="text-sm font-mono uppercase">No telemetry data found</p>
                    <p className="text-xs opacity-50 mt-1">Try adjusting the time range</p>
                </div>
            );
        }

        return (
            <div className="flex-1 w-full min-h-0 relative chart-fade-in" style={{ minWidth: 0, minHeight: 0 }}>
                <ResponsiveContainer width="99%" height="99%">
                    <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                            <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.3} />
                                <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" vertical={false} />
                        <XAxis
                            dataKey="displayTime"
                            stroke="#525252"
                            tick={{ fill: '#525252', fontSize: 10 }}
                            tickLine={false}
                            axisLine={false}
                            minTickGap={30}
                        />
                        <YAxis
                            stroke="#525252"
                            tick={{ fill: '#525252', fontSize: 10 }}
                            tickLine={false}
                            axisLine={false}
                            width={30}
                        />
                        <Tooltip
                            contentStyle={{ backgroundColor: '#171717', borderColor: '#333', borderRadius: '8px', fontSize: '12px' }}
                            itemStyle={{ color: '#fff' }}
                            labelStyle={{ color: '#a3a3a3', marginBottom: '4px' }}
                        />
                        <Area
                            type="monotone"
                            dataKey="value"
                            stroke="#0ea5e9"
                            strokeWidth={2}
                            fillOpacity={1}
                            fill="url(#colorValue)"
                        />
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        );
    };

    return (
        <div
            key={`chart-${nodeId}-${metricId}`}
            className="bg-surface-800 rounded-xl p-6 border border-white/5 shadow-inner flex flex-col h-full min-h-[300px]"
        >
            <style>{`
                .chart-fade-in {
                    animation: fadeIn 300ms ease-out forwards;
                }
                @keyframes fadeIn {
                    from { opacity: 0; }
                    to { opacity: 1; }
                }
            `}</style>
            <div className="flex justify-between items-center mb-6 flex-shrink-0">
                <div>
                    <h3 className="text-white font-bold uppercase tracking-tight">{metricName} History</h3>
                    <p className="text-xs text-neutral-500">
                        {customRange && !isNaN(new Date(customRange.start).getTime())
                            ? `${new Date(customRange.start).toLocaleDateString()} - ${new Date(customRange.end).toLocaleDateString()}`
                            : customRange
                                ? "Custom Range"
                                : `Past ${period} Hours`
                        }
                    </p>
                </div>
                {!customRange && (
                    <div className="flex bg-black/20 rounded-lg p-1 gap-1">
                        {[1, 6, 24, 32, 72].map(h => (
                            <button
                                key={h}
                                onClick={() => setPeriod(h)}
                                className={`px-3 py-1 rounded-md text-[10px] font-bold transition-all ${period === h ? 'bg-brand-600 text-white shadow' : 'text-neutral-500 hover:text-white hover:bg-white/5'}`}
                            >
                                {h}H
                            </button>
                        ))}
                    </div>
                )}
            </div>

            {renderContent()}
        </div>
    );
};

export default MetricHistoryChart;
