import { describe, expect, it } from "vitest";
import type { GraphNode } from "../types";
import {
	buildEditorForceGraphLayout,
	buildEditorGraphDatum,
	getEditorStatusVisual,
	truncateGraphLabel,
} from "./visualRelationshipLayout";

const baseNode = (id: string, extra: Partial<GraphNode> = {}): GraphNode => ({
	id,
	label: id,
	type: "INFRASTRUCTURE",
	status: "OK",
	metadata: {},
	...extra,
});

describe("visual relationship layout", () => {
	it("keeps editor graph datum fallback positions stable across input order changes", () => {
		const nodes = [baseNode("b"), baseNode("a"), baseNode("c")];
		const first = buildEditorGraphDatum(nodes).nodes;
		const second = buildEditorGraphDatum([...nodes].reverse()).nodes;

		expect(
			new Map(first.map((node) => [node.id, [node.anchorX, node.anchorY]])),
		).toEqual(
			new Map(second.map((node) => [node.id, [node.anchorX, node.anchorY]])),
		);
	});

	it("uses explicit CI coordinates as editor force graph anchors", () => {
		const [node] = buildEditorForceGraphLayout(
			[
				baseNode("router", {
					x: 12,
					y: 34,
					location: { lat: 32.5, long: -117 },
				}),
			],
			[],
			{ ticks: 0 },
		).nodes;

		expect(node.anchorX).toBe(12);
		expect(node.anchorY).toBe(34);
		expect(node.x).toBe(12);
		expect(node.y).toBe(34);
	});

	it("uses CMDB location coordinates as editor force graph fallback", () => {
		const graph = buildEditorForceGraphLayout(
			[
				baseNode("origin", { location: { lat: 32.5, long: -117 } }),
				baseNode("east", { location: { lat: 32.5, long: -116.9 } }),
			],
			[],
			{ ticks: 0 },
		).nodes;
		const origin = graph.find((node) => node.id === "origin")!;
		const east = graph.find((node) => node.id === "east")!;

		expect(east.anchorX).toBeGreaterThan(origin.anchorX);
		expect(east.anchorY).toBe(origin.anchorY);
	});

	it("keeps editor force graph fallback positions stable across input order changes", () => {
		const nodes = [baseNode("b"), baseNode("a"), baseNode("c")];
		const first = buildEditorForceGraphLayout(nodes, [], { ticks: 0 }).nodes;
		const second = buildEditorForceGraphLayout([...nodes].reverse(), [], {
			ticks: 0,
		}).nodes;

		expect(
			new Map(first.map((node) => [node.id, [node.anchorX, node.anchorY]])),
		).toEqual(
			new Map(second.map((node) => [node.id, [node.anchorX, node.anchorY]])),
		);
	});

	it("separates overlapping editor force graph nodes without mutating inputs", () => {
		const colocated = Array.from({ length: 5 }, (_, index) =>
			baseNode(`force-${index}`, { x: 100, y: 100 }),
		);
		const originalSnapshot = structuredClone(colocated);

		const graph = buildEditorForceGraphLayout(colocated, [], {
			ticks: 80,
		}).nodes;
		const roundedPositions = new Set(
			graph.map((node) => `${Math.round(node.x)}:${Math.round(node.y)}`),
		);

		expect(roundedPositions.size).toBe(colocated.length);
		expect(colocated).toEqual(originalSnapshot);
	});

	it("reuses cached editor force graph positions for repeated CI identities", () => {
		const cache = new Map([["ci-a", { x: 321, y: 654 }]]);
		const [node] = buildEditorForceGraphLayout(
			[baseNode("ci-a", { x: 10, y: 20 })],
			[],
			{ nodePositionCache: cache, ticks: 0 },
		).nodes;

		expect(node.x).toBe(321);
		expect(node.y).toBe(654);
		expect(node.anchorX).toBe(10);
		expect(node.anchorY).toBe(20);
	});

	it("builds copied editor graph datum without mutating source nodes or links", () => {
		const sourceNode = baseNode("a", {
			label: "Router A",
			category: "Network",
			x: 42,
			y: 84,
		});
		const targetNode = baseNode("b", { label: "Switch B", x: 100, y: 120 });
		const link = {
			source: "a",
			target: "b",
			source_label: "Router A",
			target_label: "Switch B",
			relationship: "CONNECTS_TO",
		};
		const originalNodeSnapshot = structuredClone([sourceNode, targetNode]);
		const originalLinkSnapshot = structuredClone([link]);

		const graph = buildEditorGraphDatum([sourceNode, targetNode], [link]);
		graph.nodes[0].x = 999;
		graph.nodes[0].sourceNode.label = "changed reference label";
		graph.links[0].source = graph.nodes[1];
		graph.links[0].sourceLink.relationship = "DEPENDS_ON";

		expect([sourceNode, targetNode]).toEqual(originalNodeSnapshot);
		expect([link]).toEqual(originalLinkSnapshot);
		expect(graph.nodes[0]).toMatchObject({
			id: "a",
			label: "Router A",
			layer: "Network",
			type: "INFRASTRUCTURE",
			x: 999,
		});
		expect(graph.links[0].id).toBe("a->b:CONNECTS_TO:0");
	});

	it("truncates labels for dense graph views while preserving the full label", () => {
		expect(truncateGraphLabel("Router A")).toEqual({
			displayLabel: "Router A",
			fullLabel: "Router A",
			truncated: false,
		});
		expect(truncateGraphLabel("Very Long Router Label")).toEqual({
			displayLabel: "Very Long Ro...",
			fullLabel: "Very Long Router Label",
			truncated: true,
		});
		expect(truncateGraphLabel("")).toEqual({
			displayLabel: "Unknown CI",
			fullLabel: "Unknown CI",
			truncated: false,
		});
	});

	it("normalizes GraphCMDB and editor statuses to safe visual tokens", () => {
		expect(getEditorStatusVisual("ACTIVE")).toMatchObject({
			status: "OK",
			color: "#10b981",
			radius: 24,
		});
		expect(getEditorStatusVisual("OK").color).toBe("#10b981");
		expect(getEditorStatusVisual("WARNING")).toMatchObject({
			status: "WARNING",
			color: "#f59e0b",
			radius: 28,
		});
		expect(getEditorStatusVisual("CRITICAL")).toMatchObject({
			status: "CRITICAL",
			color: "#ef4444",
			radius: 32,
		});
		expect(getEditorStatusVisual("EXCEPTION")).toMatchObject({
			status: "EXCEPTION",
			color: "#ef4444",
			radius: 32,
		});
		expect(getEditorStatusVisual("MAINTENANCE")).toMatchObject({
			status: "MAINTENANCE",
			color: "#f59e0b",
			radius: 28,
		});
		expect(getEditorStatusVisual("NOT_A_STATUS")).toMatchObject({
			status: "UNKNOWN",
			color: "#4b5563",
			radius: 24,
		});
	});
});
