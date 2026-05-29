import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import type { GraphNode } from "../types";
import { api } from "../services/api";
import type { LinkData } from "./RelationshipManager";
import {
	canDeleteRelationship,
	isReadOnlyRelationship,
} from "./relationshipCapabilities";
import { getStatusColorHex } from "../utils/status";
import {
	buildAnchoredVisualLayout,
	type PositionedVisualNode,
	VISUAL_EDITOR_VIEWBOX_HEIGHT,
	VISUAL_EDITOR_VIEWBOX_WIDTH,
} from "./visualRelationshipLayout";

const SUPPORTED_RELATIONSHIP_TYPES = [
	"CONNECTS_TO",
	"DEPENDS_ON",
	"HOSTED_ON",
	"MANAGES",
	"USES",
	"PROVIDES",
] as const;

const CI_TYPES: GraphNode["type"][] = [
	"SERVICE",
	"INFRASTRUCTURE",
	"APPLICATION",
	"USER",
	"CLOUD_RESOURCE",
];

const CI_STATUSES: GraphNode["status"][] = [
	"OK",
	"ACTIVE",
	"EXCEPTION",
	"MAINTENANCE",
];

type CiFormState = {
	id: string;
	label: string;
	type: GraphNode["type"] | "";
	status: GraphNode["status"];
	ip: string;
	owner: string;
	location_name: string;
};

const EMPTY_CI_FORM: CiFormState = {
	id: "",
	label: "",
	type: "",
	status: "OK",
	ip: "",
	owner: "",
	location_name: "",
};

interface VisualRelationshipEditorProps {
	nodes: GraphNode[];
	links: LinkData[];
	onClose: () => void;
	onMutated: () => void | Promise<void>;
	mode?: "modal" | "page";
}

const nodeLabel = (node?: GraphNode) => node?.label || node?.id || "Unknown CI";
const nodeLayer = (node: GraphNode) => node.category ?? node.type;
const sameLayers = (a: string[], b: string[]) =>
	a.length === b.length && a.every((layer, index) => layer === b[index]);

const toCiForm = (node: GraphNode): CiFormState => ({
	id: node.id,
	label: node.label,
	type: node.type,
	status: node.status || "OK",
	ip: node.ip || "",
	owner: node.owner || "",
	location_name: node.location_name || "",
});

