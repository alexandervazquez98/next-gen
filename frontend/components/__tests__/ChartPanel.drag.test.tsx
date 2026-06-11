import type React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChartPanel from "../ChartPanel";
import type { DataPoint } from "../../types";

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

const SAMPLE_DATA: DataPoint[] = [
	{ time: "2026-05-12T10:00:00Z", value: 42 },
	{ time: "2026-05-12T10:00:30Z", value: 43 },
	{ time: "2026-05-12T10:01:00Z", value: 45 },
	{ time: "2026-05-12T10:01:30Z", value: 44 },
];

describe("ChartPanel drag selection", () => {
	it("emits a synchronized timestamp range from mouse drag", () => {
		const onBrushChange = vi.fn();
		render(
			<ChartPanel
				nodeId="ci-001"
				label="Router-01"
				data={SAMPLE_DATA}
				brushRange={null}
				onBrushChange={onBrushChange}
			/>,
		);

		fireEvent.mouseDown(screen.getByTestId("area-chart"));
		fireEvent.mouseMove(screen.getByTestId("area-chart"));
		fireEvent.mouseUp(screen.getByTestId("area-chart"));

		expect(onBrushChange).toHaveBeenCalledWith({
			startTime: "2026-05-12T10:00:00Z",
			endTime: "2026-05-12T10:01:00Z",
		});
	});
});
