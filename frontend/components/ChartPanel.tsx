import React, { useMemo } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Brush, ReferenceArea } from 'recharts';

interface BrushRange {
  startIndex?: number;
  endIndex?: number;
}

interface DataPoint {
  time: string;
  value: number;
}

interface ChartPanelProps {
  nodeId: string;
  label: string;
  data: DataPoint[];
  brushRange: BrushRange | null;
  onBrushChange: (range: BrushRange | null) => void;
  unit?: string;
  metricName?: string;
}

const ChartPanel: React.FC<ChartPanelProps> = ({
  nodeId,
  label,
  data,
  brushRange,
  onBrushChange,
  unit,
  metricName,
}) => {
  const formattedData = useMemo(() => {
    return data
      .sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())
      .map(d => ({
        ...d,
        displayTime: new Date(d.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' }),
        rawTime: d.time,
        value: typeof d.value === 'string' ? parseFloat(d.value) : d.value,
      }));
  }, [data]);

  const displayData = brushRange && brushRange.startIndex !== undefined && brushRange.endIndex !== undefined
    ? formattedData.slice(brushRange.startIndex, brushRange.endIndex + 1)
    : formattedData;

  const hasBrushApplied = brushRange !== null;

  const handleResetView = () => {
    onBrushChange(null);
  };

  const hasData = data.length > 0;

  return (
    <div className="bg-surface-800 rounded-xl p-6 border border-white/5 shadow-inner flex flex-col h-full min-h-[250px]">
      <div className="flex justify-between items-center mb-4 flex-shrink-0">
        <div>
          <h4 className="text-white font-bold uppercase tracking-tight">{label}</h4>
          <p className="text-xs text-neutral-500">
            {hasBrushApplied
              ? `${displayData.length} points selected`
              : `${data.length} data points`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {hasBrushApplied && (
            <button
              onClick={handleResetView}
              className="flex items-center gap-1 px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-bold transition-all text-neutral-300"
            >
              <span className="material-symbols-outlined text-sm">restart_alt</span>
              Reset
            </button>
          )}
        </div>
      </div>

      {!hasData ? (
        <div className="flex-1 flex flex-col items-center justify-center text-neutral-500">
          <span className="material-symbols-outlined text-4xl mb-2 opacity-50">data_loss_prevention</span>
          <p className="text-sm font-mono uppercase">No telemetry data</p>
        </div>
      ) : (
        <div className="flex-1 w-full min-h-0 relative" style={{ minWidth: 0, minHeight: 0 }}>
          <ResponsiveContainer width="99%" height="99%">
            <AreaChart
              data={displayData}
              margin={{ top: 10, right: 10, left: -20, bottom: hasBrushApplied ? 50 : 0 }}
            >
              <defs>
                <linearGradient id={`colorValue-${nodeId}`} x1="0" y1="0" x2="0" y2="1">
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
                fill={`url(#colorValue-${nodeId})`}
              />
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
                    onBrushChange({ startIndex: range.startIndex, endIndex: range.endIndex });
                  } else {
                    onBrushChange(null);
                  }
                }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
};

export default ChartPanel;