import React, { useEffect, useState, useRef, useCallback } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Brush, ReferenceArea } from 'recharts';

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

const MetricHistoryChart: React.FC<MetricHistoryChartProps> = ({ nodeId, metricId, metricName, unit, customRange }) => {
    const [data, setData] = useState<DataPoint[]>([]);
    const [loading, setLoading] = useState(false);
    const [period, setPeriod] = useState(24); // hours

    // Brush/zoom state
    const [brushRange, setBrushRange] = useState<{ startIndex?: number; endIndex?: number } | null>(null);
    const [isSelecting, setIsSelecting] = useState(false);
    const [selectionStart, setSelectionStart] = useState<number | null>(null);
    const [selectionEnd, setSelectionEnd] = useState<number | null>(null);
    const chartRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        fetchData();
    }, [nodeId, metricId, period, customRange]);

    // Reset brush when period or customRange changes
    useEffect(() => {
        setBrushRange(null);
        setSelectionStart(null);
        setSelectionEnd(null);
    }, [period, customRange]);

    const fetchData = () => {
        setLoading(true);
        const token = localStorage.getItem('token');

        let url = `/api/metrics/${nodeId}/${metricId}/history?limit=1000`;
        if (customRange) {
            url += `&start_time=${customRange.start}&end_time=${customRange.end}`;
        } else {
            url += `&hours=${period}`;
        }

        console.log(`[MetricHistoryChart] Fetching: ${url}`);

        fetch(url, {
            headers: { 'Authorization': `Bearer ${token}` }
        })
            .then(res => {
                if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
                return res.json();
            })
            .then(jsonData => {
                if (!Array.isArray(jsonData)) {
                    console.warn("[MetricHistoryChart] Received non-array data:", jsonData);
                    setLoading(false);
                    return;
                }

                const sorted = jsonData.sort((a: any, b: any) => new Date(a.time).getTime() - new Date(b.time).getTime());
                const formatted = sorted.map((d: any) => ({
                    ...d,
                    value: typeof d.value === 'string' ? parseFloat(d.value) : d.value,
                    displayTime: new Date(d.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' }),
                    rawTime: d.time
                }));

                console.log(`[MetricHistoryChart] Loaded ${formatted.length} points`);
                setData(formatted);
                setLoading(false);
            })
            .catch(err => {
                console.error("Failed to fetch metric history", err);
                setLoading(false);
            });
    };

    const handleResetView = () => {
        setBrushRange(null);
        setSelectionStart(null);
        setSelectionEnd(null);
        setIsSelecting(false);
    };

    // Mouse handlers for drag-to-zoom
    const handleMouseDown = useCallback((e: any) => {
        if (!e || !e.activeLabel) return;
        setIsSelecting(true);
        setSelectionStart(e.activeLabel);
        setSelectionEnd(e.activeLabel);
    }, []);

    const handleMouseMove = useCallback((e: any) => {
        if (!isSelecting || !e || !e.activeLabel) return;
        setSelectionEnd(e.activeLabel);
    }, [isSelecting]);

    const handleMouseUp = useCallback(() => {
        if (!isSelecting || selectionStart === null || selectionEnd === null) {
            setIsSelecting(false);
            return;
        }

        // Find indices in data
        const startIdx = data.findIndex(d => d.displayTime === selectionStart);
        const endIdx = data.findIndex(d => d.displayTime === selectionEnd);

        if (startIdx !== -1 && endIdx !== -1) {
            const [minIdx, maxIdx] = startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
            // Only apply if selection is meaningful (at least 2 points)
            if (maxIdx - minIdx >= 2) {
                setBrushRange({ startIndex: minIdx, endIndex: maxIdx });
            }
        }

        setIsSelecting(false);
        setSelectionStart(null);
        setSelectionEnd(null);
    }, [isSelecting, selectionStart, selectionEnd, data]);

    // Filter data based on brush selection
    const displayData = brushRange && brushRange.startIndex !== undefined && brushRange.endIndex !== undefined
        ? data.slice(brushRange.startIndex, brushRange.endIndex + 1)
        : data;

    const hasBrushApplied = brushRange !== null;

    const renderContent = () => {
        if (loading && data.length === 0) {
            return (
                <div className="flex-1 flex items-center justify-center text-neutral-500 animate-pulse font-mono text-sm">
                    LOADING METRICS...
                </div>
            );
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
            <div className="flex-1 w-full min-h-0 relative" style={{ minWidth: 0, minHeight: 0 }}>
                <ResponsiveContainer width="99%" height="99%">
                    <AreaChart
                        data={displayData}
                        margin={{ top: 10, right: 10, left: -20, bottom: hasBrushApplied ? 50 : 0 }}
                        onMouseDown={handleMouseDown}
                        onMouseMove={handleMouseMove}
                        onMouseUp={handleMouseUp}
                        onMouseLeave={() => setIsSelecting(false)}
                    >
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
                        {/* Selection rectangle overlay */}
                        {isSelecting && selectionStart && selectionEnd && (
                            <ReferenceArea
                                x1={selectionStart}
                                x2={selectionEnd}
                                strokeOpacity={0.3}
                                fill="#0ea5e9"
                                fillOpacity={0.2}
                            />
                        )}
                        {/* Brush component at bottom for direct range selection */}
                        {data.length > 0 && (
                            <Brush
                                dataKey="displayTime"
                                height={30}
                                stroke="#525252"
                                fill="#171717"
                                tickFormatter={() => ''}
                                startIndex={brushRange?.startIndex}
                                endIndex={brushRange?.endIndex}
                                onChange={(range: any) => {
                                    if (range.startIndex !== undefined && range.endIndex !== undefined) {
                                        setBrushRange({ startIndex: range.startIndex, endIndex: range.endIndex });
                                    }
                                }}
                            />
                        )}
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        );
    };

    return (
        <div className="bg-surface-800 rounded-xl p-6 border border-white/5 shadow-inner flex flex-col h-full min-h-[300px]">
            <div className="flex justify-between items-center mb-6 flex-shrink-0">
                <div>
                    <h3 className="text-white font-bold uppercase tracking-tight">{metricName} History</h3>
                    <p className="text-xs text-neutral-500">
                        {hasBrushApplied
                            ? `Zoomed: ${displayData.length} points selected`
                            : customRange
                                ? `${new Date(customRange.start).toLocaleDateString()} - ${new Date(customRange.end).toLocaleDateString()}`
                                : `Past ${period} Hours`
                        }
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {hasBrushApplied && (
                        <button
                            onClick={handleResetView}
                            className="flex items-center gap-1 px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-bold transition-all text-neutral-300"
                            title="Reset zoom (drag to select range, or use slider)"
                        >
                            <span className="material-symbols-outlined text-sm">restart_alt</span>
                            Reset View
                        </button>
                    )}
                    {!customRange && (
                        <div className="flex bg-black/20 rounded-lg p-1 gap-1">
                            {[1, 6, 24, 32, 72].map(h => (
                                <button
                                    key={h}
                                    onClick={() => setPeriod(h)}
                                    className={`px-3 py-1 rounded-md text-[10px] font-bold transition-all ${period === h && !hasBrushApplied ? 'bg-brand-600 text-white shadow' : 'text-neutral-500 hover:text-white hover:bg-white/5'}`}
                                >
                                    {h}H
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {renderContent()}

            {/* Instructions hint */}
            {hasBrushApplied && (
                <p className="text-[10px] text-neutral-600 text-center mt-2">
                    Drag on chart or use slider below to zoom • Click "Reset View" to restore
                </p>
            )}
        </div>
    );
};

export default MetricHistoryChart;