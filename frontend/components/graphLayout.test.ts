import { describe, expect, it } from "vitest";
import {
	clampClusterCenterToBounds,
	getBoundedClusterDelta,
	isValidGeoCoordinate,
	projectGeoPointsToCanvas,
	resolveClusterOverlaps,
	summarizeClusterGeoQuality,
} from "./graphLayout";

describe("graph layout bounds", () => {
	it("keeps a cluster circle inside the canvas padding", () => {
		const result = clampClusterCenterToBounds(
			{ x: -50, y: 900, radius: 100 },
			{ width: 800, height: 600, padding: 20 },
		);

		expect(result).toEqual({ x: 120, y: 480, radius: 100 });
	});

	it("reduces manual drag deltas at the graph boundary", () => {
		const delta = getBoundedClusterDelta(
			{ x: 690, y: 300, radius: 80 },
			200,
			0,
			{ width: 800, height: 600, padding: 24 },
		);

		expect(delta).toEqual({ dx: 6, dy: 0 });
	});

	it("centers oversized clusters instead of producing invalid bounds", () => {
		const result = clampClusterCenterToBounds(
			{ x: 10, y: 10, radius: 500 },
			{ width: 800, height: 600, padding: 24 },
		);

		expect(result.x).toBe(400);
		expect(result.y).toBe(300);
	});

	it("pushes initially overlapping clusters apart", () => {
		const result = resolveClusterOverlaps(
			{
				a: { x: 300, y: 300, radius: 90 },
				b: { x: 330, y: 300, radius: 90 },
			},
			{ width: 900, height: 700, padding: 24 },
			{ padding: 20, iterations: 12 },
		);

		const distance = Math.hypot(
			result.a.x - result.b.x,
			result.a.y - result.b.y,
		);
		expect(distance).toBeGreaterThanOrEqual(199);
	});
});

describe("graph geo quality", () => {
	it("validates geographic coordinates", () => {
		expect(isValidGeoCoordinate(-34.6, -58.4)).toBe(true);
		expect(isValidGeoCoordinate(91, -58.4)).toBe(false);
		expect(isValidGeoCoordinate(-34.6, Number.NaN)).toBe(false);
	});

	it("summarizes missing coordinates and median coordinates", () => {
		const quality = summarizeClusterGeoQuality([
			{ id: "a", location: { lat: -34.6, long: -58.4 } },
			{ id: "b", location: { lat: -34.7, long: -58.5 } },
			{ id: "c" },
		]);

		expect(quality.validCoordinateCount).toBe(2);
		expect(quality.missingCoordinateCount).toBe(1);
		expect(quality.medianCoordinate?.lat).toBeCloseTo(-34.65);
		expect(quality.medianCoordinate?.long).toBeCloseTo(-58.45);
	});

	it("marks distant CIs as geo outliers relative to the cluster median", () => {
		const quality = summarizeClusterGeoQuality([
			{ id: "near-1", location: { lat: -34.6, long: -58.4 } },
			{ id: "near-2", location: { lat: -34.61, long: -58.41 } },
			{ id: "near-3", location: { lat: -34.62, long: -58.42 } },
			{ id: "far", location: { lat: -31.4, long: -64.2 } },
		]);

		expect(quality.outlierNodeIds.has("far")).toBe(true);
		expect(quality.outlierNodeIds.has("near-1")).toBe(false);
	});

	it("projects country-scale coordinates inside the drawable canvas", () => {
		const result = projectGeoPointsToCanvas(
			[
				{ id: "west", lat: 32.5, long: -117 },
				{ id: "east", lat: 19.4, long: -99.1 },
			],
			{ width: 1200, height: 800, paddingX: 120, paddingY: 100 },
		);

		expect(result.get("west")?.x).toBeCloseTo(120);
		expect(result.get("west")?.y).toBeCloseTo(100);
		expect(result.get("east")?.x).toBeCloseTo(1080);
		expect(result.get("east")?.y).toBeCloseTo(700);
	});

	it("keeps single-city coordinates stable instead of dividing by a zero-sized domain", () => {
		const result = projectGeoPointsToCanvas(
			[{ id: "same-city", lat: 19.4326, long: -99.1332 }],
			{ width: 1200, height: 800, paddingX: 120, paddingY: 100 },
		);

		expect(result.get("same-city")?.x).toBeCloseTo(600);
		expect(result.get("same-city")?.y).toBeCloseTo(400);
	});
});
