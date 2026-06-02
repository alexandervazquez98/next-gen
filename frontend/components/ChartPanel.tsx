import type React from "react";
import { useCallback, useMemo, useState } from "react";
import {
	AreaChart,
	Area,
	XAxis,
	YAxis,
	CartesianGrid,
	Tooltip,
	ResponsiveContainer,
	Brush,
	ReferenceArea,
} from "recharts";
import { formatMetricValue } from "../utils/metricFormatting";

interface BrushRange {
	startTime?: string;
	endTime?: string;
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

const MIN_DRAG_POINTS = 2;
const MIN_DRAG_RANGE_MS = 5 * 60 * 1000;

const getActiveRawTime = (event: any): string | null => {
	return (
		event?.activePayload?.[0]?.payload?.rawTime ?? event?.activeLabel ?? null
	);
};

const getRangeLabel = (startTime: string, endTime: string) => {
	const durationMs = Math.abs(
		new Date(endTime).getTime() - new Date(startTime).getTime(),
	);
	if (durationMs <= 6 * 60 * 60 * 1000) {
		return { hour: "2-digit", minute: "2-digit" } as const;
	}
	if (durationMs <= 48 * 60 * 60 * 1000) {
		return {
			day: "numeric",
			month: "short",
			hour: "2-digit",
			minute: "2-digit",
		} as const;
	}
	return { day: "numeric", month: "short" } as const;
};

const ChartPanel: React.FC<ChartPanelProps> = ({
	nodeId,
	label,
	data,
	brushRange,
	onBrushChange,
	unit,
	metricName,
}) => {
	const [isSelecting, setIsSelecting] = useState(false);
	const [selectionStart, setSelectionStart] = useState<string | null>(null);
	const [selectionEnd, setSelectionEnd] = useState<string | null>(null);

	const formattedData = useMemo(() => {
		return data
			.sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())
			.map((d) => ({
				...d,
				displayTime: new Date(d.time).toLocaleTimeString([], {
					hour: "2-digit",
					minute: "2-digit",
					day: "numeric",
					month: "short",
				}),
				rawTime: d.time,
				value: typeof d.value === "string" ? parseFloat(d.value) : d.value,
			}));
	}, [data]);

	const displayData =
		brushRange?.startTime && brushRange?.endTime
			? formattedData.filter(
					(d) =>
						d.rawTime >= brushRange.startTime! &&
						d.rawTime <= brushRange.endTime!,
				)
			: formattedData;

	const hasBrushApplied = brushRange !== null;
	const xTickFormatter = useCallback(
		(value: string) => {
			const rangeStart = displayData[0]?.rawTime;
			const rangeEnd = displayData[displayData.length - 1]?.rawTime;
			if (!rangeStart || !rangeEnd) return value;
			return new Date(value).toLocaleString(
				[],
				getRangeLabel(rangeStart, rangeEnd),
			);
		},
		[displayData],
	);

	const handleResetView = () => {
		onBrushChange(null);
		setIsSelecting(false);
		setSelectionStart(null);
		setSelectionEnd(null);
	};

	const handleMouseDown = useCallback((event: any) => {
		const rawTime = getActiveRawTime(event);
		if (!rawTime) return;
		setIsSelecting(true);
		setSelectionStart(rawTime);
		setSelectionEnd(rawTime);
	}, []);

	const handleMouseMove = useCallback(
		(event: any) => {
			const rawTime = getActiveRawTime(event);
			if (!isSelecting || !rawTime) return;
			setSelectionEnd(rawTime);
		},
		[isSelecting],
	);

	const handleMouseUp = useCallback(() => {
		if (!isSelecting || !selectionStart || !selectionEnd) {
			setIsSelecting(false);
			return;
		}

		const startIdx = displayData.findIndex(
			(point) => point.rawTime === selectionStart,
		);
		const endIdx = displayData.findIndex(
			(point) => point.rawTime === selectionEnd,
		);
		if (startIdx !== -1 && endIdx !== -1) {
			let [minIdx, maxIdx] =
				startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
			const durationMs = Math.abs(
				new Date(displayData[maxIdx].rawTime).getTime() -
					new Date(displayData[minIdx].rawTime).getTime(),
			);
			if (
				maxIdx - minIdx + 1 < MIN_DRAG_POINTS ||
				durationMs < MIN_DRAG_RANGE_MS
			) {
				const centerIdx = Math.round((minIdx + maxIdx) / 2);
				minIdx = Math.max(0, centerIdx - 1);
				maxIdx = Math.min(displayData.length - 1, centerIdx + 1);
			}
			const start = displayData[minIdx]?.rawTime;
			const end = displayData[maxIdx]?.rawTime;
			onBrushChange(
				start && end && end !== start
					? { startTime: start, endTime: end }
					: null,
			);
		}

		setIsSelecting(false);
		setSelectionStart(null);
		setSelectionEnd(null);
	}, [isSelecting, selectionStart, selectionEnd, displayData, onBrushChange]);

