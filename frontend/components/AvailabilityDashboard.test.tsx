import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AvailabilityDashboard from "./AvailabilityDashboard";
import type { AvailabilityReportResponse } from "../types";

const { mockUseAvailabilityReportQuery } = vi.hoisted(() => ({
	mockUseAvailabilityReportQuery: vi.fn(),
}));

vi.mock("../hooks/queries/useAvailabilityReportQuery", () => ({
	useAvailabilityReportQuery: mockUseAvailabilityReportQuery,
}));

const report: AvailabilityReportResponse = {
	window_start: "2026-01-01T00:00:00Z",
	window_end: "2026-01-31T00:00:00Z",
	generated_at: "2026-01-31T00:05:00Z",
	window_days: 30,
	total_groups: 2,
	snmp_coverage: {
		total_ci_with_snmp: 2,
		functional_ci: 1,
		failing_ci: 1,
		no_response_ci: 1,
		no_response_event_count: 2,
		functional_percentage: 50,
		failing_percentage: 50,
	},
	rows: [
		{
			ci_id: "ci-1",
			ci_name: "Core Router",
			event_type: "AVAILABILITY",
			recovered_incidents: 3,
			mttr_seconds: 900,
			mtbf_seconds: 7200,
			downtime_seconds: 2700,
			active_events: 1,
			active_downtime_seconds: 600,
			availability_percentage: 99.87,
			first_failure_at: "2026-01-02T00:00:00Z",
			last_failure_at: "2026-01-20T00:00:00Z",
			ci: {
				id: "ci-1",
				label: "Core Router",
				category: "Network",
				type: "Router",
				ip: "10.0.0.1",
				owner: "NOC",
				brand: "Cisco",
				model: "ISR4331",
				metadata: { rack: "R1", site: "Madrid" },
			},
		},
		{
			ci_id: "ci-2",
			ci_name: "Billing Database",
			event_type: "DATABASE",
			recovered_incidents: 1,
			mttr_seconds: 1800,
			mtbf_seconds: null,
			downtime_seconds: 1800,
			active_events: 0,
			active_downtime_seconds: 0,
			availability_percentage: 99.95,
			first_failure_at: "2026-01-10T00:00:00Z",
			last_failure_at: "2026-01-10T00:00:00Z",
			ci: {
				id: "ci-2",
				label: "Billing Database",
				category: "Database",
				type: "Postgres",
				ip: "10.0.0.20",
				owner: "DataOps",
				brand: "PostgreSQL",
				model: "15",
				metadata: { tier: "gold" },
			},
		},
	],
};

describe("AvailabilityDashboard", () => {
	beforeEach(() => {
		mockUseAvailabilityReportQuery.mockReturnValue({
			data: report,
			isLoading: false,
			error: null,
		});
		URL.createObjectURL = vi.fn(() => "blob:availability");
		URL.revokeObjectURL = vi.fn();
	});

	it("renders availability MTTR, MTBF, and SNMP coverage from the report", () => {
		render(<AvailabilityDashboard />);

		expect(screen.getByText("Availability MTTR/MTBF")).toBeInTheDocument();
		expect(screen.getByText("Core Router")).toBeInTheDocument();
		expect(screen.getByText("Billing Database")).toBeInTheDocument();
		expect(screen.getByText("15m")).toBeInTheDocument();
		expect(screen.getAllByText("2h").length).toBeGreaterThan(0);
		expect(screen.getByText("SNMP functional")).toBeInTheDocument();
		expect(screen.getByText("1/2 (50.00%)")).toBeInTheDocument();
		expect(screen.getByText("SNMP no-response")).toBeInTheDocument();
		expect(screen.getByText("1 CIs / 2 events")).toBeInTheDocument();
	});

	it("handles older availability responses without SNMP coverage", () => {
		mockUseAvailabilityReportQuery.mockReturnValueOnce({
			data: { ...report, snmp_coverage: undefined },
			isLoading: false,
			error: null,
		});

		render(<AvailabilityDashboard />);

		expect(screen.getByText("SNMP functional")).toBeInTheDocument();
		expect(screen.getByText("SNMP no-response")).toBeInTheDocument();
		expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
	});

	it("filters by enriched CI metadata and keeps the search after expanding a row", () => {
		render(<AvailabilityDashboard />);

		const search = screen.getByRole("searchbox", { name: /search availability/i });
		fireEvent.change(search, { target: { value: "DataOps" } });

		expect(screen.getByText("Billing Database")).toBeInTheDocument();
		expect(screen.queryByText("Core Router")).not.toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /expand billing database/i }));

		expect(search).toHaveValue("DataOps");
		expect(screen.getByText("tier")).toBeInTheDocument();
		expect(screen.getByText("gold")).toBeInTheDocument();
	});

	it("filters by represented metadata keys and formatted durations", () => {
		render(<AvailabilityDashboard />);

		const search = screen.getByRole("searchbox", { name: /search availability/i });
		fireEvent.change(search, { target: { value: "rack" } });
		expect(screen.getByText("Core Router")).toBeInTheDocument();
		expect(screen.queryByText("Billing Database")).not.toBeInTheDocument();

		fireEvent.change(search, { target: { value: "15m" } });
		expect(screen.getByText("Core Router")).toBeInTheDocument();
		expect(screen.queryByText("Billing Database")).not.toBeInTheDocument();
	});

	it("filters by category and resets back to all categories", () => {
		render(<AvailabilityDashboard />);

		fireEvent.change(screen.getByLabelText(/category/i), {
			target: { value: "Network" },
		});
		expect(screen.getByText("Core Router")).toBeInTheDocument();
		expect(screen.queryByText("Billing Database")).not.toBeInTheDocument();

		fireEvent.change(screen.getByLabelText(/category/i), {
			target: { value: "ALL" },
		});
		expect(screen.getByText("Billing Database")).toBeInTheDocument();
	});

	it("exports only currently filtered rows to CSV", async () => {
		const click = vi.fn();
		const originalCreateElement = document.createElement.bind(document);
		vi.spyOn(document, "createElement").mockImplementation((tagName) => {
			const element = originalCreateElement(tagName);
			if (tagName === "a") {
				element.click = click;
			}
			return element;
		});

		render(<AvailabilityDashboard />);
		fireEvent.change(screen.getByRole("searchbox", { name: /search availability/i }), {
			target: { value: "Cisco" },
		});
		fireEvent.click(screen.getByRole("button", { name: /export csv/i }));

		await waitFor(() => expect(click).toHaveBeenCalled());
		const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls[0][0] as Blob;
		const csv = await blob.text();
		expect(csv).toContain("Core Router");
		expect(csv).toContain("Cisco");
		expect(csv).not.toContain("Billing Database");
	});

	it("shows loading, error, and empty states", () => {
		mockUseAvailabilityReportQuery.mockReturnValueOnce({ data: undefined, isLoading: true, error: null });
		const { rerender } = render(<AvailabilityDashboard />);
		expect(screen.getByText(/loading availability metrics/i)).toBeInTheDocument();

		mockUseAvailabilityReportQuery.mockReturnValueOnce({ data: undefined, isLoading: false, error: new Error("boom") });
		rerender(<AvailabilityDashboard />);
		expect(screen.getByText(/could not load availability metrics/i)).toBeInTheDocument();

		mockUseAvailabilityReportQuery.mockReturnValueOnce({ data: { ...report, rows: [] }, isLoading: false, error: null });
		rerender(<AvailabilityDashboard />);
		expect(screen.getByText(/no availability incidents/i)).toBeInTheDocument();
	});
});
