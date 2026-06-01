import * as d3 from "d3";
import type { GraphNode } from "../types";
import { STATUS_COLORS } from "../utils/status";
import {
	GRAPH_NODE_COLLISION_RADIUS,
	estimateClusterRadius,
	getClusterNodeTarget,
	isValidGeoCoordinate,
	projectGeoPointsToCanvas,
	resolveClusterOverlaps,
	summarizeClusterGeoQuality,
} from "./graphLayout";
import type { LinkData } from "./RelationshipManager";

export const VISUAL_EDITOR_VIEWBOX_WIDTH = 9000;
export const VISUAL_EDITOR_VIEWBOX_HEIGHT = 6200;
const EDITOR_CLUSTER_SPACING_MULTIPLIER = 1.25;
const EDITOR_FILTERED_CLUSTER_COMPACT_SCALE = 0.46;

export interface TruncatedGraphLabel {
	displayLabel: string;
	fullLabel: string;
	truncated: boolean;
}

export interface EditorStatusVisual {
	status:
		| "OK"
		| "WARNING"
		| "CRITICAL"
		| "EXCEPTION"
		| "MAINTENANCE"
		| "UNKNOWN";
	color: string;
	radius: number;
	strokeWidth: number;
}

export type EditorGraphNodeDatum = {
	id: string;
	label: string;
	type: GraphNode["type"];
	status?: string;
	layer: string;
	sourceNode: GraphNode;
	anchorX: number;
	anchorY: number;
	x: number;
	y: number;
	vx?: number;
	vy?: number;
};

export type EditorGraphLinkDatum = {
	id: string;
	source: string | EditorGraphNodeDatum;
	target: string | EditorGraphNodeDatum;
	type: string;
	sourceLink: LinkData;
};

export interface EditorGraphDatum {
	nodes: EditorGraphNodeDatum[];
	links: EditorGraphLinkDatum[];
}

export type EditorNodePosition = {
	x: number;
	y: number;
	vx?: number;
	vy?: number;
};

export type EditorNodePositionCache = Map<string, EditorNodePosition>;

export type EditorClusterPlacementMode = "radial" | "relationshipAware";

export interface EditorForceGraphLayoutOptions {
	nodePositionCache?: EditorNodePositionCache;
	ticks?: number;
	width?: number;
	height?: number;
	compactClusters?: boolean;
	clusterPlacementMode?: EditorClusterPlacementMode;
}

const nodeLabel = (node: GraphNode) => node.label || node.id;
const nodeLayer = (node: GraphNode) => node.category ?? node.type;
const hasNumber = (value: unknown): value is number =>
	typeof value === "number" && Number.isFinite(value);

const cloneGraphNode = (node: GraphNode): GraphNode => ({
	...node,
	metadata: { ...(node.metadata ?? {}) },
	location: node.location ? { ...node.location } : undefined,
});

const cloneLink = (link: LinkData): LinkData => ({ ...link });

export const editorClusterName = (node: GraphNode) =>
	String(
		(node as GraphNode & { cluster_name?: string }).cluster_name ||
			(node.metadata as Record<string, unknown> | undefined)?.cluster_name ||
			node.location_name ||
			node.owner ||
			"Unassigned",
	);

const hasExplicitEditorPosition = (node: GraphNode) =>
	hasNumber(node.x) && hasNumber(node.y);

export const truncateGraphLabel = (
	label: string | null | undefined,
	maxLength = 15,
): TruncatedGraphLabel => {
	const fullLabel = label?.trim() || "Unknown CI";
	if (fullLabel.length <= maxLength) {
		return { displayLabel: fullLabel, fullLabel, truncated: false };
	}
	return {
		displayLabel: `${fullLabel.slice(0, Math.max(0, maxLength - 3))}...`,
		fullLabel,
		truncated: true,
	};
};

