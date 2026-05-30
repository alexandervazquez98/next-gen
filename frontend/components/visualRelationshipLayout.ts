import * as d3 from "d3";
import type { GraphNode } from "../types";
import { STATUS_COLORS } from "../utils/status";
import type { LinkData } from "./RelationshipManager";

export const VISUAL_EDITOR_VIEWBOX_WIDTH = 2200;
export const VISUAL_EDITOR_VIEWBOX_HEIGHT = 1400;

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

export interface EditorForceGraphLayoutOptions {
	nodePositionCache?: EditorNodePositionCache;
	ticks?: number;
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
): EditorGraphDatum => {
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
	const graph = buildEditorGraphDatum(visibleNodes, visibleLinks);
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

	const simulation = d3
		.forceSimulation<EditorGraphNodeDatum>(simulationNodes)
		.force("charge", d3.forceManyBody<EditorGraphNodeDatum>().strength(-260))
		.force(
			"collision",
			d3
				.forceCollide<EditorGraphNodeDatum>()
				.radius((node) => getEditorStatusVisual(node.status).radius + 34),
		)
		.force(
			"link",
			d3
				.forceLink<EditorGraphNodeDatum, EditorGraphLinkDatum>(simulationLinks)
				.id((node) => node.id)
				.distance(180)
				.strength(0.08),
		)
		.force(
			"x",
			d3.forceX<EditorGraphNodeDatum>((node) => node.anchorX).strength(0.12),
		)
		.force(
			"y",
			d3.forceY<EditorGraphNodeDatum>((node) => node.anchorY).strength(0.12),
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

const rawCoordinateForNode = (node: GraphNode, fallbackIndex: number) => {
	if (hasNumber(node.x) && hasNumber(node.y)) return { x: node.x, y: node.y };
	if (hasNumber(node.location?.long) && hasNumber(node.location?.lat)) {
		return {
			x: VISUAL_EDITOR_VIEWBOX_WIDTH / 2 + (node.location.long + 117) * 3000,
			y: VISUAL_EDITOR_VIEWBOX_HEIGHT / 2 - (node.location.lat - 32.5) * 3000,
		};
	}

	const angle = (fallbackIndex / Math.max(1, 12)) * Math.PI * 2 - Math.PI / 2;
	const radius = 260 + Math.floor(fallbackIndex / 12) * 120;
	return {
		x: VISUAL_EDITOR_VIEWBOX_WIDTH / 2 + Math.cos(angle) * radius,
		y: VISUAL_EDITOR_VIEWBOX_HEIGHT / 2 + Math.sin(angle) * radius,
	};
};
