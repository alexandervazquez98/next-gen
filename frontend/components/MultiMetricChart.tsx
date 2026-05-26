import type React from "react";
import ChartPanel from "./ChartPanel";
import type { NodeMetricData } from "../types";

interface BrushRange {
	startTime?: string;
	endTime?: string;
}

interface MultiMetricChartProps {
	nodeData: NodeMetricData[];
	brushRange: BrushRange | null;
	onBrushChange: (range: BrushRange | null) => void;
	metricName?: string;
	unit?: string;
}

const MultiMetricChart: React.FC<MultiMetricChartProps> = ({
	nodeData,
	brushRange,
	onBrushChange,
	metricName,
	unit,
}) => {
	if (nodeData.length === 0) {
		return (
			<div className="flex min-w-0 flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-white/10 bg-surface-900 text-neutral-600">
				<span className="material-symbols-outlined text-6xl mb-4 opacity-20">
					analytics
				</span>
				<p className="font-bold uppercase tracking-widest">
					Select CIs to Compare
				</p>
			</div>
		);
	}

	return (
		<div className="flex h-full min-w-0 max-w-full flex-col gap-4 overflow-y-auto overflow-x-hidden">
			{nodeData.map((node) => (
				<ChartPanel
					key={node.node_id}
					nodeId={node.node_id}
					label={node.label}
					data={node.data}
					brushRange={brushRange}
					onBrushChange={onBrushChange}
					unit={node.unit ?? unit}
					metricName={node.metricName ?? metricName}
				/>
			))}
		</div>
	);
};

export default MultiMetricChart;
