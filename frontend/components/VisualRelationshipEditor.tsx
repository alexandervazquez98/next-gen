import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as d3 from "d3";
import type { GraphNode } from "../types";
import { api } from "../services/api";
import CategoryIcon from "./CategoryIcon";
import type { LinkData } from "./RelationshipManager";
import {
	canDeleteRelationship,
	isReadOnlyRelationship,
} from "./relationshipCapabilities";
import {
	buildEditorForceGraphLayout,
	editorClusterName,
	getEditorStatusVisual,
	truncateGraphLabel,
	type EditorClusterPlacementMode,
	type EditorGraphNodeDatum,
	type EditorNodePosition,
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
	const [selectedLocations, setSelectedLocations] = useState<string[]>([]);
	const [locationSearch, setLocationSearch] = useState("");
	const [graphSearch, setGraphSearch] = useState("");
	const [clusterPlacementMode, setClusterPlacementMode] =
		useState<EditorClusterPlacementMode>("relationshipAware");
	const [viewResetNonce, setViewResetNonce] = useState(0);
	const knownLayerLabelsRef = useRef<string[]>([]);
	const knownLocationLabelsRef = useRef<string[]>([]);
	const graphSvgRef = useRef<SVGSVGElement>(null);
	const zoomTransformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
	const nodePositionCacheRef = useRef<Map<string, EditorNodePosition>>(
		new Map(),
	);
	const graphLayoutKeyRef = useRef("");

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
	const locationOptions = useMemo(() => {
		const counts = new Map<string, number>();
		for (const node of nodes) {
			const location = node.location_name || "Unassigned";
			counts.set(location, (counts.get(location) ?? 0) + 1);
		}
		return Array.from(counts.entries())
			.map(([label, count]) => ({ label, count }))
			.sort((a, b) => a.label.localeCompare(b.label));
	}, [nodes]);
	const filteredLocationOptions = useMemo(() => {
		const query = locationSearch.trim().toLowerCase();
		if (!query) return locationOptions;
		return locationOptions.filter((option) =>
			option.label.toLowerCase().includes(query),
		);
	}, [locationOptions, locationSearch]);

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

	useEffect(() => {
		const available = locationOptions.map((option) => option.label);
		const previousAvailable = knownLocationLabelsRef.current;
		knownLocationLabelsRef.current = available;

		setSelectedLocations((current) => {
			const availableSet = new Set(available);
			const previousAvailableSet = new Set(previousAvailable);
			const preserved = current.filter((location) =>
				availableSet.has(location),
			);
			const newlyDiscovered = available.filter(
				(location) => !previousAvailableSet.has(location),
			);
			const next = [...preserved, ...newlyDiscovered];
			return sameLayers(current, next) ? current : next;
		});
	}, [locationOptions]);

	const searchableText = (value: unknown): string => {
		if (value === null || value === undefined) return "";
		if (
			typeof value === "string" ||
			typeof value === "number" ||
			typeof value === "boolean"
		) {
			return String(value);
		}
		if (Array.isArray(value)) return value.map(searchableText).join(" ");
		if (typeof value === "object") {
			return Object.entries(value as Record<string, unknown>)
				.map(([key, entryValue]) => `${key} ${searchableText(entryValue)}`)
				.join(" ");
		}
		return "";
	};
	const normalizedGraphSearch = graphSearch.trim().toLowerCase();
	const nodeMatchesGraphSearch = useCallback(
		(node: GraphNode) => {
			if (!normalizedGraphSearch) return true;
			return searchableText({
				...node,
				metadata: node.metadata,
				clusterName: editorClusterName(node),
			})
				.toLowerCase()
				.includes(normalizedGraphSearch);
		},
		[normalizedGraphSearch],
	);
	const matchingNodeIds = useMemo(() => {
		if (!normalizedGraphSearch) return new Set<string>();
		return new Set(nodes.filter(nodeMatchesGraphSearch).map((node) => node.id));
	}, [nodes, nodeMatchesGraphSearch, normalizedGraphSearch]);
	const visibleNodes = useMemo(
		() =>
			nodes.filter(
				(node) =>
					selectedLayers.includes(nodeLayer(node)) &&
					selectedLocations.includes(node.location_name || "Unassigned") &&
					nodeMatchesGraphSearch(node),
			),
		[nodes, selectedLayers, selectedLocations, nodeMatchesGraphSearch],
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
	const compactLocationClusters =
		selectedLocations.length > 0 &&
		selectedLocations.length < locationOptions.length;
	const nodeMap = useMemo(
		() => new Map(nodes.map((node) => [node.id, node])),
		[nodes],
	);

	useEffect(() => {
		const currentNodeIds = new Set(nodes.map((node) => node.id));
		for (const cachedNodeId of nodePositionCacheRef.current.keys()) {
			if (!currentNodeIds.has(cachedNodeId)) {
				nodePositionCacheRef.current.delete(cachedNodeId);
			}
		}
	}, [nodes]);

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
	const toggleLocation = (location: string) => {
		setSelectedLocations((current) =>
			current.includes(location)
				? current.filter((item) => item !== location)
				: [...current, location],
		);
	};
	const selectAllLocations = () => {
		setSelectedLocations(locationOptions.map((option) => option.label));
	};
	const clearAllLocations = () => {
		setSelectedLocations([]);
	};
	const resetGraphView = () => {
		setSelectedLayers(layerOptions.map((option) => option.label));
		setSelectedLocations(locationOptions.map((option) => option.label));
		setLocationSearch("");
		setGraphSearch("");
		nodePositionCacheRef.current.clear();
		graphLayoutKeyRef.current = "";
		zoomTransformRef.current = d3.zoomIdentity;
		setViewResetNonce((current) => current + 1);
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

		const viewportRect = svgElement.getBoundingClientRect();
		const viewportWidth = viewportRect.width || svgElement.clientWidth || 1200;
		const viewportHeight =
			viewportRect.height || svgElement.clientHeight || 800;
		const graphWidth = VISUAL_EDITOR_VIEWBOX_WIDTH;
		const graphHeight = VISUAL_EDITOR_VIEWBOX_HEIGHT;
		const graphLayoutKey = JSON.stringify({
			version: "clustered-scaled-v3",
			width: graphWidth,
			height: graphHeight,
			compactLocationClusters,
			clusterPlacementMode,
			viewResetNonce,
			nodes: visibleNodes
				.map((node) => {
					const clusterName =
						(node as typeof node & { cluster_name?: string }).cluster_name ??
						"";
					return `${node.id}:${clusterName}:${node.location_name ?? ""}:${node.owner ?? ""}:${node.location?.lat ?? ""}:${node.location?.long ?? ""}`;
				})
				.sort(),
			links: visibleCiLinks
				.map((link) => `${link.source}->${link.target}:${link.relationship}`)
				.sort(),
		});
		const reuseCachedLayout = graphLayoutKeyRef.current === graphLayoutKey;
		graphLayoutKeyRef.current = graphLayoutKey;
		const graph = buildEditorForceGraphLayout(visibleNodes, visibleCiLinks, {
			nodePositionCache: nodePositionCacheRef.current,
			ticks: reuseCachedLayout ? 0 : undefined,
			width: graphWidth,
			height: graphHeight,
			compactClusters: compactLocationClusters,
			clusterPlacementMode,
		});
		const graphNodes = graph.nodes;
		const graphLinks = graph.links;
		const positionMap = new Map(graphNodes.map((node) => [node.id, node]));
		const statusVisualMap = new Map(
			graphNodes.map((node) => [node.id, getEditorStatusVisual(node.status)]),
		);

		const svg = d3.select(svgElement);
		svg.attr("width", viewportWidth).attr("height", viewportHeight);
		svg.selectAll("*").remove();

		const container = svg.append("g").attr("class", "visual-editor-zoom-root");
		const initialTransform =
			zoomTransformRef.current === d3.zoomIdentity
				? d3.zoomIdentity.translate(
						(viewportWidth - graphWidth) / 2,
						(viewportHeight - graphHeight) / 2,
					)
				: zoomTransformRef.current;
		const zoom = d3
			.zoom<SVGSVGElement, unknown>()
			.extent([
				[0, 0],
				[viewportWidth, viewportHeight],
			])
			.scaleExtent([0.01, 12])
			.on("zoom", (event) => {
				zoomTransformRef.current = event.transform;
				container.attr("transform", event.transform);
			});
		svg.call(zoom);
		svg.call(zoom.transform, initialTransform);

		const linkEndpointIds = (link: (typeof graphLinks)[number]) => ({
			sourceId: typeof link.source === "string" ? link.source : link.source.id,
			targetId: typeof link.target === "string" ? link.target : link.target.id,
		});

		const clusterGroups = new Map<string, EditorGraphNodeDatum[]>();
		graphNodes.forEach((node) => {
			const clusterName = editorClusterName(node.sourceNode);
			clusterGroups.set(clusterName, [
				...(clusterGroups.get(clusterName) ?? []),
				node,
			]);
		});
		const clusterData = Array.from(clusterGroups.entries()).map(
			([name, members]) => {
				const x =
					members.reduce((sum, node) => sum + node.x, 0) / members.length;
				const y =
					members.reduce((sum, node) => sum + node.y, 0) / members.length;
				const memberRadius = Math.max(
					...members.map((node) => {
						const visual = statusVisualMap.get(node.id);
						return Math.hypot(node.x - x, node.y - y) + (visual?.radius ?? 24);
					}),
				);
				return {
					name,
					count: members.length,
					x,
					y,
					radius: Math.max(92, memberRadius + 44),
				};
			},
		);
		const clusterByName = new Map(
			clusterData.map((cluster) => [cluster.name, cluster]),
		);
		const constrainNodeToCluster = (
			node: EditorGraphNodeDatum,
			x: number,
			y: number,
		) => {
			const cluster = clusterByName.get(editorClusterName(node.sourceNode));
			if (!cluster) return { x, y };
			const nodeRadius = statusVisualMap.get(node.id)?.radius ?? 24;
			const maxDistance = Math.max(0, cluster.radius - nodeRadius - 14);
			const dx = x - cluster.x;
			const dy = y - cluster.y;
			const distance = Math.hypot(dx, dy);
			if (distance <= maxDistance || distance === 0) return { x, y };
			const scale = maxDistance / distance;
			return {
				x: cluster.x + dx * scale,
				y: cluster.y + dy * scale,
			};
		};
		const matchingClusterNames = new Set(
			clusterData
				.filter((cluster) =>
					graphNodes.some(
						(node) =>
							editorClusterName(node.sourceNode) === cluster.name &&
							matchingNodeIds.has(node.id),
					),
				)
				.map((cluster) => cluster.name),
		);
		const clusterSelection = container
			.append("g")
			.attr("class", "relationship-clusters")
			.selectAll<SVGGElement, (typeof clusterData)[number]>("g")
			.data(clusterData)
			.join("g")
			.attr("transform", (cluster) => `translate(${cluster.x},${cluster.y})`)
			.attr("opacity", 0.72);

		clusterSelection
			.append("circle")
			.attr("r", (cluster) => cluster.radius)
			.attr("fill", (cluster) =>
				matchingClusterNames.has(cluster.name)
					? "rgba(250, 204, 21, 0.12)"
					: "rgba(15, 23, 42, 0.42)",
			)
			.attr("stroke", (cluster) =>
				matchingClusterNames.has(cluster.name) ? "#facc15" : "#345bf2",
			)
			.attr("stroke-opacity", (cluster) =>
				matchingClusterNames.has(cluster.name) ? 0.78 : 0.36,
			)
			.attr("stroke-width", (cluster) =>
				matchingClusterNames.has(cluster.name) ? 3 : 1.5,
			)
			.attr("stroke-dasharray", "5, 8")
			.style("pointer-events", "none");

		clusterSelection
			.append("text")
			.attr("y", (cluster) => -cluster.radius - 10)
			.attr("text-anchor", "middle")
			.attr("fill", "#e5e7eb")
			.attr("font-size", 10)
			.attr("font-weight", 900)
			.attr("paint-order", "stroke")
			.attr("stroke", "#020617")
			.attr("stroke-width", 4)
			.style("pointer-events", "none")
			.text((cluster) => `${cluster.name} (${cluster.count})`);

		clusterSelection
			.append("title")
			.text((cluster) => `${cluster.name}: ${cluster.count} CIs`);

		const linkSelection = container
			.append("g")
			.attr("class", "relationship-links")
			.selectAll<SVGGElement, (typeof graphLinks)[number]>("g")
			.data(graphLinks)
			.join("g")
			.attr("data-link-source", (link) => linkEndpointIds(link).sourceId)
			.attr("data-link-target", (link) => linkEndpointIds(link).targetId)
			.each(function (link) {
				const { sourceId, targetId } = linkEndpointIds(link);
				const source = positionMap.get(sourceId);
				const target = positionMap.get(targetId);
				if (!source || !target) return;

				const linkGroup = d3.select(this);
				linkGroup
					.append("line")
					.attr("x1", source.x)
					.attr("y1", source.y)
					.attr("x2", target.x)
					.attr("y2", target.y)
					.attr("stroke", statusVisualMap.get(target.id)?.color ?? "#4b5563")
					.attr("stroke-opacity", 0.55)
					.attr("stroke-width", 2)
					.attr(
						"stroke-dasharray",
						link.type === "DEPENDS_ON"
							? "5, 8"
							: link.type === "HOSTED_ON"
								? "2, 2"
								: "none",
					);

				if (graphLinks.length <= 24) {
					linkGroup
						.append("text")
						.attr("x", (source.x + target.x) / 2)
						.attr("y", (source.y + target.y) / 2)
						.attr("fill", "#d4d4d4")
						.attr("font-size", 10)
						.attr("font-weight", 700)
						.text(link.type);
				}
			});

		const updateLinksForNode = (nodeId: string) => {
			linkSelection.each(function (link) {
				const { sourceId, targetId } = linkEndpointIds(link);
				if (sourceId !== nodeId && targetId !== nodeId) return;
				const source = positionMap.get(sourceId);
				const target = positionMap.get(targetId);
				if (!source || !target) return;
				const linkGroup = d3.select(this);
				linkGroup
					.select<SVGLineElement>("line")
					.attr("x1", source.x)
					.attr("y1", source.y)
					.attr("x2", target.x)
					.attr("y2", target.y);
				linkGroup
					.select<SVGTextElement>("text")
					.attr("x", (source.x + target.x) / 2)
					.attr("y", (source.y + target.y) / 2);
			});
		};
		const suppressedClickNodeIds = new Set<string>();
		const nodeSelection = container
			.append("g")
			.attr("class", "relationship-nodes")
			.selectAll<SVGGElement, EditorGraphNodeDatum>("g")
			.data(graphNodes, (node) => node.id)
			.join("g")
			.attr("role", "button")
			.attr("tabindex", 0)
			.attr("aria-label", (node) => `CI node ${node.label}`)
			.attr("title", (node) => `${node.label} · ${node.layer}`)
			.attr("data-node-id", (node) => node.id)
			.attr("transform", (node) => `translate(${node.x},${node.y})`)
			.attr("class", "cursor-pointer")
			.on("click", (_event, node) => {
				if (suppressedClickNodeIds.delete(node.id)) return;
				selectNode(node.id);
			})
			.on("keydown", (event, node) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					selectNode(node.id);
				}
			});

		nodeSelection
			.append("circle")
			.attr("r", (node) => statusVisualMap.get(node.id)?.radius ?? 24)
			.attr("fill", (node) =>
				node.id === sourceId
					? "#345bf2"
					: node.id === targetId
						? "#06b6d4"
						: matchingNodeIds.has(node.id)
							? "#3a2f08"
							: "#1a1a1a",
			)
			.attr("stroke", (node) =>
				matchingNodeIds.has(node.id)
					? "#facc15"
					: (statusVisualMap.get(node.id)?.color ?? "#4b5563"),
			)
			.attr("stroke-width", (node) =>
				matchingNodeIds.has(node.id) ||
				node.id === sourceId ||
				node.id === targetId
					? 5
					: (statusVisualMap.get(node.id)?.strokeWidth ?? 2),
			)
			.attr("filter", (node) =>
				matchingNodeIds.has(node.id) ? "drop-shadow(0 0 14px #facc15)" : null,
			)
			.attr("class", "node-circle transition-all duration-300");

		nodeSelection
			.append("foreignObject")
			.attr("x", (node) => -((statusVisualMap.get(node.id)?.radius ?? 24) - 7))
			.attr("y", (node) => -((statusVisualMap.get(node.id)?.radius ?? 24) - 7))
			.attr(
				"width",
				(node) => ((statusVisualMap.get(node.id)?.radius ?? 24) - 7) * 2,
			)
			.attr(
				"height",
				(node) => ((statusVisualMap.get(node.id)?.radius ?? 24) - 7) * 2,
			)
			.attr("class", "pointer-events-none")
			.each(function (node) {
				this.innerHTML = `<div class="flex h-full w-full items-center justify-center">${renderToStaticMarkup(
					<CategoryIcon
						iconKey={node.sourceNode.category_icon_key}
						categoryName={node.sourceNode.category ?? node.sourceNode.type}
						className="text-[18px] leading-none text-white pointer-events-none select-none"
					/>,
				)}</div>`;
			});

		nodeSelection
			.append("text")
			.attr("dy", "-1.8em")
			.attr("text-anchor", "middle")
			.attr("fill", "#f5f5f5")
			.attr("font-size", 9)
			.attr("font-weight", 900)
			.attr("pointer-events", "none")
			.text((node) => node.label.slice(0, 2).toUpperCase());

		nodeSelection
			.append("text")
			.attr("dy", "3.5em")
			.attr("text-anchor", "middle")
			.attr("fill", "#a3a3a3")
			.attr("font-size", 10)
			.attr("font-weight", 700)
			.attr("class", "node-label pointer-events-none")
			.text((node) => truncateGraphLabel(node.label).displayLabel);

		nodeSelection.call(
			d3
				.drag<SVGGElement, EditorGraphNodeDatum>()
				.on("start", function (event, node) {
					event.sourceEvent?.stopPropagation();
					d3.select(this).raise().attr("data-dragging", "true");
					node.vx = 0;
					node.vy = 0;
				})
				.on("drag", function (event, node) {
					event.sourceEvent?.stopPropagation();
					const next = constrainNodeToCluster(node, event.x, event.y);
					node.x = next.x;
					node.y = next.y;
					node.vx = 0;
					node.vy = 0;
					positionMap.set(node.id, node);
					nodePositionCacheRef.current.set(node.id, {
						x: next.x,
						y: next.y,
						vx: 0,
						vy: 0,
					});
					suppressedClickNodeIds.add(node.id);
					d3.select(this).attr("transform", `translate(${next.x},${next.y})`);
					updateLinksForNode(node.id);
				})
				.on("end", function (event, node) {
					event.sourceEvent?.stopPropagation();
					d3.select(this).attr("data-dragging", null);
					nodePositionCacheRef.current.set(node.id, {
						x: node.x,
						y: node.y,
						vx: 0,
						vy: 0,
					});
				}),
		);

		const selectedStrokeWidth = (node: EditorGraphNodeDatum) =>
			node.id === sourceId || node.id === targetId
				? 5
				: (statusVisualMap.get(node.id)?.strokeWidth ?? 2);
		const resetGraphFocus = () => {
			nodeSelection.attr("opacity", 1);
			nodeSelection
				.select<SVGCircleElement>("circle.node-circle")
				.attr("stroke-width", selectedStrokeWidth)
				.attr("filter", null);
			nodeSelection
				.select<SVGTextElement>("text.node-label")
				.attr("fill", "#a3a3a3")
				.attr("font-weight", 700)
				.text((node) => truncateGraphLabel(node.label).displayLabel);
			linkSelection
				.select<SVGLineElement>("line")
				.attr("stroke-opacity", 0.55)
				.attr("stroke-width", 2);
			linkSelection.select<SVGTextElement>("text").attr("opacity", 1);
		};
		const applyGraphFocus = (activeNodeId: string) => {
			const relatedNodeIds = new Set([activeNodeId]);
			const relatedLinkIds = new Set<string>();
			for (const link of graphLinks) {
				const { sourceId: linkSourceId, targetId: linkTargetId } =
					linkEndpointIds(link);
				if (linkSourceId === activeNodeId || linkTargetId === activeNodeId) {
					relatedNodeIds.add(linkSourceId);
					relatedNodeIds.add(linkTargetId);
					relatedLinkIds.add(link.id);
				}
			}

			nodeSelection.attr("opacity", (node) => {
				if (node.id === activeNodeId) return 1;
				return relatedNodeIds.has(node.id) ? 0.9 : 0.18;
			});
			nodeSelection
				.select<SVGCircleElement>("circle.node-circle")
				.attr("stroke-width", (node) =>
					node.id === activeNodeId ? 7 : selectedStrokeWidth(node),
				)
				.attr("filter", (node) =>
					node.id === activeNodeId ? "drop-shadow(0 0 8px currentColor)" : null,
				);
			nodeSelection
				.select<SVGTextElement>("text.node-label")
				.attr("fill", (node) =>
					node.id === activeNodeId ? "#ffffff" : "#a3a3a3",
				)
				.attr("font-weight", (node) => (node.id === activeNodeId ? 900 : 700))
				.text((node) =>
					node.id === activeNodeId
						? truncateGraphLabel(node.label).fullLabel
						: truncateGraphLabel(node.label).displayLabel,
				);
			linkSelection
				.select<SVGLineElement>("line")
				.attr("stroke-opacity", (link) =>
					relatedLinkIds.has(link.id) ? 0.72 : 0.12,
				)
				.attr("stroke-width", (link) =>
					relatedLinkIds.has(link.id) ? 3 : 1.5,
				);
			linkSelection
				.select<SVGTextElement>("text")
				.attr("opacity", (link) => (relatedLinkIds.has(link.id) ? 1 : 0.18));
		};
		nodeSelection
			.on("mouseover", (_event, node) => applyGraphFocus(node.id))
			.on("mouseout", resetGraphFocus)
			.on("focus", (_event, node) => applyGraphFocus(node.id))
			.on("blur", resetGraphFocus);

		return () => {
			svg.on(".zoom", null);
		};
	}, [
		visibleNodes,
		visibleCiLinks,
		selectNode,
		sourceId,
		targetId,
		compactLocationClusters,
		clusterPlacementMode,
		viewResetNonce,
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
		<div
			className={`${isPageMode ? "flex h-full w-full flex-col bg-neutral-950" : "flex h-full w-full max-w-7xl flex-col rounded-2xl border border-white/10 bg-neutral-950 shadow-2xl"}`}
		>
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
					<div className="absolute left-4 top-4 z-10 max-h-[calc(100%-2rem)] w-72 overflow-y-auto rounded-xl border border-white/10 bg-neutral-950/85 p-3 shadow-xl backdrop-blur custom-scrollbar">
						<div className="mb-3 flex items-center justify-between gap-2">
							<p className="text-[10px] font-black uppercase tracking-widest text-neutral-400">
								View Controls
							</p>
							<button
								type="button"
								onClick={resetGraphView}
								className="rounded-full border border-white/10 px-2 py-1 text-[10px] font-black uppercase text-neutral-300 hover:border-brand-400 hover:text-white"
							>
								Reset View
							</button>
						</div>
						<div className="mb-3 rounded-lg border border-white/5 bg-black/20 p-2">
							<p className="mb-2 text-[10px] font-black uppercase tracking-widest text-neutral-400">
								CI Placement
							</p>
							<div className="grid grid-cols-2 gap-2 text-[10px] font-black uppercase">
								<button
									type="button"
									onClick={() => setClusterPlacementMode("relationshipAware")}
									className={`rounded-lg border px-2 py-1 ${clusterPlacementMode === "relationshipAware" ? "border-brand-400 bg-brand-500/20 text-white" : "border-white/10 text-neutral-400 hover:text-white"}`}
								>
									Auto Links
								</button>
								<button
									type="button"
									onClick={() => setClusterPlacementMode("radial")}
									className={`rounded-lg border px-2 py-1 ${clusterPlacementMode === "radial" ? "border-brand-400 bg-brand-500/20 text-white" : "border-white/10 text-neutral-400 hover:text-white"}`}
								>
									Radial
								</button>
							</div>
							<p className="mt-2 text-[10px] leading-snug text-neutral-500">
								Drag CIs inside their cluster to fine-tune this session.
							</p>
						</div>
						<label className="block">
							<span className="mb-1 block text-[10px] font-black uppercase tracking-widest text-neutral-400">
								Graph Search
							</span>
							<div className="relative">
								<input
									value={graphSearch}
									onChange={(event) => setGraphSearch(event.target.value)}
									placeholder="Search any CI field..."
									className="w-full rounded-lg border border-yellow-500/20 bg-neutral-950 py-2 pl-8 pr-8 text-xs text-white outline-none transition-colors focus:border-yellow-400"
								/>
								<span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-sm text-yellow-400">
									search
								</span>
								{graphSearch && (
									<button
										type="button"
										onClick={() => setGraphSearch("")}
										className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-yellow-300"
									>
										×
									</button>
								)}
							</div>
						</label>

						<div className="mt-4">
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
							<div className="mt-3 max-h-36 space-y-2 overflow-y-auto pr-1 custom-scrollbar">
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

						<div className="mt-4 border-t border-white/10 pt-4">
							<div className="flex items-center justify-between gap-2">
								<div>
									<p className="text-[10px] font-black uppercase tracking-widest text-neutral-400">
										Locations
									</p>
									<p className="text-[10px] text-neutral-500">
										{selectedLocations.length}/{locationOptions.length} selected
									</p>
								</div>
								<div className="flex gap-2 text-[10px] font-black uppercase">
									<button
										type="button"
										onClick={selectAllLocations}
										aria-label="All locations"
										className="text-brand-300 hover:text-brand-200"
									>
										All
									</button>
									<button
										type="button"
										onClick={clearAllLocations}
										aria-label="No locations"
										className="text-neutral-400 hover:text-white"
									>
										None
									</button>
								</div>
							</div>
							<div className="relative mt-2">
								<input
									value={locationSearch}
									onChange={(event) => setLocationSearch(event.target.value)}
									placeholder="Search locations..."
									className="w-full rounded-lg border border-white/5 bg-neutral-950 py-2 pl-8 pr-3 text-xs text-white outline-none transition-colors focus:border-brand-500"
								/>
								<span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-sm text-neutral-600">
									search
								</span>
							</div>
							<div className="mt-3 max-h-44 space-y-2 overflow-y-auto pr-1 custom-scrollbar">
								{filteredLocationOptions.map((option) => (
									<label
										key={option.label}
										className="flex items-center justify-between gap-2 text-xs text-neutral-300"
									>
										<span className="flex items-center gap-2 truncate">
											<input
												type="checkbox"
												checked={selectedLocations.includes(option.label)}
												onChange={() => toggleLocation(option.label)}
												aria-label={`${option.label} location (${option.count} CIs)`}
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
					</div>
					<svg
						ref={graphSvgRef}
						className="absolute inset-0 h-full w-full"
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
									onChange={(event) => updateCiForm("type", event.target.value)}
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
								{targetId ? nodeLabel(nodeMap.get(targetId)) : "Select target"}
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
