import { describe, expect, it } from "vitest";
import {
	canDeleteRelationship,
	isReadOnlyRelationship,
} from "./relationshipCapabilities";

describe("relationshipCapabilities", () => {
	it("marks RUNS_ON as read-only", () => {
		expect(isReadOnlyRelationship("RUNS_ON")).toBe(true);
	});

	it("blocks deleting RUNS_ON relationships", () => {
		expect(canDeleteRelationship("RUNS_ON")).toBe(false);
	});

	it("allows deleting mutable and unknown relationships by default", () => {
		expect(canDeleteRelationship("CONNECTS_TO")).toBe(true);
		expect(canDeleteRelationship("USES_CUSTOM_TYPE")).toBe(true);
	});
});
