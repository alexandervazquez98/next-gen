import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GraphNode, MetricValue, NodeMetricData } from "../types";
import MetricHistoryChart from "./MetricHistoryChart";
import MultiSelectCIs from "./MultiSelectCIs";
import MultiMetricChart from "./MultiMetricChart";
import AvailabilityDashboard from "./AvailabilityDashboard";
import DateTimeRangePicker from "./DateTimeRangePicker";
import {
	fetchNodes,
	fetchNodeMetricHistory,
	fetchNodeMetricHistoryDays,
} from "../services/queryResources";
import { formatMetricValue } from "../utils/metricFormatting";

interface BrushRange {
	startTime?: string;
	endTime?: string;
}

type AnalyticsSection = "METRICS" | "AVAILABILITY";
const ANALYTICS_SECTIONS: AnalyticsSection[] = ["METRICS", "AVAILABILITY"];

interface MetricHistoryDayRequest {
	nodeId: string;
	metricId: string;
}

const getMonthRange = (monthKey: string) => {
	const [year, month] = monthKey.split("-").map(Number);
	const start = new Date(Date.UTC(year, month - 1, 1, 0, 0, 0, 0));
	const end = new Date(Date.UTC(year, month, 1, 0, 0, 0, 0));
	return { start: start.toISOString(), end: end.toISOString() };
};

const shiftMonthKey = (monthKey: string, delta: number) => {
	const [year, month] = monthKey.split("-").map(Number);
	const shifted = new Date(Date.UTC(year, month - 1 + delta, 1));
	return `${shifted.getFullYear()}-${String(shifted.getMonth() + 1).padStart(2, "0")}`;
};