const VisualRelationshipEditor: React.FC<VisualRelationshipEditorProps> = ({
	nodes,
	links,
	onClose,
	onMutated,
	mode = "modal",
}) => {
	const [sourceId, setSourceId] = useState("");
	const [targetId, setTargetId] = useState("");
	const [relationship, setRelationship] =
		useState<(typeof SUPPORTED_RELATIONSHIP_TYPES)[number]>("CONNECTS_TO");
	const [error, setError] = useState("");
	const [saving, setSaving] = useState(false);
	const [selectedCiId, setSelectedCiId] = useState("");
	const [ciForm, setCiForm] = useState<CiFormState>(EMPTY_CI_FORM);
	const [ciError, setCiError] = useState("");
	const [ciSaving, setCiSaving] = useState(false);
	const [selectedLayers, setSelectedLayers] = useState<string[]>([]);
	const knownLayerLabelsRef = useRef<string[]>([]);
	const graphSvgRef = useRef<SVGSVGElement>(null);
	const zoomTransformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);

	const ciLinks = useMemo(
		() => links.filter((link) => link.relationship !== "HAS_METRIC"),
		[links],
	);
	const layerOptions = useMemo(() => {
		const counts = new Map<string, number>();
		for (const node of nodes) {
			const layer = nodeLayer(node);
			counts.set(layer, (counts.get(layer) ?? 0) + 1);
		}
		return Array.from(counts.entries())
			.map(([label, count]) => ({ label, count }))
			.sort((a, b) => a.label.localeCompare(b.label));
	}, [nodes]);

	useEffect(() => {
		const available = layerOptions.map((option) => option.label);
		const previousAvailable = knownLayerLabelsRef.current;
		knownLayerLabelsRef.current = available;

		setSelectedLayers((current) => {
			const availableSet = new Set(available);
			const previousAvailableSet = new Set(previousAvailable);
			const preserved = current.filter((layer) => availableSet.has(layer));
			const newlyDiscovered = available.filter(
				(layer) => !previousAvailableSet.has(layer),
			);
			const next = [...preserved, ...newlyDiscovered];
			return sameLayers(current, next) ? current : next;
		});
	}, [layerOptions]);

	const visibleNodes = useMemo(
		() => nodes.filter((node) => selectedLayers.includes(nodeLayer(node))),
		[nodes, selectedLayers],
	);
	const visibleNodeIds = useMemo(
		() => new Set(visibleNodes.map((node) => node.id)),
		[visibleNodes],
	);
	const visibleCiLinks = useMemo(
		() =>
			ciLinks.filter(
				(link) =>
					visibleNodeIds.has(link.source) && visibleNodeIds.has(link.target),
			),
		[ciLinks, visibleNodeIds],
	);
	const nodeMap = useMemo(
		() => new Map(nodes.map((node) => [node.id, node])),
		[nodes],
	);
	const positionedNodes = useMemo(
		() => buildAnchoredVisualLayout(visibleNodes, visibleCiLinks),
		[visibleNodes, visibleCiLinks],
	);
	const positionMap = useMemo(
		() => new Map(positionedNodes.map((item) => [item.id, item])),
		[positionedNodes],
	);

	const selectedCi = selectedCiId ? nodeMap.get(selectedCiId) : undefined;
	const isEditingCi = Boolean(selectedCi);

	useEffect(() => {
		setSourceId((current) =>
			current && !visibleNodeIds.has(current) ? "" : current,
		);
		setTargetId((current) =>
			current && !visibleNodeIds.has(current) ? "" : current,
		);
	}, [visibleNodeIds]);

	const toggleLayer = (layer: string) => {
		setSelectedLayers((current) =>
			current.includes(layer)
				? current.filter((item) => item !== layer)
				: [...current, layer],
		);
	};
	const selectAllLayers = () => {
		setSelectedLayers(layerOptions.map((option) => option.label));
	};
	const clearAllLayers = () => {
		setSelectedLayers([]);
	};

	const updateCiForm = (field: keyof CiFormState, value: string) => {
		setCiForm((current) => ({ ...current, [field]: value }));
	};

	const startNewCi = () => {
		setSelectedCiId("");
		setCiForm(EMPTY_CI_FORM);
		setCiError("");
	};

	const validateCiForm = () => {
		if (!ciForm.id.trim()) return "CI ID is required.";
		if (!ciForm.label.trim()) return "Label is required.";
		if (!ciForm.type) return "Type is required.";
		return "";
	};

	const buildCiPayload = (): GraphNode => ({
		...(selectedCi ?? {}),
		id: ciForm.id.trim(),
		label: ciForm.label.trim(),
		type: ciForm.type as GraphNode["type"],
		status: ciForm.status || "OK",
		metadata: selectedCi?.metadata ?? {},
		ip: ciForm.ip.trim() || undefined,
		owner: ciForm.owner.trim() || undefined,
		location_name: ciForm.location_name.trim() || undefined,
	});

	const handleSaveCi = async () => {
		const validationError = validateCiForm();
		if (validationError) {
			setCiError(validationError);
			return;
		}
		setCiSaving(true);
		setCiError("");
		try {
			await api.post("/nodes", buildCiPayload());
			await onMutated();
		} catch (err) {
			console.error(err);
			setCiError("Could not save CI.");
		} finally {
			setCiSaving(false);
		}
	};

	const handleDeleteCi = async () => {
		if (!selectedCi) return;
		if (!confirm(`Delete CI ${selectedCi.id}?`)) return;
		setCiSaving(true);
		setCiError("");
		try {
			await api.delete(`/nodes/${encodeURIComponent(selectedCi.id)}`);
			setSelectedCiId("");
			setCiForm(EMPTY_CI_FORM);
			await onMutated();
		} catch (err) {
			console.error(err);
			setCiError("Could not delete CI.");
		} finally {
			setCiSaving(false);
		}
	};

	const selectNode = useCallback(
		(id: string) => {
			if (!visibleNodeIds.has(id)) return;
			setError("");
			setCiError("");
			const node = nodeMap.get(id);
			if (node) {
				setSelectedCiId(id);
				setCiForm(toCiForm(node));
			}
			if (!sourceId || (sourceId && targetId)) {
				setSourceId(id);
				setTargetId("");
				return;
			}
			if (id === sourceId) {
				setError("Source and target must be different CIs.");
				return;
			}
			setTargetId(id);
		},
		[nodeMap, sourceId, targetId, visibleNodeIds],
	);

	useEffect(() => {
		const svgElement = graphSvgRef.current;
		if (!svgElement) return;

		const svg = d3.select(svgElement);
		svg.selectAll("*").remove();

		const container = svg.append("g").attr("class", "visual-editor-zoom-root");
		const zoom = d3.zoom<SVGSVGElement, unknown>()
			.scaleExtent([0.35, 3])
			.on("zoom", (event) => {
				zoomTransformRef.current = event.transform;
				container.attr("transform", event.transform);
			});
		svg.call(zoom);
		container.attr("transform", zoomTransformRef.current);
		container
			.append("g")
			.attr("class", "relationship-links")
			.selectAll("g")
			.data(visibleCiLinks)
			.join("g")
			.each(function (link) {
				const source = positionMap.get(link.source);
				const target = positionMap.get(link.target);
				if (!source || !target) return;

				const linkGroup = d3.select(this);
				linkGroup
					.append("line")
					.attr("x1", source.mapX)
					.attr("y1", source.mapY)
					.attr("x2", target.mapX)
					.attr("y2", target.mapY)
					.attr("stroke", getStatusColorHex(target.status))
					.attr("stroke-opacity", 0.45)
					.attr("stroke-width", 2)
					.attr(
						"stroke-dasharray",
						link.relationship === "DEPENDS_ON"
							? "5, 8"
							: link.relationship === "HOSTED_ON"
								? "2, 2"
								: "none",
					);

				if (visibleCiLinks.length <= 24) {
					linkGroup
						.append("text")
						.attr("x", (source.mapX + target.mapX) / 2)
						.attr("y", (source.mapY + target.mapY) / 2)
						.attr("fill", "#d4d4d4")
						.attr("font-size", 10)
						.attr("font-weight", 700)
						.text(link.relationship);
				}
			});

		const nodeSelection = container
			.append("g")
			.attr("class", "relationship-nodes")
			.selectAll<SVGGElement, PositionedVisualNode>("g")
			.data(positionedNodes, (node) => node.id)
			.join("g")
			.attr("role", "button")
			.attr("tabindex", 0)
			.attr("aria-label", (node) => `CI node ${nodeLabel(node)}`)
			.attr("title", (node) => `${nodeLabel(node)} · ${node.layer}`)
			.attr("transform", (node) => `translate(${node.mapX},${node.mapY})`)
			.attr("class", "cursor-pointer")
			.on("click", (_event, node) => selectNode(node.id))
			.on("keydown", (event, node) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					selectNode(node.id);
				}
			});

		nodeSelection
			.append("circle")
			.attr("r", (node) =>
				node.status === "EXCEPTION"
					? 32
					: node.status === "MAINTENANCE"
						? 28
						: 24,
			)
			.attr("fill", (node) =>
				node.id === sourceId
					? "#345bf2"
					: node.id === targetId
						? "#06b6d4"
						: "#1a1a1a",
			)
			.attr("stroke", (node) => getStatusColorHex(node.status))
			.attr("stroke-width", (node) =>
				node.id === sourceId || node.id === targetId ? 5 : 2,
			)
			.attr("class", "node-circle transition-all duration-300");

		nodeSelection
			.append("text")
			.attr("dy", "0.35em")
			.attr("text-anchor", "middle")
			.attr("fill", "#f5f5f5")
			.attr("font-size", 11)
			.attr("font-weight", 900)
			.attr("pointer-events", "none")
			.text((node) => nodeLabel(node).slice(0, 2).toUpperCase());

		nodeSelection
			.append("text")
			.attr("dy", "3.5em")
			.attr("text-anchor", "middle")
			.attr("fill", "#a3a3a3")
			.attr("font-size", 10)
			.attr("class", "node-label pointer-events-none")
			.text((node) =>
				nodeLabel(node).length > 15
					? `${nodeLabel(node).substring(0, 12)}...`
					: nodeLabel(node),
			);

		nodeSelection
			.on("mouseover", function (_event, node) {
				d3.select(this)
					.select("circle")
					.attr("stroke-width", 6)
					.attr("filter", "drop-shadow(0 0 8px currentColor)");
				d3.select(this)
					.select(".node-label")
					.attr("fill", "white")
					.attr("font-weight", "bold")
					.text(nodeLabel(node));
				nodeSelection
					.filter((item) => item.id !== node.id)
					.attr("opacity", 0.3);
			})
			.on("mouseout", function () {
				const node = d3.select(this).datum() as PositionedVisualNode;
				d3.select(this)
					.select("circle")
					.attr(
						"stroke-width",
						node.id === sourceId || node.id === targetId ? 5 : 2,
					)
					.attr("filter", null);
				d3.select(this)
					.select(".node-label")
					.attr("fill", "#a3a3a3")
					.attr("font-weight", "normal")
					.text(
						nodeLabel(node).length > 15
							? `${nodeLabel(node).substring(0, 12)}...`
							: nodeLabel(node),
					);
				nodeSelection.attr("opacity", 1);
			});
	}, [
		positionMap,
		positionedNodes,
		selectNode,
		sourceId,
		targetId,
		visibleCiLinks,
	]);

	const handleCreate = async () => {
		if (!sourceId || !targetId) {
			setError("Select a source CI and a target CI.");
			return;
		}
		if (sourceId === targetId) {
			setError("Source and target must be different CIs.");
			return;
		}
		if (!visibleNodeIds.has(sourceId) || !visibleNodeIds.has(targetId)) {
			setError("Selected CIs must be visible.");
			return;
		}
		setSaving(true);
		setError("");
		try {
			await api.post("/links", {
				source: sourceId,
				target: targetId,
				relationship,
			});
			setTargetId("");
			await onMutated();
		} catch (err) {
			console.error(err);
			setError("Could not create relationship.");
		} finally {
			setSaving(false);
		}
	};

	const handleDelete = async (link: LinkData) => {
		if (!canDeleteRelationship(link.relationship)) return;

		setSaving(true);
		setError("");
		try {
			await api.delete("/links", link);
			await onMutated();
		} catch (err) {
			console.error(err);
			setError("Could not delete relationship.");
		} finally {
			setSaving(false);
		}
	};

	const isPageMode = mode === "page";

	const editorContent = (
		<div className={`${isPageMode ? "flex h-full w-full flex-col bg-neutral-950" : "flex h-full w-full max-w-7xl flex-col rounded-2xl border border-white/10 bg-neutral-950 shadow-2xl"}`}>
				<div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
					<div>
						<h2 className="text-xl font-black uppercase text-white">
							Visual Relationship Editor
						</h2>
						<p className="text-xs font-bold uppercase tracking-widest text-neutral-500">
							Click source CI, click target CI, choose type, then create link
						</p>
					</div>
					<button
						onClick={onClose}
						className="text-neutral-400 hover:text-white"
						aria-label="Close visual relationship editor"
					>
						<span className="material-symbols-outlined text-3xl">close</span>
					</button>
				</div>

				<div className="grid flex-1 min-h-0 grid-cols-[1fr_360px] gap-4 p-4">
					<div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[radial-gradient(circle_at_center,rgba(59,130,246,0.12),rgba(0,0,0,0.18)_42%,rgba(0,0,0,0.62))]">
						<div className="pointer-events-none absolute inset-0 opacity-35 [background-image:linear-gradient(rgba(255,255,255,0.06)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.06)_1px,transparent_1px)] [background-size:48px_48px]" />
						<div className="absolute left-4 top-4 z-10 w-56 rounded-xl border border-white/10 bg-neutral-950/85 p-3 shadow-xl backdrop-blur">
							<div className="flex items-center justify-between gap-2">
								<div>
									<p className="text-[10px] font-black uppercase tracking-widest text-neutral-400">
										Layers
									</p>
									<p className="text-[10px] text-neutral-500">
										{visibleNodes.length}/{nodes.length} CIs
									</p>
								</div>
								<div className="flex gap-2 text-[10px] font-black uppercase">
									<button
										type="button"
										onClick={selectAllLayers}
										className="text-brand-300 hover:text-brand-200"
									>
										All
									</button>
									<button
										type="button"
										onClick={clearAllLayers}
										className="text-neutral-400 hover:text-white"
									>
										None
									</button>
								</div>
							</div>
							<div className="mt-3 space-y-2">
								{layerOptions.map((option) => (
									<label
										key={option.label}
										className="flex items-center justify-between gap-2 text-xs text-neutral-300"
									>
										<span className="flex items-center gap-2 truncate">
											<input
												type="checkbox"
												checked={selectedLayers.includes(option.label)}
												onChange={() => toggleLayer(option.label)}
												aria-label={`${option.label} layer (${option.count} CIs)`}
											/>
											<span className="truncate">{option.label}</span>
										</span>
										<span className="rounded bg-white/10 px-2 py-0.5 font-mono text-[10px] text-neutral-400">
											{option.count}
										</span>
									</label>
								))}
							</div>
						</div>
						<svg
							ref={graphSvgRef}
							className="absolute inset-0 h-full w-full"
							viewBox={`0 0 ${VISUAL_EDITOR_VIEWBOX_WIDTH} ${VISUAL_EDITOR_VIEWBOX_HEIGHT}`}
							aria-label="Visual CI relationship map"
						/>
						{visibleNodes.length === 0 && (
							<div className="absolute inset-0 flex items-center justify-center text-xs font-bold uppercase tracking-widest text-neutral-500">
								No CIs match selected layers
							</div>
						)}
					</div>

					<aside className="flex min-h-0 flex-col gap-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
						<div className="rounded-xl border border-white/10 bg-black/20 p-3">
							<div className="flex items-center justify-between gap-2">
								<p className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
									CI details — {isEditingCi ? "editing" : "new"}
								</p>
								<button
									type="button"
									onClick={startNewCi}
									className="text-[10px] font-black uppercase text-brand-300 hover:text-brand-200"
								>
									New CI
								</button>
							</div>
							<div className="mt-3 grid grid-cols-2 gap-2 text-xs text-neutral-300">
								<label className="col-span-2 space-y-1">
									<span className="text-neutral-500">CI ID</span>
									<input
										aria-label="CI ID"
										value={ciForm.id}
										disabled={isEditingCi || ciSaving}
										onChange={(event) => updateCiForm("id", event.target.value)}
										className="w-full rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-white disabled:opacity-60"
									/>
								</label>
								<label className="col-span-2 space-y-1">
									<span className="text-neutral-500">Label</span>
									<input
										aria-label="CI label"
										value={ciForm.label}
										disabled={ciSaving}
										onChange={(event) =>
											updateCiForm("label", event.target.value)
										}
										className="w-full rounded-lg border border-white/10 bg-black/30 p-2 text-white"
									/>
								</label>
								<label className="space-y-1">
									<span className="text-neutral-500">Type</span>
									<select
										aria-label="CI type"
										value={ciForm.type}
										disabled={ciSaving}
										onChange={(event) =>
											updateCiForm("type", event.target.value)
										}
										className="w-full rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-white"
									>
										<option value="">Select type</option>
										{CI_TYPES.map((type) => (
											<option key={type} value={type}>
												{type}
											</option>
										))}
									</select>
								</label>
								<label className="space-y-1">
									<span className="text-neutral-500">Status</span>
									<select
										aria-label="CI status"
										value={ciForm.status}
										disabled={ciSaving}
										onChange={(event) =>
											updateCiForm("status", event.target.value)
										}
										className="w-full rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-white"
									>
										{CI_STATUSES.map((status) => (
											<option key={status} value={status}>
												{status}
											</option>
										))}
									</select>
								</label>
								{ciError && (
									<div className="col-span-2 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-red-300">
										{ciError}
									</div>
								)}
								<button
									type="button"
									onClick={handleSaveCi}
									disabled={ciSaving}
									className="col-span-2 rounded-xl bg-cyan-600 py-2 text-xs font-black uppercase text-white disabled:cursor-not-allowed disabled:opacity-40"
								>
									{ciSaving
										? "Saving CI..."
										: isEditingCi
											? "Save CI"
											: "Create CI"}
								</button>
								<button
									type="button"
									onClick={handleDeleteCi}
									disabled={!isEditingCi || ciSaving}
									className="col-span-2 rounded-xl border border-red-500/30 py-2 text-xs font-black uppercase text-red-300 disabled:cursor-not-allowed disabled:opacity-40"
								>
									Delete CI
								</button>
							</div>
						</div>

						<div className="rounded-xl border border-white/10 bg-black/20 p-3">
							<p className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
								New relationship
							</p>
							<div className="mt-3 space-y-2 text-xs text-neutral-300">
								<div>
									<span className="text-neutral-500">Source:</span>{" "}
									{nodeLabel(nodeMap.get(sourceId))}
								</div>
								<div>
									<span className="text-neutral-500">Target:</span>{" "}
									{targetId
										? nodeLabel(nodeMap.get(targetId))
										: "Select target"}
								</div>
								<select
									value={relationship}
									onChange={(event) =>
										setRelationship(event.target.value as typeof relationship)
									}
									className="mt-2 w-full rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-white"
									aria-label="Relationship type"
								>
									{SUPPORTED_RELATIONSHIP_TYPES.map((type) => (
										<option key={type} value={type}>
											{type}
										</option>
									))}
								</select>
								{error && (
									<div className="rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-red-300">
										{error}
									</div>
								)}
								<button
									onClick={handleCreate}
									disabled={
										saving || !sourceId || !targetId || sourceId === targetId
									}
									className="w-full rounded-xl bg-brand-600 py-2 text-xs font-black uppercase text-white disabled:cursor-not-allowed disabled:opacity-40"
								>
									{saving ? "Saving..." : "Create relationship"}
								</button>
							</div>
						</div>

						<div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-white/10 bg-black/20">
							<div className="sticky top-0 bg-neutral-950/90 p-3 text-[10px] font-black uppercase tracking-widest text-neutral-500">
								Existing links
							</div>
							{visibleCiLinks.map((link) => {
								const readOnly = isReadOnlyRelationship(link.relationship);

								return (
									<div
										key={`${link.source}-${link.target}-${link.relationship}`}
										className="border-t border-white/5 p-3 text-xs text-neutral-300"
									>
										<div className="font-bold text-white">
											{link.source_label || link.source} →{" "}
											{link.target_label || link.target}
										</div>
										<div className="mt-1 flex items-center justify-between gap-2">
											<span className="flex items-center gap-2">
												<span className="rounded bg-white/10 px-2 py-1 font-mono text-[10px]">
													{link.relationship}
												</span>
												{readOnly && (
													<span className="rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-[10px] font-black uppercase text-amber-200">
														Read-only
													</span>
												)}
											</span>
											{canDeleteRelationship(link.relationship) && (
												<button
													onClick={() => handleDelete(link)}
													className="text-red-300 hover:text-red-200"
													disabled={saving}
												>
													Delete
												</button>
											)}
										</div>
									</div>
								);
							})}
							{visibleCiLinks.length === 0 && (
								<div className="p-6 text-center text-xs text-neutral-500">
									{ciLinks.length === 0
										? "No CI links yet."
										: "No visible CI links for selected layers."}
								</div>
							)}
						</div>
					</aside>
				</div>
			</div>
	);

	if (isPageMode) return editorContent;

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-6 backdrop-blur-xl">
			{editorContent}
		</div>
	);
};

export default VisualRelationshipEditor;
