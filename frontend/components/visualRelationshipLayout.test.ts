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

	it("groups editor nodes by location and distributes them inside cluster targets", () => {
		const graph = buildEditorForceGraphLayout(
			[
				...Array.from({ length: 8 }, (_, index) =>
					baseNode(`a-${index}`, {
						location_name: "City A",
						location: { lat: 19.4326, long: -99.1332 },
					}),
				),
				...Array.from({ length: 4 }, (_, index) =>
					baseNode(`b-${index}`, {
						location_name: "City B",
						location: { lat: 20.5888, long: -100.3899 },
					}),
				),
			],
			[],
			{ ticks: 0, width: 2200, height: 1400 },
		).nodes;
		const cityA = graph.filter(
			(node) => node.sourceNode.location_name === "City A",
		);
		const cityB = graph.filter(
			(node) => node.sourceNode.location_name === "City B",
		);
		const cityASpread = new Set(
			cityA.map(
				(node) => `${Math.round(node.anchorX)}:${Math.round(node.anchorY)}`,
			),
		);
		const cityACenterX =
			cityA.reduce((sum, node) => sum + node.anchorX, 0) / cityA.length;
		const cityBCenterX =
			cityB.reduce((sum, node) => sum + node.anchorX, 0) / cityB.length;

		expect(cityASpread.size).toBe(cityA.length);
		expect(Math.abs(cityACenterX - cityBCenterX)).toBeGreaterThan(200);
	});

	it("can place highly related CIs closer to the cluster center", () => {
		const nodes = [
			...Array.from({ length: 4 }, (_, index) =>
				baseNode(`a-${index + 1}`, {
					location_name: "City A",
					location: { lat: 19.4326, long: -99.1332 },
				}),
			),
			baseNode("b-1", {
				location_name: "City B",
				location: { lat: 20.5888, long: -100.3899 },
			}),
		];
		const relationshipLinks = [
			{
				source: "a-4",
				target: "a-1",
				source_label: "a-4",
				target_label: "a-1",
				relationship: "CONNECTS_TO",
			},
			{
				source: "a-4",
				target: "a-2",
				source_label: "a-4",
				target_label: "a-2",
				relationship: "CONNECTS_TO",
			},
			{
				source: "a-4",
				target: "a-3",
				source_label: "a-4",
				target_label: "a-3",
				relationship: "CONNECTS_TO",
			},
		];
		const radial = buildEditorForceGraphLayout(nodes, relationshipLinks, {
			ticks: 0,
			width: 2200,
			height: 1400,
			clusterPlacementMode: "radial",
		}).nodes;
		const relationshipAware = buildEditorForceGraphLayout(
			nodes,
			relationshipLinks,
			{
				ticks: 0,
				width: 2200,
				height: 1400,
				clusterPlacementMode: "relationshipAware",
			},
		).nodes;
		const clusterCenter = (items: typeof radial) => {
			const cityA = items.filter(
				(node) => node.sourceNode.location_name === "City A",
			);
			return {
				x: cityA.reduce((sum, node) => sum + node.anchorX, 0) / cityA.length,
				y: cityA.reduce((sum, node) => sum + node.anchorY, 0) / cityA.length,
			};
		};
		const distanceFromCityACenter = (items: typeof radial, id: string) => {
			const center = clusterCenter(items);
			const node = items.find((item) => item.id === id)!;
			return Math.hypot(node.anchorX - center.x, node.anchorY - center.y);
		};

		expect(distanceFromCityACenter(relationshipAware, "a-4")).toBeLessThan(
			distanceFromCityACenter(radial, "a-4"),
		);
	});

	it("packs filtered editor clusters closer together without changing full-view anchors", () => {
		const nodes = [
			...Array.from({ length: 3 }, (_, index) =>
				baseNode(`north-${index}`, {
					location_name: "North",
					location: { lat: 26.9, long: -101.4 },
				}),
			),
			...Array.from({ length: 3 }, (_, index) =>
				baseNode(`center-${index}`, {
					location_name: "Center",
					location: { lat: 20.6, long: -100.4 },
				}),
			),
			...Array.from({ length: 3 }, (_, index) =>
				baseNode(`south-${index}`, {
					location_name: "South",
					location: { lat: 16.8, long: -99.9 },
				}),
			),
		];
		const full = buildEditorForceGraphLayout(nodes, [], {
			ticks: 0,
			width: 3000,
			height: 2200,
		}).nodes;
		const compact = buildEditorForceGraphLayout(nodes, [], {
			ticks: 0,
			width: 3000,
			height: 2200,
			compactClusters: true,
		}).nodes;
		const centerFor = (items: typeof full, location: string) => {
			const group = items.filter(
				(node) => node.sourceNode.location_name === location,
			);
			return {
				x: group.reduce((sum, node) => sum + node.anchorX, 0) / group.length,
				y: group.reduce((sum, node) => sum + node.anchorY, 0) / group.length,
			};
		};
		const distance = (
			a: ReturnType<typeof centerFor>,
			b: ReturnType<typeof centerFor>,
		) => Math.hypot(a.x - b.x, a.y - b.y);

		expect(
			distance(centerFor(compact, "North"), centerFor(compact, "South")),
		).toBeLessThan(
			distance(centerFor(full, "North"), centerFor(full, "South")),
		);
		expect(centerFor(full, "Center").x).not.toBe(
			centerFor(compact, "Center").x,
		);
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