export const getEditorStatusVisual = (
	status?: string | null,
): EditorStatusVisual => {
	switch (status?.toUpperCase()) {
		case "ACTIVE":
		case "OK":
			return {
				status: "OK",
				color: STATUS_COLORS.OK,
				radius: 24,
				strokeWidth: 2,
			};
		case "WARNING":
			return {
				status: "WARNING",
				color: STATUS_COLORS.WARNING,
				radius: 28,
				strokeWidth: 3,
			};
		case "CRITICAL":
			return {
				status: "CRITICAL",
				color: STATUS_COLORS.CRITICAL,
				radius: 32,
				strokeWidth: 4,
			};
		case "EXCEPTION":
			return {
				status: "EXCEPTION",
				color: STATUS_COLORS.CRITICAL,
				radius: 32,
				strokeWidth: 4,
			};
		case "MAINTENANCE":
			return {
				status: "MAINTENANCE",
				color: STATUS_COLORS.WARNING,
				radius: 28,
				strokeWidth: 3,
			};
		default:
			return {
				status: "UNKNOWN",
				color: STATUS_COLORS.UNKNOWN,
				radius: 24,
				strokeWidth: 2,
			};
	}
};

export const buildEditorGraphDatum = (
	visibleNodes: GraphNode[],
	visibleLinks: LinkData[] = [],
	options: Pick<EditorForceGraphLayoutOptions, "width" | "height"> = {},
): EditorGraphDatum => {
	const width = options.width ?? VISUAL_EDITOR_VIEWBOX_WIDTH;
	const height = options.height ?? VISUAL_EDITOR_VIEWBOX_HEIGHT;
	const geoTargets = projectGeoPointsToCanvas(
		visibleNodes
			.filter((node) =>
				isValidGeoCoordinate(node.location?.lat, node.location?.long),
			)
			.map((node) => ({
				id: node.id,
				lat: node.location?.lat ?? 0,
				long: node.location?.long ?? 0,
			})),
		{ width, height },
	);
	const sortedFallbackIndexes = new Map(
		[...visibleNodes]
			.sort((a, b) => a.id.localeCompare(b.id))
			.map((node, index) => [node.id, index]),
	);
	const nodeIds = new Set(visibleNodes.map((node) => node.id));
	const nodes = visibleNodes.map((node) => {
		const sourceNode = cloneGraphNode(node);
		const positioned = node as GraphNode & {
			anchorX?: number;
			anchorY?: number;
			mapX?: number;
			mapY?: number;
			layer?: string;
		};
		const fallback = rawCoordinateForNode(
			node,
			sortedFallbackIndexes.get(node.id) ?? 0,
			{ width, height, geoTargets },
		);
		const anchorX = hasNumber(positioned.anchorX)
			? positioned.anchorX
			: fallback.x;
		const anchorY = hasNumber(positioned.anchorY)
			? positioned.anchorY
			: fallback.y;
		return {
			id: node.id,
			label: nodeLabel(node),
			type: node.type,
			status: node.status,
			layer: positioned.layer ?? nodeLayer(node),
			sourceNode,
			anchorX,
			anchorY,
			x: hasNumber(positioned.mapX) ? positioned.mapX : anchorX,
			y: hasNumber(positioned.mapY) ? positioned.mapY : anchorY,
		};
	});
	const links = visibleLinks
		.filter((link) => nodeIds.has(link.source) && nodeIds.has(link.target))
		.map((link, index) => ({
			id: `${link.source}->${link.target}:${link.relationship}:${index}`,
			source: link.source,
			target: link.target,
			type: link.relationship,
			sourceLink: cloneLink(link),
		}));

	return { nodes, links };
};

