import React, { useState, useEffect } from "react";
import { GraphNode, MetricValue, NodeMetricData } from "../types";
import MetricHistoryChart from "./MetricHistoryChart";
import MultiSelectCIs from "./MultiSelectCIs";
import MultiMetricChart from "./MultiMetricChart";
import { fetchNodes, fetchNodeMetricHistory } from "../services/queryResources";

interface BrushRange {
	startTime?: string;
	endTime?: string;
}

const MetricAnalytics: React.FC = () => {
	const [nodes, setNodes] = useState<GraphNode[]>([]);
	const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
	const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
	const [selectedMetric, setSelectedMetric] = useState<MetricValue | null>(
		null,
	);
	const [, setLoading] = useState(true);
	const [startDate, setStartDate] = useState("");
	const [endDate, setEndDate] = useState("");

	// Multi-CI state
	const [brushRange, setBrushRange] = useState<BrushRange | null>(null);
	const [multiCiData, setMultiCiData] = useState<NodeMetricData[]>([]);
	const [multiCiLoading, setMultiCiLoading] = useState(false);
	const [showSecondary, setShowSecondary] = useState(false);
	const [selectedMetricByNodeId, setSelectedMetricByNodeId] = useState<
		Record<string, string>
	>({});
	const [secondaryMetricByNodeId, setSecondaryMetricByNodeId] = useState<
		Record<string, string>
	>({});
	const [secondaryMultiCiData, setSecondaryMultiCiData] = useState<
		NodeMetricData[]
	>([]);
	const [secondaryMultiCiLoading, setSecondaryMultiCiLoading] = useState(false);

	// Reset brush when node selection, date range, or metric changes
	// (indices are specific to each dataset)
	useEffect(() => {
		setBrushRange(null);
	}, [
		selectedNodeIds,
		startDate,
		endDate,
		selectedMetric,
		selectedMetricByNodeId,
		secondaryMetricByNodeId,
	]);

	// Derive selectedNode from selectedNodeIds[0]
	useEffect(() => {
		setSelectedNode(nodes.find((n) => n.id === selectedNodeIds[0]) || null);
	}, [selectedNodeIds, nodes]);

	// Fetch Nodes on Mount (original behavior)
	useEffect(() => {
		fetchNodes()
			.then((data) => {
				if (Array.isArray(data)) {
					setNodes(data);
				}
				setLoading(false);
			})
			.catch((err) => {
				console.error(err);
				setLoading(false);
				// On fetch failure, ensure consistent state by not setting any defaults
				// User can still manually select from the dropdown if nodes were previously loaded
			});
	}, []);

	// Update available metrics when node changes
	useEffect(() => {
		if (
			selectedNode &&
			selectedNode.metrics &&
			selectedNode.metrics.length > 0
		) {
			setSelectedMetric(selectedNode.metrics[0]);
		} else {
			setSelectedMetric(null);
		}
	}, [selectedNode]);

	// Each selected CI can use its own metrics for heterogeneous models/brands.
	useEffect(() => {
		setSelectedMetricByNodeId((previous) => {
			const next: Record<string, string> = {};
			selectedNodeIds.forEach((nodeId) => {
				const node = nodes.find((n) => n.id === nodeId);
				const metrics = node?.metrics ?? [];
				const previousMetric = previous[nodeId];
				const hasPreviousMetric = metrics.some(
					(metric) => metric.name === previousMetric,
				);
				next[nodeId] = hasPreviousMetric
					? previousMetric
					: (metrics[0]?.name ?? "");
			});
			return next;
		});

		setSecondaryMetricByNodeId((previous) => {
			const next: Record<string, string> = {};
			selectedNodeIds.forEach((nodeId) => {
				const node = nodes.find((n) => n.id === nodeId);
				const metrics = node?.metrics ?? [];
				const previousMetric = previous[nodeId];
				const hasPreviousMetric = metrics.some(
					(metric) => metric.name === previousMetric,
				);
				next[nodeId] = hasPreviousMetric
					? previousMetric
					: (metrics[1]?.name ?? metrics[0]?.name ?? "");
			});
			return next;
		});
	}, [selectedNodeIds, nodes]);

	// Fetch multi-CI data. Each CI can use a different metric.
	useEffect(() => {
		const hasMultipleSelected = selectedNodeIds.length > 1;

		if (!hasMultipleSelected) {
			setMultiCiData([]);
			setMultiCiLoading(false);
			return;
		}

		setMultiCiLoading(true);
		const controller = new AbortController();

		const customRange =
			startDate && endDate
				? {
						start: new Date(startDate).toISOString(),
						end: new Date(endDate).toISOString(),
					}
				: null;

		Promise.all(
			selectedNodeIds.map(async (nodeId) => {
				const node = nodes.find((n) => n.id === nodeId);
				const metricId = selectedMetricByNodeId[nodeId];
				const metric = node?.metrics?.find(
					(candidate) => candidate.name === metricId,
				);

				if (!node || !metricId) {
					return {
						node_id: nodeId,
						label: node?.label ?? nodeId,
						metricName: undefined,
						unit: undefined,
						data: [],
					};
				}

				const data = await fetchNodeMetricHistory({
					nodeId,
					metricId,
					hours: customRange ? undefined : 24,
					startTime: customRange?.start,
					endTime: customRange?.end,
					signal: controller.signal,
				});

				return {
					node_id: nodeId,
					label: node.label,
					metricName: metricId,
					unit: metric?.unit,
					data: data.map((point) => ({
						time: point.time,
						value:
							typeof point.value === "string"
								? parseFloat(point.value)
								: point.value,
					})),
				};
			}),
		)
			.then((nodeData) => {
				setMultiCiData(nodeData);
				setMultiCiLoading(false);
			})
			.catch((err) => {
				if (err.name !== "AbortError") {
					console.error("Failed to fetch multi-CI metric history", err);
				}
				setMultiCiLoading(false);
			});

		return () => controller.abort();
	}, [selectedNodeIds, selectedMetricByNodeId, nodes, startDate, endDate]);

	// Fetch secondary metric data. Each CI can use a different secondary metric.
	useEffect(() => {
		if (!showSecondary || selectedNodeIds.length <= 1) {
			setSecondaryMultiCiData([]);
			setSecondaryMultiCiLoading(false);
			return;
		}

		setSecondaryMultiCiLoading(true);
		setSecondaryMultiCiData([]);
		const controller = new AbortController();
		const customRange =
			startDate && endDate
				? {
						start: new Date(startDate).toISOString(),
						end: new Date(endDate).toISOString(),
					}
				: null;

		Promise.all(
			selectedNodeIds.map(async (nodeId) => {
				const node = nodes.find((n) => n.id === nodeId);
				const metricId = secondaryMetricByNodeId[nodeId];
				const metric = node?.metrics?.find(
					(candidate) => candidate.name === metricId,
				);

				if (!node || !metricId) {
					return {
						node_id: nodeId,
						label: node?.label ?? nodeId,
						metricName: undefined,
						unit: undefined,
						data: [],
					};
				}

				const data = await fetchNodeMetricHistory({
					nodeId,
					metricId,
					hours: customRange ? undefined : 24,
					startTime: customRange?.start,
					endTime: customRange?.end,
					signal: controller.signal,
				});

				return {
					node_id: nodeId,
					label: node.label,
					metricName: metricId,
					unit: metric?.unit,
					data: data.map((point) => ({
						time: point.time,
						value:
							typeof point.value === "string"
								? parseFloat(point.value)
								: point.value,
					})),
				};
			}),
		)
			.then((nodeData) => {
				setSecondaryMultiCiData(nodeData);
				setSecondaryMultiCiLoading(false);
			})
			.catch((err) => {
				if (err.name !== "AbortError") {
					console.error("Failed to fetch secondary metric history", err);
				}
				setSecondaryMultiCiLoading(false);
			});

		return () => controller.abort();
	}, [
		showSecondary,
		selectedNodeIds,
		secondaryMetricByNodeId,
		nodes,
		startDate,
		endDate,
	]);

	const handleResetDateRange = () => {
		setStartDate("");
		setEndDate("");
	};

	const handleMultiCiChange = (ids: string[]) => {
		setSelectedNodeIds(ids);
		setBrushRange(null);
	};

	const handleBrushChange = (range: BrushRange | null) => {
		setBrushRange(range);
	};

	const hasMultipleSelected = selectedNodeIds.length > 1;
	const selectedNodes = selectedNodeIds
		.map((nodeId) => nodes.find((node) => node.id === nodeId))
		.filter((node): node is GraphNode => Boolean(node));

	return (
		<div className="flex flex-col h-full bg-surface-950 text-white p-8 overflow-hidden">
			<header className="mb-8 flex justify-between items-end">
				<div>
					<h1 className="text-3xl font-black uppercase tracking-tighter">
						Metric Analytics
					</h1>
					<p className="text-neutral-500 font-mono text-sm mt-1">
						Historical Telemetry Visualization
					</p>
				</div>
			</header>

			<div className="grid grid-cols-12 gap-8 h-full">
				{/* Controls Sidebar */}
				<div className="col-span-12 lg:col-span-3 space-y-6 flex flex-col h-full overflow-hidden min-w-0">
					{/* Multi-CI Selector */}
					<div className="bg-surface-900 border border-white/5 rounded-xl p-5">
						<label className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2 block">
							Compare Multiple CIs
						</label>
						<MultiSelectCIs
							selectedIds={selectedNodeIds}
							onChange={handleMultiCiChange}
							availableNodes={nodes}
							maxCIs={10}
						/>
					</div>

					{/* Date Range Selector */}
					<div className="bg-surface-900 border border-white/5 rounded-xl p-5">
						<label className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2 block">
							Custom Time Range
						</label>
						<div className="space-y-3">
							<div>
								<label className="text-[10px] text-neutral-400 block mb-1">
									Start Date
								</label>
								<input
									type="datetime-local"
									className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-xs text-white outline-none focus:border-brand-500"
									value={startDate}
									onChange={(e) => setStartDate(e.target.value)}
								/>
							</div>
							<div>
								<label className="text-[10px] text-neutral-400 block mb-1">
									End Date
								</label>
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
						<label className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3 block">
							{hasMultipleSelected ? "Metric per CI" : "Available Metrics"}
						</label>
						<div className="space-y-3">
							{hasMultipleSelected ? (
								selectedNodes.map((node) => {
									const metrics = node.metrics ?? [];
									return (
										<div
											key={node.id}
											className="rounded-lg border border-white/10 bg-white/[0.03] p-3"
										>
											<p className="text-xs font-bold uppercase text-white truncate">
												{node.label}
											</p>
											<p className="text-[10px] text-neutral-500 font-mono mb-2 truncate">
												{node.brand || "Unknown brand"} {node.model || ""}
											</p>
											{metrics.length > 0 ? (
												<select
													value={
														selectedMetricByNodeId[node.id] ?? metrics[0].name
													}
													onChange={(event) => {
														setSelectedMetricByNodeId((previous) => ({
															...previous,
															[node.id]: event.target.value,
														}));
														setMultiCiData([]);
														setBrushRange(null);
													}}
													className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-xs text-white focus:border-brand-500 outline-none transition-colors"
												>
													{metrics.map((metric) => (
														<option key={metric.name} value={metric.name}>
															{metric.name}
														</option>
													))}
												</select>
											) : (
												<p className="text-xs text-neutral-600 py-2">
													No metrics available for this CI.
												</p>
											)}
										</div>
									);
								})
							) : (
								<>
									{selectedNode?.metrics?.map((m, idx) => (
										<button
											key={idx}
											onClick={() => {
												setSelectedMetric(m);
												setMultiCiData([]);
												setBrushRange(null);
											}}
											className={`w-full text-left p-3 rounded-lg border transition-all flex items-center justify-between ${
												selectedMetric?.name === m.name
													? "bg-brand-500/20 border-brand-500/50 text-white"
													: "bg-white/5 border-transparent text-neutral-400 hover:bg-white/10"
											}`}
										>
											<div>
												<p className="text-xs font-bold uppercase">{m.name}</p>
												<p className="text-[10px] opacity-60 font-mono mt-0.5">
													{m.protocol}
												</p>
											</div>
											<span
												className={`w-2 h-2 rounded-full ${m.status === "OK" ? "bg-emerald-500" : "bg-red-500"}`}
											></span>
										</button>
									))}
									{(!selectedNode?.metrics ||
										selectedNode.metrics.length === 0) && (
										<p className="text-xs text-neutral-600 text-center py-4">
											No metrics available for this CI.
										</p>
									)}
								</>
							)}
						</div>
					</div>

					{/* Secondary Metric Toggle */}
					{hasMultipleSelected && (
						<div className="bg-surface-900 border border-white/5 rounded-xl p-5">
							<div className="flex items-center justify-between mb-3">
								<label className="text-xs font-bold text-neutral-500 uppercase tracking-wider">
									Secondary Metric
								</label>
								<button
									onClick={() => setShowSecondary(!showSecondary)}
									className={`w-10 h-5 rounded-full transition-colors ${showSecondary ? "bg-brand-500" : "bg-white/20"}`}
								>
									<div
										className={`w-4 h-4 rounded-full bg-white transition-transform ${showSecondary ? "translate-x-5" : "translate-x-0.5"}`}
									></div>
								</button>
							</div>
							{showSecondary && (
								<div className="space-y-3">
									{selectedNodes.map((node) => {
										const metrics = node.metrics ?? [];
										return (
											<div
												key={node.id}
												className="rounded-lg border border-white/10 bg-white/[0.03] p-3"
											>
												<p className="text-xs font-bold uppercase text-white truncate">
													{node.label}
												</p>
												{metrics.length > 0 ? (
													<select
														value={
															secondaryMetricByNodeId[node.id] ??
															metrics[1]?.name ??
															metrics[0].name
														}
														onChange={(event) => {
															setSecondaryMetricByNodeId((previous) => ({
																...previous,
																[node.id]: event.target.value,
															}));
															setSecondaryMultiCiData([]);
															setBrushRange(null);
														}}
														className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-xs text-white focus:border-brand-500 outline-none transition-colors"
													>
														{metrics.map((metric) => (
															<option key={metric.name} value={metric.name}>
																{metric.name}
															</option>
														))}
													</select>
												) : (
													<p className="text-xs text-neutral-600 py-2">
														No metrics available for this CI.
													</p>
												)}
											</div>
										);
									})}
								</div>
							)}
						</div>
					)}
				</div>

				{/* Main Chart Area */}
				<div className="col-span-12 lg:col-span-9 flex flex-col gap-6 h-full overflow-hidden pb-8 min-w-0">
					{hasMultipleSelected ? (
						<>
							{/* Multi-CI Chart View */}
							<div className="flex-1 bg-surface-900 border border-white/5 rounded-xl p-8 relative overflow-hidden flex flex-col">
								<div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none">
									<span className="material-symbols-outlined text-9xl">
										monitoring
									</span>
								</div>

								<div className="relative z-10 flex-1 flex flex-col min-h-0">
									{multiCiLoading ? (
										<div className="flex-1 flex items-center justify-center text-neutral-500 animate-pulse font-mono text-sm">
											LOADING METRICS...
										</div>
									) : (
										<MultiMetricChart
											nodeData={multiCiData}
											brushRange={brushRange}
											onBrushChange={handleBrushChange}
											metricName="Selected metrics"
										/>
									)}
								</div>
							</div>

							{/* Secondary Metric Section */}
							{showSecondary && (
								<div className="flex-1 bg-surface-900 border border-white/5 rounded-xl p-8 relative overflow-hidden flex flex-col">
									<div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none">
										<span className="material-symbols-outlined text-9xl">
											analytics
										</span>
									</div>
									<div className="relative z-10 flex-1 flex flex-col min-h-0">
										<div className="mb-4">
											<h3 className="text-white font-bold uppercase tracking-tight">
												Secondary Metrics Comparison
											</h3>
											<p className="text-xs text-neutral-500">
												Secondary metric per selected CI
											</p>
										</div>
										{secondaryMultiCiLoading ? (
											<div className="flex-1 flex items-center justify-center text-neutral-500 animate-pulse font-mono text-sm">
												LOADING SECONDARY METRIC...
											</div>
										) : (
											<MultiMetricChart
												nodeData={secondaryMultiCiData}
												brushRange={brushRange}
												onBrushChange={handleBrushChange}
												metricName="Secondary metrics"
											/>
										)}
									</div>
								</div>
							)}
						</>
					) : selectedNode && selectedMetric ? (
						<div className="flex-1 bg-surface-900 border border-white/5 rounded-xl p-8 relative overflow-hidden flex flex-col">
							{/* Background Pattern */}
							<div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none">
								<span className="material-symbols-outlined text-9xl">
									monitoring
								</span>
							</div>

							<div className="relative z-10 flex-1 flex flex-col min-h-0">
								<MetricHistoryChart
									nodeId={selectedNode.id}
									metricId={selectedMetric.name}
									metricName={selectedMetric.name}
									unit={selectedMetric.unit}
									customRange={
										startDate && endDate
											? {
													start: new Date(startDate).toISOString(),
													end: new Date(endDate).toISOString(),
												}
											: null
									}
								/>

								<div className="mt-8 grid grid-cols-3 gap-6 flex-shrink-0">
									<StatCard
										label="Current Value"
										value={selectedMetric.value}
										unit={selectedMetric.unit}
									/>
									<StatCard
										label="Status"
										value={selectedMetric.status}
										isStatus
									/>
									<StatCard
										label="Last Updated"
										value={selectedMetric.last_updated}
										isDate
									/>
								</div>
							</div>
						</div>
					) : (
						<div className="flex-1 bg-surface-900 border border-dashed border-white/10 rounded-xl flex items-center justify-center flex-col text-neutral-600">
							<span className="material-symbols-outlined text-6xl mb-4 opacity-20">
								analytics
							</span>
							<p className="font-bold uppercase tracking-widest">
								Select a CI and Metric
							</p>
						</div>
					)}
				</div>
			</div>
		</div>
	);
};

const StatCard: React.FC<{
	label: string;
	value: string | number | null | undefined;
	unit?: string;
	isStatus?: boolean;
	isDate?: boolean;
}> = ({ label, value, unit, isStatus, isDate }) => {
	let displayValue = value ?? "--";
	let colorClass = "text-white";

	if (isStatus) {
		if (value === "OK") colorClass = "text-emerald-500";
		else if (value === "CRITICAL") colorClass = "text-red-500";
		else if (value === "WARNING") colorClass = "text-orange-500";
	} else if (isDate && value) {
		displayValue = new Date(value).toLocaleString();
		colorClass = "text-neutral-300 text-sm";
	}

	return (
		<div className="bg-black/20 rounded-lg p-4 border border-white/5">
			<p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-1">
				{label}
			</p>
			<p className={`text-2xl font-black tracking-tight ${colorClass}`}>
				{displayValue}{" "}
				<span className="text-xs text-neutral-500 font-normal">{unit}</span>
			</p>
		</div>
	);
};

export default MetricAnalytics;
