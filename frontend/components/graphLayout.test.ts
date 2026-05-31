import { describe, expect, it } from "vitest";
import {
	clampClusterCenterToBounds,
	getBoundedClusterDelta,
	isValidGeoCoordinate,
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
});
