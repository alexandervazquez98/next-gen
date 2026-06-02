import type React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MetricHistoryChart from "./MetricHistoryChart";

const { mockFetchNodeMetricHistory } = vi.hoisted(() => ({
	mockFetchNodeMetricHistory: vi.fn(),
}));

vi.mock("../services/queryResources", () => ({
	fetchNodeMetricHistory: mockFetchNodeMetricHistory,
}));

vi.mock("recharts", () => ({
	ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
		<div>{children}</div>
	),
	AreaChart: ({
		children,
		onMouseDown,
		onMouseMove,
		onMouseUp,
	}: {
		children: React.ReactNode;
		onMouseDown?: (event: unknown) => void;
		onMouseMove?: (event: unknown) => void;
		onMouseUp?: () => void;
	}) => (
		<div
			data-testid="area-chart"
			onMouseDown={() =>
				onMouseDown?.({
					activeLabel: "2026-05-12T10:00:00Z",
					activePayload: [{ payload: { rawTime: "2026-05-12T10:00:00Z" } }],
				})
			}
			onMouseMove={() =>
				onMouseMove?.({
					activeLabel: "2026-05-12T10:00:30Z",
					activePayload: [{ payload: { rawTime: "2026-05-12T10:00:30Z" } }],
				})
			}
			onMouseUp={() => onMouseUp?.()}
		>
			{children}
		</div>
	),
	Area: () => null,
	XAxis: () => null,
	YAxis: () => null,
	CartesianGrid: () => null,
	Tooltip: () => null,
	ReferenceArea: () => <div data-testid="reference-area" />,
	Brush: () => <div data-testid="brush" />,
}));

const SAMPLE_HISTORY = [
	{ time: "2026-05-12T10:00:00Z", value: 42 },
	{ time: "2026-05-12T10:00:30Z", value: 43 },
	{ time: "2026-05-12T10:01:00Z", value: 44 },
	{ time: "2026-05-12T10:01:30Z", value: 45 },
];

describe("MetricHistoryChart interactions", () => {
	beforeEach(() => {
		mockFetchNodeMetricHistory.mockReset();
		mockFetchNodeMetricHistory.mockResolvedValue(SAMPLE_HISTORY);
	});

	it("requests the selected quick hour windows", async () => {
		render(
			<MetricHistoryChart nodeId="ci-001" metricId="cpu" metricName="CPU" />,
		);

		await waitFor(() =>
			expect(mockFetchNodeMetricHistory).toHaveBeenLastCalledWith(
				expect.objectContaining({
					hours: 24,
					nodeId: "ci-001",
					metricId: "cpu",
				}),
			),
		);

		fireEvent.click(screen.getByRole("button", { name: "1H" }));
		await waitFor(() =>
			expect(mockFetchNodeMetricHistory).toHaveBeenLastCalledWith(
				expect.objectContaining({
					hours: 1,
					nodeId: "ci-001",
					metricId: "cpu",
				}),
			),
		);

		fireEvent.click(screen.getByRole("button", { name: "72H" }));
		await waitFor(() =>
			expect(mockFetchNodeMetricHistory).toHaveBeenLastCalledWith(
				expect.objectContaining({
					hours: 72,
					nodeId: "ci-001",
					metricId: "cpu",
				}),
			),
		);
	});

	it("uses custom date range instead of quick hour windows", async () => {
		render(
			<MetricHistoryChart
				nodeId="ci-001"
				metricId="cpu"
				metricName="CPU"
				customRange={{
					start: "2026-05-01T00:00:00.000Z",
					end: "2026-06-01T00:00:00.000Z",
				}}
			/>,
		);

		await waitFor(() =>
			expect(mockFetchNodeMetricHistory).toHaveBeenCalledWith(
				expect.objectContaining({
					startTime: "2026-05-01T00:00:00.000Z",
					endTime: "2026-06-01T00:00:00.000Z",
					hours: undefined,
				}),
			),
		);
		expect(
			screen.queryByRole("button", { name: "72H" }),
		).not.toBeInTheDocument();
	});

	it("turns a tiny mouse drag into a stable zoom range", async () => {
		render(
			<MetricHistoryChart nodeId="ci-001" metricId="cpu" metricName="CPU" />,
		);

		await screen.findByTestId("area-chart");
		fireEvent.mouseDown(screen.getByTestId("area-chart"));
		fireEvent.mouseMove(screen.getByTestId("area-chart"));
		fireEvent.mouseUp(screen.getByTestId("area-chart"));

		expect(
			await screen.findByRole("button", { name: /reset view/i }),
		).toBeInTheDocument();
		expect(screen.getByText(/Zoomed:/)).toBeInTheDocument();
	});
});
