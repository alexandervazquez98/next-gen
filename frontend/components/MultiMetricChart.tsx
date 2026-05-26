import React from "react";
import ChartPanel from "./ChartPanel";
import { NodeMetricData } from "../types";

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
			<div className="flex-1 bg-surface-900 border border-dashed border-white/10 rounded-xl flex items-center justify-center flex-col text-neutral-600">
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
		<div className="flex flex-col gap-4 h-full overflow-y-auto">
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