export const buildEditorForceGraphLayout = (
	visibleNodes: GraphNode[],
	visibleLinks: LinkData[] = [],
	options: EditorForceGraphLayoutOptions = {},
): EditorGraphDatum => {
	const width = options.width ?? VISUAL_EDITOR_VIEWBOX_WIDTH;
	const height = options.height ?? VISUAL_EDITOR_VIEWBOX_HEIGHT;
	const graph = buildEditorGraphDatum(visibleNodes, visibleLinks, {
		width,
		height,
	});
	applyEditorClusterTargets(graph.nodes, graph.links, {
		width,
		height,
		compactClusters: options.compactClusters ?? false,
		clusterPlacementMode: options.clusterPlacementMode ?? "relationshipAware",
	});
	const cache = options.nodePositionCache;

	const simulationNodes = graph.nodes.map((node) => {
		const cached = cache?.get(node.id);
		return {
			...node,
			x: cached?.x ?? node.x,
			y: cached?.y ?? node.y,
			vx: cached?.vx ?? node.vx,
			vy: cached?.vy ?? node.vy,
		};
	});
	const simulationLinks = graph.links.map((link) => ({ ...link }));
	const hasCachedNodes = simulationNodes.some((node) => cache?.has(node.id));
	const ticks = options.ticks ?? (hasCachedNodes ? 40 : 120);

	const groupedLayout = hasGroupedEditorLayout(simulationNodes);
	const simulation = d3
		.forceSimulation<EditorGraphNodeDatum>(simulationNodes)
		.force(
			"charge",
			d3
				.forceManyBody<EditorGraphNodeDatum>()
				.strength(groupedLayout ? -8 : -260),
		)
		.force(
			"collision",
			d3
				.forceCollide<EditorGraphNodeDatum>()
				.radius((node) =>
					Math.max(
						GRAPH_NODE_COLLISION_RADIUS,
						getEditorStatusVisual(node.status).radius + 10,
					),
				)
				.iterations(2),
		)
		.force(
			"link",
			groupedLayout
				? null
				: d3
						.forceLink<EditorGraphNodeDatum, EditorGraphLinkDatum>(
							simulationLinks,
						)
						.id((node) => node.id)
						.distance(180)
						.strength(0.08),
		)
		.force(
			"x",
			d3
				.forceX<EditorGraphNodeDatum>((node) => node.anchorX)
				.strength(groupedLayout ? 0.9 : 0.12),
		)
		.force(
			"y",
			d3
				.forceY<EditorGraphNodeDatum>((node) => node.anchorY)
				.strength(groupedLayout ? 0.9 : 0.12),
		)
		.stop();

	if (ticks > 0) simulation.tick(ticks);
	simulation.stop();

	const nodes = simulationNodes.map((node) => ({ ...node }));
	for (const node of nodes) {
		cache?.set(node.id, {
			x: node.x,
			y: node.y,
			vx: node.vx,
			vy: node.vy,
		});
	}

	return { nodes, links: simulationLinks };
};

