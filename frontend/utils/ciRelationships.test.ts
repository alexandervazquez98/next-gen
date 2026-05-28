import { describe, expect, it } from "vitest";
import {
	formatCiRelationshipDetails,
	getCiRelationshipDetails,
	getCiRelationshipState,
} from "./ciRelationships";

describe("ciRelationships", () => {
	it("derives none, incoming, outgoing, and both states", () => {
		expect(getCiRelationshipState()).toBe("none");
		expect(getCiRelationshipState({ asSource: [], asTarget: [] })).toBe("none");
		expect(
			getCiRelationshipState({
				asSource: [{ otherId: "ci-b", otherLabel: "Switch B", type: "CONNECTS_TO" }],
				asTarget: [],
			}),
		).toBe("outgoing");
		expect(
			getCiRelationshipState({
				asSource: [],
				asTarget: [{ otherId: "ci-a", otherLabel: "Router A", type: "DEPENDS_ON" }],
			}),
		).toBe("incoming");
		expect(
			getCiRelationshipState({
				asSource: [{ otherId: "ci-c", otherLabel: "Server C", type: "HOSTED_ON" }],
				asTarget: [{ otherId: "ci-a", otherLabel: "Router A", type: "CONNECTS_TO" }],
			}),
		).toBe("both");
	});

	it("formats relationship details with direction, type, label, and id", () => {
		const summary = {
			asSource: [{ otherId: "ci-b", otherLabel: "Switch B", type: "CONNECTS_TO" }],
			asTarget: [{ otherId: "ci-a", otherLabel: "Router A", type: "DEPENDS_ON" }],
		};

		expect(getCiRelationshipDetails(summary)).toEqual([
			{ direction: "OUTGOING", type: "CONNECTS_TO", otherId: "ci-b", otherLabel: "Switch B" },
			{ direction: "INCOMING", type: "DEPENDS_ON", otherId: "ci-a", otherLabel: "Router A" },
		]);
		expect(formatCiRelationshipDetails(summary)).toContain("OUTGOING: CONNECTS_TO Switch B (ci-b)");
		expect(formatCiRelationshipDetails(summary)).toContain("INCOMING: DEPENDS_ON Router A (ci-a)");
	});
});