	const hasData = data.length > 0;

	return (
		<div className="flex h-full min-h-[300px] min-w-0 max-w-full flex-col rounded-xl border border-white/5 bg-surface-800 p-4 shadow-inner md:p-6">
			<div className="mb-4 flex min-w-0 flex-shrink-0 items-center justify-between gap-3">
				<div className="min-w-0">
					<h4 className="truncate font-bold uppercase tracking-tight text-white">
						{label}
					</h4>
					{metricName && (
						<p className="mt-0.5 truncate font-mono text-[10px] uppercase text-brand-300">
							{metricName}
						</p>
					)}
					<p className="truncate text-xs text-neutral-500">
						{hasBrushApplied
							? `${displayData.length} points selected`
							: `${data.length} data points`}
					</p>
				</div>
				<div className="flex shrink-0 items-center gap-2">
					{hasBrushApplied && (
						<button
							onClick={handleResetView}
							className="flex items-center gap-1 px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-bold transition-all text-neutral-300"
						>
							<span className="material-symbols-outlined text-sm">
								restart_alt
							</span>
							Reset
						</button>
					)}
				</div>
			</div>

			{!hasData ? (
				<div className="flex-1 flex flex-col items-center justify-center text-neutral-500">
					<span className="material-symbols-outlined text-4xl mb-2 opacity-50">
						data_loss_prevention
					</span>
					<p className="text-sm font-mono uppercase">No telemetry data</p>
				</div>
			) : (
				<div
					className="relative min-h-0 w-full min-w-0 flex-1 select-none cursor-crosshair"
					style={{ minWidth: 0, minHeight: 0, userSelect: "none" }}
					onMouseDown={(event) => event.preventDefault()}
				>
					<style>{`.recharts-cartesian-axis-tick-value{user-select:none;pointer-events:none;}`}</style>
					<ResponsiveContainer width="100%" height="100%">
						<AreaChart
							data={displayData}
							margin={{
								top: 10,
								right: 16,
								left: 0,
								bottom: 54,
							}}
							onMouseDown={handleMouseDown}
							onMouseMove={handleMouseMove}
							onMouseUp={handleMouseUp}
							onMouseLeave={() => setIsSelecting(false)}
						>
							<defs>
								<linearGradient
									id={`colorValue-${nodeId}`}
									x1="0"
									y1="0"
									x2="0"
									y2="1"
								>
									<stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.3} />
									<stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
								</linearGradient>
							</defs>
							<CartesianGrid
								strokeDasharray="3 3"
								stroke="#ffffff10"
								vertical={false}
							/>
							<XAxis
								dataKey="rawTime"
								stroke="#525252"
								tick={{ fill: "#525252", fontSize: 10 }}
								tickLine={false}
								axisLine={false}
								minTickGap={30}
								tickFormatter={xTickFormatter}
							/>
							<YAxis
								stroke="#525252"
								tick={{ fill: "#525252", fontSize: 10 }}
								tickLine={false}
								axisLine={false}
								width={30}
							/>
							<Tooltip
								contentStyle={{
									backgroundColor: "#171717",
									borderColor: "#333",
									borderRadius: "8px",
									fontSize: "12px",
								}}
								itemStyle={{ color: "#fff" }}
								labelStyle={{ color: "#a3a3a3", marginBottom: "4px" }}
								formatter={(value: string | number) => [
									`${formatMetricValue(value, unit)}${unit ? ` ${unit}` : ""}`,
									metricName ?? "value",
								]}
							/>
							<Area
								type="monotone"
								dataKey="value"
								stroke="#0ea5e9"
								strokeWidth={2}
								fillOpacity={1}
								fill={`url(#colorValue-${nodeId})`}
							/>
							{isSelecting && selectionStart && selectionEnd && (
								<ReferenceArea
									x1={selectionStart}
									x2={selectionEnd}
									strokeOpacity={0.3}
									fill="#0ea5e9"
									fillOpacity={0.2}
								/>
							)}
							<Brush
								dataKey="rawTime"
								height={30}
								stroke="#525252"
								fill="#171717"
								tickFormatter={() => ""}
								onChange={(range: any) => {
									if (
										range.startIndex !== undefined &&
										range.endIndex !== undefined
									) {
										const start = displayData[range.startIndex]?.rawTime;
										const end = displayData[range.endIndex]?.rawTime;
										onBrushChange(
											start && end ? { startTime: start, endTime: end } : null,
										);
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
