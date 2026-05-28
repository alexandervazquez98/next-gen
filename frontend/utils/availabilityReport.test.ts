import { describe, expect, it } from "vitest";
import {
	availabilityRowsToCsv,
	buildAvailabilitySearchText,
	filterAvailabilityRows,
	getAvailabilityCategory,
} from "./availabilityReport";
import type { AvailabilityReportRow } from "../types";

const baseRow: AvailabilityReportRow = {
	ci_id: "ci-1",
	ci_name: "Core Router",
	event_type: "AVAILABILITY",
	recovered_incidents: 1,
	mttr_seconds: 900,
	mtbf_seconds: 7200,
	downtime_seconds: 900,
	active_events: 0,
	active_downtime_seconds: 0,
	availability_percentage: 99.9,
	first_failure_at: "2026-01-01T00:00:00Z",
	last_failure_at: "2026-01-01T00:15:00Z",
};

describe("availabilityReport helpers", () => {
	it("builds search text from represented keys, values, and formatted durations", () => {
		const row: AvailabilityReportRow = {
			...baseRow,
			ci: {
				id: "ci-1",
				label: "Core Router",
				type: "Router",
				metadata: { rack: "R1", support_contact: { phone: "+34123456789" } },
			},
		};

		const searchText = buildAvailabilitySearchText(row);

		expect(searchText).toContain("rack");
		expect(searchText).toContain("support_contact");
		expect(searchText).toContain("+34123456789");
		expect(searchText).toContain("15m");
		expect(searchText).toContain("2h");
	});

	it("uses CI type as category fallback", () => {
		const row: AvailabilityReportRow = {
			...baseRow,
			ci: { id: "ci-1", label: "Core Router", type: "Router" },
		};

		expect(getAvailabilityCategory(row)).toBe("Router");
		expect(filterAvailabilityRows([row], "", "Router")).toEqual([row]);
	});

	it("escapes CSV values containing commas, quotes, LF, or CR", () => {
		const row: AvailabilityReportRow = {
			...baseRow,
			ci: {
				id: "ci-1",
				label: "Core Router",
				category: "Network",
				brand: "ACME, Inc.",
				model: "Quote \"Model\"\rLegacy",
			},
		};

		const csv = availabilityRowsToCsv([row]);

		expect(csv).toContain('"ACME, Inc."');
		expect(csv).toContain('"Quote ""Model""\rLegacy"');
	});
});