const MetricAnalytics: React.FC = () => {
	const [activeSection, setActiveSection] =
		useState<AnalyticsSection>("METRICS");
	const [nodes, setNodes] = useState<GraphNode[]>([]);
	const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
	const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
	const [selectedMetric, setSelectedMetric] = useState<MetricValue | null>(
		null,
	);
	const [, setLoading] = useState(true);
	const [startDate, setStartDate] = useState("");
	const [endDate, setEndDate] = useState("");
	const [metricHistoryDays, setMetricHistoryDays] = useState<Set<string>>(
		() => new Set(),
	);

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

	const hasMultipleSelected = selectedNodeIds.length > 1;
	const selectedNodes = selectedNodeIds
		.map((nodeId) => nodes.find((node) => node.id === nodeId))
		.filter((node): node is GraphNode => Boolean(node));

	const historyDayRequests = useMemo<MetricHistoryDayRequest[]>(() => {
		return hasMultipleSelected
			? selectedNodeIds.flatMap((nodeId) => {
					const primaryMetric = selectedMetricByNodeId[nodeId];
					const secondaryMetric = showSecondary
						? secondaryMetricByNodeId[nodeId]
						: undefined;
					return [primaryMetric, secondaryMetric]
						.filter((metricId): metricId is string => Boolean(metricId))
						.map((metricId) => ({ nodeId, metricId }));
				})
			: selectedNode && selectedMetric
				? [{ nodeId: selectedNode.id, metricId: selectedMetric.name }]
				: [];
	}, [
		hasMultipleSelected,
		selectedNode,
		selectedMetric,
		selectedNodeIds,
		selectedMetricByNodeId,
		showSecondary,
		secondaryMetricByNodeId,
	]);

	const historyDayRequestKey = useMemo(
		() =>
			historyDayRequests
				.map(({ nodeId, metricId }) => `${nodeId}:${metricId}`)
				.sort()
				.join("|"),
		[historyDayRequests],
	);
	const historyDayCacheRef = useRef<Map<string, Set<string>>>(new Map());
	const historyDayInFlightRef = useRef<Set<string>>(new Set());
	const historyDayGenerationRef = useRef(0);
	const historyDayBackgroundTimersRef = useRef<number[]>([]);
	const [loadedHistoryMonths, setLoadedHistoryMonths] = useState<Set<string>>(
		() => new Set(),
	);
	const [loadingHistoryMonths, setLoadingHistoryMonths] = useState<Set<string>>(
		() => new Set(),
	);
	const [visibleHistoryMonth, setVisibleHistoryMonth] = useState<string | null>(
		null,
	);

	const mergeHistoryDayCache = useCallback(() => {
		const merged = new Set<string>();
		historyDayCacheRef.current.forEach((days) => {
			days.forEach((day) => merged.add(day));
		});
		setMetricHistoryDays(merged);
	}, []);

	useEffect(() => {
		historyDayGenerationRef.current += 1;
		historyDayCacheRef.current.clear();
		historyDayInFlightRef.current.clear();
		historyDayBackgroundTimersRef.current.forEach(window.clearTimeout);
		historyDayBackgroundTimersRef.current = [];
		setMetricHistoryDays(new Set());
		setLoadedHistoryMonths(new Set());
		setLoadingHistoryMonths(new Set());
	}, [historyDayRequestKey]);

	const loadHistoryMonth = useCallback(
		(monthKey: string) => {
			if (historyDayRequests.length === 0) return;

			const generation = historyDayGenerationRef.current;
			const { start, end } = getMonthRange(monthKey);
			const missingRequests = historyDayRequests.filter(
				({ nodeId, metricId }) => {
					const cacheKey = `${nodeId}:${metricId}:${monthKey}`;
					return (
						!historyDayCacheRef.current.has(cacheKey) &&
						!historyDayInFlightRef.current.has(cacheKey)
					);
				},
			);

			if (missingRequests.length === 0) {
				const hasInFlightRequests = historyDayRequests.some(
					({ nodeId, metricId }) =>
						historyDayInFlightRef.current.has(
							`${nodeId}:${metricId}:${monthKey}`,
						),
				);
				if (!hasInFlightRequests) {
					setLoadedHistoryMonths((previous) => new Set(previous).add(monthKey));
					mergeHistoryDayCache();
				}
				return;
			}

			setLoadingHistoryMonths((previous) => new Set(previous).add(monthKey));
			missingRequests.forEach(({ nodeId, metricId }) => {
				historyDayInFlightRef.current.add(`${nodeId}:${metricId}:${monthKey}`);
			});

			Promise.all(
				missingRequests.map(({ nodeId, metricId }) =>
					fetchNodeMetricHistoryDays({
						nodeId,
						metricId,
						startTime: start,
						endTime: end,
					}).then((days) => ({ nodeId, metricId, days })),
				),
			)
				.then((results) => {
					if (generation !== historyDayGenerationRef.current) return;
					results.forEach(({ nodeId, metricId, days }) => {
						historyDayCacheRef.current.set(
							`${nodeId}:${metricId}:${monthKey}`,
							new Set(days),
						);
					});
					mergeHistoryDayCache();
					setLoadedHistoryMonths((previous) => new Set(previous).add(monthKey));
				})
				.catch((err) => {
					if (generation !== historyDayGenerationRef.current) return;
					console.error("Failed to fetch metric history days", err);
				})
				.finally(() => {
					if (generation !== historyDayGenerationRef.current) return;
					missingRequests.forEach(({ nodeId, metricId }) => {
						historyDayInFlightRef.current.delete(
							`${nodeId}:${metricId}:${monthKey}`,
						);
					});
					setLoadingHistoryMonths((previous) => {
						const next = new Set(previous);
						next.delete(monthKey);
						return next;
					});
				});
		},
		[historyDayRequests, mergeHistoryDayCache],
	);

	const handleVisibleHistoryMonthChange = useCallback(
		(monthKey: string) => {
			setVisibleHistoryMonth(monthKey);
			historyDayBackgroundTimersRef.current.forEach(window.clearTimeout);
			historyDayBackgroundTimersRef.current = [];
			loadHistoryMonth(monthKey);

			const backgroundMonths = [
				shiftMonthKey(monthKey, -1),
				shiftMonthKey(monthKey, 1),
				...Array.from({ length: 11 }, (_, index) =>
					shiftMonthKey(monthKey, -(index + 2)),
				),
			];

			backgroundMonths.forEach((backgroundMonth, index) => {
				const timer = window.setTimeout(
					() => {
						loadHistoryMonth(backgroundMonth);
					},
					300 * (index + 1),
				);
				historyDayBackgroundTimersRef.current.push(timer);
			});
		},
		[loadHistoryMonth],
	);

	useEffect(() => {
		if (visibleHistoryMonth) {
			handleVisibleHistoryMonthChange(visibleHistoryMonth);
		}
	}, [
		historyDayRequestKey,
		visibleHistoryMonth,
		handleVisibleHistoryMonthChange,
	]);

	useEffect(() => {
		return () => {
			historyDayBackgroundTimersRef.current.forEach(window.clearTimeout);
		};
	}, []);

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

	return (
		<div className="flex h-full min-w-0 max-w-full flex-col overflow-x-hidden overflow-y-auto bg-surface-950 p-4 text-white md:p-8">
			<header className="mb-8 flex min-w-0 flex-col gap-6 md:flex-row md:items-end md:justify-between">
				<div className="min-w-0">
					<h1 className="truncate text-3xl font-black uppercase tracking-tighter">
						Metric Analytics
					</h1>
					<p className="mt-1 truncate font-mono text-sm text-neutral-500">
						Historical Telemetry Visualization
					</p>
				</div>
				<nav
					className="flex gap-3 border-b border-white/5 pb-3 md:border-b-0 md:pb-0"
					aria-label="Analytics sections"
				>
					{ANALYTICS_SECTIONS.map((section) => (
						<button
							key={section}
							type="button"
							onClick={() => setActiveSection(section)}
							className={`rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-widest transition-all ${activeSection === section ? "bg-brand-600 text-white" : "text-neutral-500 hover:bg-white/5 hover:text-white"}`}
						>
							{section}
						</button>
					))}
				</nav>
			</header>

			{activeSection === "AVAILABILITY" ? (
				<AvailabilityDashboard />
			) : (
				<div className="grid min-w-0 max-w-full flex-1 grid-cols-12 gap-4 md:gap-8 lg:min-h-0">
					{/* Controls Sidebar */}
					<div className="col-span-12 flex min-w-0 max-w-full flex-col space-y-6 overflow-x-hidden lg:col-span-3 lg:h-full lg:overflow-y-auto lg:pr-1">
						{/* Multi-CI Selector */}
						<div className="min-w-0 max-w-full rounded-xl border border-white/5 bg-surface-900 p-5">
							<label className="mb-2 block text-xs font-bold uppercase tracking-wider text-neutral-500">
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
						<div className="min-w-0 max-w-full rounded-xl border border-white/5 bg-surface-900 p-5">
							<label className="mb-2 block text-xs font-bold uppercase tracking-wider text-neutral-500">
								Custom Time Range
							</label>
							<DateTimeRangePicker
								startDate={startDate}
								endDate={endDate}
								onStartDateChange={setStartDate}
								onEndDateChange={setEndDate}
								onReset={handleResetDateRange}
								availableDays={metricHistoryDays}
								loadedMonths={loadedHistoryMonths}
								loadingMonths={loadingHistoryMonths}
								onVisibleMonthChange={handleVisibleHistoryMonthChange}
							/>
						</div>

						{/* Metric Selector */}
						<div className="min-w-0 max-w-full flex-1 overflow-y-auto rounded-xl border border-white/5 bg-surface-900 p-5 lg:min-h-0">
							<label className="mb-3 block text-xs font-bold uppercase tracking-wider text-neutral-500">
								{hasMultipleSelected ? "Metric per CI" : "Available Metrics"}
							</label>
							<div className="min-w-0 space-y-3">
								{hasMultipleSelected ? (
									selectedNodes.map((node) => {
										const metrics = node.metrics ?? [];
										return (
											<div
												key={node.id}
												className="min-w-0 max-w-full rounded-lg border border-white/10 bg-white/[0.03] p-3"
											>
												<p className="truncate text-xs font-bold uppercase text-white">
													{node.label}
												</p>
												<p className="mb-2 truncate font-mono text-[10px] text-neutral-500">
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
														className="w-full min-w-0 max-w-full truncate rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white outline-none transition-colors focus:border-brand-500"
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
												className={`flex w-full min-w-0 items-center justify-between rounded-lg border p-3 text-left transition-all ${
													selectedMetric?.name === m.name
														? "bg-brand-500/20 border-brand-500/50 text-white"
														: "bg-white/5 border-transparent text-neutral-400 hover:bg-white/10"
												}`}
											>
												<div className="min-w-0">
													<p className="truncate text-xs font-bold uppercase">
														{m.name}
													</p>
													<p className="mt-0.5 truncate font-mono text-[10px] opacity-60">
														{m.protocol}
													</p>
												</div>
												<span
													className={`h-2 w-2 shrink-0 rounded-full ${m.status === "OK" ? "bg-emerald-500" : "bg-red-500"}`}
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
							<div className="min-w-0 max-w-full rounded-xl border border-white/5 bg-surface-900 p-5">
								<div className="mb-3 flex min-w-0 items-center justify-between gap-3">
									<label className="truncate text-xs font-bold uppercase tracking-wider text-neutral-500">
										Secondary Metric
									</label>
									<button
										aria-label="Toggle secondary metric comparison"
										onClick={() => setShowSecondary(!showSecondary)}
										className={`h-5 w-10 shrink-0 rounded-full transition-colors ${showSecondary ? "bg-brand-500" : "bg-white/20"}`}
									>
										<div
											className={`w-4 h-4 rounded-full bg-white transition-transform ${showSecondary ? "translate-x-5" : "translate-x-0.5"}`}
										></div>
									</button>
								</div>
								{showSecondary && (
									<div className="min-w-0 space-y-3">
										{selectedNodes.map((node) => {
											const metrics = node.metrics ?? [];
											return (
												<div
													key={node.id}
													className="min-w-0 max-w-full rounded-lg border border-white/10 bg-white/[0.03] p-3"
												>
													<p className="truncate text-xs font-bold uppercase text-white">
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
															className="w-full min-w-0 max-w-full truncate rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white outline-none transition-colors focus:border-brand-500"
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
					<div className="col-span-12 flex min-h-[24rem] min-w-0 max-w-full flex-col gap-6 overflow-hidden pb-8 lg:col-span-9 lg:h-full lg:min-h-0">
						{hasMultipleSelected ? (
							<>
								{/* Multi-CI Chart View */}
								<div className="relative flex min-w-0 max-w-full flex-1 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface-900 p-4 md:p-8">
									<div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none">
										<span className="material-symbols-outlined text-9xl">
											monitoring
										</span>
									</div>

									<div className="relative z-10 flex min-h-0 min-w-0 flex-1 flex-col">
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
									<div className="relative flex min-w-0 max-w-full flex-1 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface-900 p-4 md:p-8">
										<div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none">
											<span className="material-symbols-outlined text-9xl">
												analytics
											</span>
										</div>
										<div className="relative z-10 flex min-h-0 min-w-0 flex-1 flex-col">
											<div className="mb-4 min-w-0">
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
							<div className="relative flex min-w-0 max-w-full flex-1 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface-900 p-4 md:p-8">
								{/* Background Pattern */}
								<div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none">
									<span className="material-symbols-outlined text-9xl">
										monitoring
									</span>
								</div>

								<div className="relative z-10 flex min-h-0 min-w-0 flex-1 flex-col">
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

									<div className="mt-8 grid flex-shrink-0 grid-cols-1 gap-4 sm:grid-cols-3 md:gap-6">
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
							<div className="flex min-w-0 flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-white/10 bg-surface-900 text-neutral-600">
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
			)}
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
	let displayValue = formatMetricValue(value, unit);
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
		<div className="min-w-0 rounded-lg border border-white/5 bg-black/20 p-4">
			<p className="mb-1 truncate text-[10px] font-bold uppercase tracking-wider text-neutral-500">
				{label}
			</p>
			<p
				className={`truncate text-2xl font-black tracking-tight ${colorClass}`}
			>
				{displayValue}{" "}
				<span className="text-xs font-normal text-neutral-500">{unit}</span>
			</p>
		</div>
	);
};

export default MetricAnalytics;
