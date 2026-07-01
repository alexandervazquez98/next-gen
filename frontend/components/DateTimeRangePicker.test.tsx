import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DateTimeRangePicker from "./DateTimeRangePicker";

describe("DateTimeRangePicker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 5, 15, 12, 0, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

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

    fireEvent.click(screen.getByRole("button", { name: /startchoose start date/i }));

    expect(screen.getByLabelText("Time")).toBeInTheDocument();
    expect(screen.getByText("History markers not loaded yet.")).toBeInTheDocument();
    expect(screen.getByTitle("Metric history available")).toBeInTheDocument();
  });

  it("notifies when a visible month needs history markers", () => {
    const onVisibleMonthChange = vi.fn();
    render(
      <DateTimeRangePicker
        startDate="2026-06-10T08:30"
        endDate=""
        onStartDateChange={vi.fn()}
        onEndDateChange={vi.fn()}
        onReset={vi.fn()}
        onVisibleMonthChange={onVisibleMonthChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /start/i }));

    expect(onVisibleMonthChange).toHaveBeenCalledWith("2026-06");
  });

  it("distinguishes loading and confirmed-empty calendar marker states", () => {
    const { rerender } = render(
      <DateTimeRangePicker
        startDate="2026-06-10T08:30"
        endDate=""
        onStartDateChange={vi.fn()}
        onEndDateChange={vi.fn()}
        onReset={vi.fn()}
        loadingMonths={new Set(["2026-06"])}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /start/i }));
    expect(screen.getByText("Loading history markers…")).toBeInTheDocument();

    rerender(
      <DateTimeRangePicker
        startDate="2026-06-10T08:30"
        endDate=""
        onStartDateChange={vi.fn()}
        onEndDateChange={vi.fn()}
        onReset={vi.fn()}
        loadedMonths={new Set(["2026-06"])}
      />,
    );

    expect(screen.getByText("Green days contain confirmed metric history.")).toBeInTheDocument();
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
