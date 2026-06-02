import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DateTimeRangePicker from "./DateTimeRangePicker";

describe("DateTimeRangePicker", () => {
	it("opens a calendar and time control from the start button", () => {
		render(
			<DateTimeRangePicker
				startDate=""
				endDate=""
				onStartDateChange={vi.fn()}
				onEndDateChange={vi.fn()}
				onReset={vi.fn()}
				availableDays={new Set(["2026-06-01"])}
			/>,
		);

		fireEvent.click(
			screen.getByRole("button", { name: /startchoose start date/i }),
		);

		expect(screen.getByLabelText("Time")).toBeInTheDocument();
		expect(
			screen.getByText("Green days contain metric history."),
		).toBeInTheDocument();
		expect(screen.getByTitle("Metric history available")).toBeInTheDocument();
	});

	it("updates the selected date while preserving the time", () => {
		const onStartDateChange = vi.fn();
		render(
			<DateTimeRangePicker
				startDate="2026-06-10T08:30"
				endDate=""
				onStartDateChange={onStartDateChange}
				onEndDateChange={vi.fn()}
				onReset={vi.fn()}
				availableDays={new Set(["2026-06-01"])}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: /start/i }));
		fireEvent.click(screen.getByTitle("Metric history available"));

		expect(onStartDateChange).toHaveBeenCalledWith("2026-06-01T08:30");
	});
});
