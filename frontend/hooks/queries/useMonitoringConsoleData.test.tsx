import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMonitoringConsoleData } from "./useMonitoringConsoleData";

const mockUseNodesQuery = vi.fn();
const mockUseLinksQuery = vi.fn();
const mockUseActiveEventsQuery = vi.fn();
const mockUseAvailabilityReportQuery = vi.fn();
const mockUseCategoriesQuery = vi.fn();

vi.mock("./useNodesQuery", () => ({
	useNodesQuery: () => mockUseNodesQuery(),
}));
vi.mock("./useLinksQuery", () => ({
	useLinksQuery: () => mockUseLinksQuery(),
}));
vi.mock("./useActiveEventsQuery", () => ({
	useActiveEventsQuery: () => mockUseActiveEventsQuery(),
}));
vi.mock("./useAvailabilityReportQuery", () => ({
	useAvailabilityReportQuery: () => mockUseAvailabilityReportQuery(),
}));
vi.mock("./useCategoriesQuery", () => ({
	useCategoriesQuery: () => mockUseCategoriesQuery(),
}));

function Probe() {
	const data = useMonitoringConsoleData();
	return <pre data-testid="payload">{JSON.stringify(data)}</pre>;
}

describe("useMonitoringConsoleData", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockUseNodesQuery.mockReturnValue({
			data: [{ id: "node-1", type: "INFRASTRUCTURE" }],
			isLoading: false,
			error: null,
		});
		mockUseLinksQuery.mockReturnValue({
			data: [{ id: "link-1" }],
			isLoading: false,
			error: null,
		});
		mockUseActiveEventsQuery.mockReturnValue({
			data: [{ id: "evt-1", ci_id: "node-1" }],
			isLoading: false,
			error: null,
		});
		mockUseAvailabilityReportQuery.mockReturnValue({
			data: { rows: [{ ci_id: "node-1", event_type: "AVAILABILITY" }] },
			isLoading: false,
			error: null,
		});
		mockUseCategoriesQuery.mockReturnValue({
			data: [{ name: "Network" }],
			isLoading: false,
			error: null,
		});
	});

	it("combines shared monitoring resources into one screen-facing contract", () => {
		render(<Probe />);

		expect(screen.getByTestId("payload")).toHaveTextContent(
			'"nodes":[{"id":"node-1","type":"INFRASTRUCTURE"}]',
		);
		expect(screen.getByTestId("payload")).toHaveTextContent(
			'"links":[{"id":"link-1"}]',
		);
		expect(screen.getByTestId("payload")).toHaveTextContent(
			'"events":[{"id":"evt-1","ci_id":"node-1"}]',
		);
		expect(mockUseAvailabilityReportQuery).not.toHaveBeenCalled();
		expect(screen.getByTestId("payload")).not.toHaveTextContent(
			"availabilityReport",
		);
		expect(screen.getByTestId("payload")).toHaveTextContent(
			'"categories":["Network"]',
		);
	});

	it("does not let availability report failures affect monitoring", () => {
		mockUseAvailabilityReportQuery.mockImplementation(() => {
			throw new Error("availability report should not be queried by monitoring");
		});

		render(<Probe />);

		expect(screen.getByTestId("payload")).toHaveTextContent('"error":null');
		expect(screen.getByTestId("payload")).not.toHaveTextContent(
			"availabilityReport",
		);
	});

	it("surfaces node types when category names are missing", () => {
		mockUseCategoriesQuery.mockReturnValue({
			data: [],
			isLoading: false,
			error: null,
		});

		render(<Probe />);

		expect(screen.getByTestId("payload")).toHaveTextContent(
			'"categories":["INFRASTRUCTURE"]',
		);
	});
});