const applyEditorClusterTargets = (
	nodes: EditorGraphNodeDatum[],
	links: EditorGraphLinkDatum[],
	{
		width,
		height,
		compactClusters,
		clusterPlacementMode,
	}: {
		width: number;
		height: number;
		compactClusters: boolean;
		clusterPlacementMode: EditorClusterPlacementMode;
	},
) => {
	const clusterGroups = new Map<string, EditorGraphNodeDatum[]>();
	nodes.forEach((node) => {
		const clusterName = editorClusterName(node.sourceNode);
		clusterGroups.set(clusterName, [
			...(clusterGroups.get(clusterName) ?? []),
			node,
		]);
	});
	const clusterEntries = Array.from(clusterGroups.entries()).sort(([a], [b]) =>
		a.localeCompare(b),
	);
	if (clusterEntries.length <= 1) return;

	const layouts = clusterEntries.map(([clusterName, group], index) => {
		const quality = summarizeClusterGeoQuality(
			group.map((node) => node.sourceNode),
		);
		return {
			clusterName,
			group,
			index,
			radius:
				estimateClusterRadius(group.length) * EDITOR_CLUSTER_SPACING_MULTIPLIER,
			geo: quality.medianCoordinate,
		};
	});
	const geoLayouts = layouts.filter((layout) => layout.geo);
	const fallbackLayouts = layouts.filter((layout) => !layout.geo);
	const geoBase = projectGeoPointsToCanvas(
		geoLayouts.map((layout) => ({
			id: layout.clusterName,
			lat: layout.geo?.lat ?? 0,
			long: layout.geo?.long ?? 0,
		})),
		{ width, height },
	);
	const clusterCenters: Record<
		string,
		{ x: number; y: number; radius: number; count: number; hasGeo: boolean }
	> = {};

	const sameCoordinateGroups = d3.group(
		geoLayouts,
		(layout) => `${layout.geo?.lat.toFixed(4)},${layout.geo?.long.toFixed(4)}`,
	);
	sameCoordinateGroups.forEach((sameGeoLayouts) => {
		sameGeoLayouts.forEach((layout, index) => {
			const base = geoBase.get(layout.clusterName) || {
				x: width / 2,
				y: height / 2,
			};
			const spreadRadius =
				sameGeoLayouts.length > 1 ? Math.max(820, layout.radius * 2.4) : 0;
			const angle = (index / sameGeoLayouts.length) * Math.PI * 2 - Math.PI / 2;
			clusterCenters[layout.clusterName] = {
				x: base.x + Math.cos(angle) * spreadRadius,
				y: base.y + Math.sin(angle) * spreadRadius,
				radius: layout.radius,
				count: layout.group.length,
				hasGeo: true,
			};
		});
	});

	if (fallbackLayouts.length > 0) {
		const cols = Math.max(1, Math.ceil(Math.sqrt(fallbackLayouts.length)));
		const rows = Math.ceil(fallbackLayouts.length / cols);
		const cellWidth = width / Math.max(cols, 1);
		const cellHeight = height / Math.max(rows, 1);
		fallbackLayouts.forEach((layout, index) => {
			const col = index % cols;
			const row = Math.floor(index / cols);
			clusterCenters[layout.clusterName] = {
				x: cellWidth * (col + 0.5),
				y: cellHeight * (row + 0.5),
				radius: layout.radius,
				count: layout.group.length,
				hasGeo: false,
			};
		});
	}

	const spacedCenters = resolveClusterOverlaps(
		clusterCenters,
		{ width, height, padding: 24 },
		{ padding: 320, iterations: 120 },
	);
	const resolvedCenters = compactClusters
		? compactEditorClusterCenters(spacedCenters, { width, height })
		: spacedCenters;

	const relationshipOrder = buildRelationshipAwareNodeOrder(nodes, links);
	for (const [, group] of clusterEntries) {
		group
			.slice()
			.sort((a, b) => {
				if (clusterPlacementMode === "relationshipAware") {
					const orderDelta =
						(relationshipOrder.get(a.id) ?? Number.MAX_SAFE_INTEGER) -
						(relationshipOrder.get(b.id) ?? Number.MAX_SAFE_INTEGER);
					if (orderDelta !== 0) return orderDelta;
				}
				return a.id.localeCompare(b.id, undefined, { numeric: true });
			})
			.forEach((node, index, sortedGroup) => {
				if (hasExplicitEditorPosition(node.sourceNode)) return;
				const center = resolvedCenters[editorClusterName(node.sourceNode)];
				if (!center) return;
				const target = getClusterNodeTarget(center, index, sortedGroup.length);
				node.anchorX = target.x;
				node.anchorY = target.y;
				node.x = target.x;
				node.y = target.y;
			});
	}
};

const linkNodeId = (endpoint: string | EditorGraphNodeDatum) =>
	typeof endpoint === "string" ? endpoint : endpoint.id;

