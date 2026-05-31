import { describe, expect, it } from "vitest";
import {
	clampClusterCenterToBounds,
	getBoundedClusterDelta,
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