const buildRelationshipAwareNodeOrder = (
	nodes: EditorGraphNodeDatum[],
	links: EditorGraphLinkDatum[],
) => {
	const nodeIds = new Set(nodes.map((node) => node.id));
	const adjacency = new Map<string, Set<string>>(
		nodes.map((node) => [node.id, new Set<string>()]),
	);
	const degree = new Map(nodes.map((node) => [node.id, 0]));

	for (const link of links) {
		const sourceId = linkNodeId(link.source);
		const targetId = linkNodeId(link.target);
		if (!nodeIds.has(sourceId) || !nodeIds.has(targetId)) continue;
		adjacency.get(sourceId)?.add(targetId);
		adjacency.get(targetId)?.add(sourceId);
		degree.set(sourceId, (degree.get(sourceId) ?? 0) + 1);
		degree.set(targetId, (degree.get(targetId) ?? 0) + 1);
	}

	const ordered = [...nodes]
		.sort((a, b) => {
			const degreeDelta = (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0);
			if (degreeDelta !== 0) return degreeDelta;
			return a.id.localeCompare(b.id, undefined, { numeric: true });
		})
		.map((node) => node.id);
	const visited = new Set<string>();
	const result: string[] = [];

	for (const root of ordered) {
		if (visited.has(root)) continue;
		const queue = [root];
		visited.add(root);
		while (queue.length > 0) {
			const current = queue.shift();
			if (!current) continue;
			result.push(current);
			const neighbors = [...(adjacency.get(current) ?? [])]
				.filter((neighbor) => !visited.has(neighbor))
				.sort((a, b) => {
					const degreeDelta = (degree.get(b) ?? 0) - (degree.get(a) ?? 0);
					if (degreeDelta !== 0) return degreeDelta;
					return a.localeCompare(b, undefined, { numeric: true });
				});
			for (const neighbor of neighbors) {
				visited.add(neighbor);
				queue.push(neighbor);
			}
		}
	}

	return new Map(result.map((id, index) => [id, index]));
};

const compactEditorClusterCenters = (
	centers: Record<
		string,
		{ x: number; y: number; radius: number; count: number; hasGeo: boolean }
	>,
	{ width, height }: { width: number; height: number },
) => {
	const entries = Object.entries(centers);
	if (entries.length <= 1) {
		return Object.fromEntries(
			entries.map(([name, center]) => [
				name,
				{ ...center, x: width / 2, y: height / 2 },
			]),
		);
	}

	const centroid = entries.reduce(
		(acc, [, center]) => ({ x: acc.x + center.x, y: acc.y + center.y }),
		{ x: 0, y: 0 },
	);
	centroid.x /= entries.length;
	centroid.y /= entries.length;

	const compacted = Object.fromEntries(
		entries.map(([name, center]) => [
			name,
			{
				...center,
				x:
					width / 2 +
					(center.x - centroid.x) * EDITOR_FILTERED_CLUSTER_COMPACT_SCALE,
				y:
					height / 2 +
					(center.y - centroid.y) * EDITOR_FILTERED_CLUSTER_COMPACT_SCALE,
			},
		]),
	);

	return resolveClusterOverlaps(
		compacted,
		{ width, height, padding: 160 },
		{ padding: 120, iterations: 100 },
	);
};

const hasGroupedEditorLayout = (nodes: EditorGraphNodeDatum[]) =>
	new Set(nodes.map((node) => editorClusterName(node.sourceNode))).size > 1;

const rawCoordinateForNode = (
	node: GraphNode,
	fallbackIndex: number,
	{
		width,
		height,
		geoTargets,
	}: {
		width: number;
		height: number;
		geoTargets: Map<string, { x: number; y: number }>;
	},
) => {
	if (hasNumber(node.x) && hasNumber(node.y)) return { x: node.x, y: node.y };
	const geoTarget = geoTargets.get(node.id);
	if (geoTarget) return geoTarget;

	const angle = (fallbackIndex / Math.max(1, 12)) * Math.PI * 2 - Math.PI / 2;
	const radius = 260 + Math.floor(fallbackIndex / 12) * 120;
	return {
		x: width / 2 + Math.cos(angle) * radius,
		y: height / 2 + Math.sin(angle) * radius,
	};
};
