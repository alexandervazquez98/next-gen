import type React from "react";
import { useEffect, useMemo, useState } from "react";

interface DateTimeRangePickerProps {
	startDate: string;
	endDate: string;
	onStartDateChange: (value: string) => void;
	onEndDateChange: (value: string) => void;
	onReset: () => void;
	availableDays?: Set<string>;
	loadedMonths?: Set<string>;
	loadingMonths?: Set<string>;
	onVisibleMonthChange?: (monthKey: string) => void;
}

type PickerTarget = "start" | "end";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const toDateKey = (date: Date) => {
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	return `${year}-${month}-${day}`;
};

const toMonthStart = (value?: string) => {
	const base = value ? new Date(value) : new Date();
	return new Date(base.getFullYear(), base.getMonth(), 1);
};

const toMonthKey = (date: Date) => {
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
	return `${year}-${month}`;
};

const formatButtonLabel = (value: string, fallback: string) => {
	if (!value) return fallback;
	const date = new Date(value);
	return Number.isNaN(date.getTime())
		? fallback
		: date.toLocaleString([], {
				month: "short",
				day: "numeric",
				year: "numeric",
				hour: "2-digit",
				minute: "2-digit",
			});
};

const setDatePart = (currentValue: string, dayKey: string) => {
	const timePart = currentValue.split("T")[1] || "00:00";
	return `${dayKey}T${timePart.slice(0, 5)}`;
};

const setTimePart = (currentValue: string, time: string) => {
	const dayPart = currentValue.split("T")[0] || toDateKey(new Date());
	return `${dayPart}T${time}`;
};

const getTimePart = (value: string) =>
	value.split("T")[1]?.slice(0, 5) || "00:00";

const DateTimeRangePicker: React.FC<DateTimeRangePickerProps> = ({
	startDate,
	endDate,
	onStartDateChange,
	onEndDateChange,
	onReset,
	availableDays = new Set(),
	loadedMonths = new Set(),
	loadingMonths = new Set(),
	onVisibleMonthChange,
}) => {
	const [openTarget, setOpenTarget] = useState<PickerTarget | null>(null);
	const [visibleMonth, setVisibleMonth] = useState(() =>
		toMonthStart(startDate || endDate),
	);

	useEffect(() => {
		if (openTarget === "start") setVisibleMonth(toMonthStart(startDate));
		if (openTarget === "end")
			setVisibleMonth(toMonthStart(endDate || startDate));
	}, [openTarget, startDate, endDate]);

	useEffect(() => {
		if (!openTarget) return;
		onVisibleMonthChange?.(toMonthKey(visibleMonth));
	}, [openTarget, visibleMonth, onVisibleMonthChange]);

	const selectedValue = openTarget === "end" ? endDate : startDate;
	const selectedDay = selectedValue.split("T")[0];
	const visibleMonthKey = toMonthKey(visibleMonth);
	const isVisibleMonthLoaded = loadedMonths.has(visibleMonthKey);
	const isVisibleMonthLoading = loadingMonths.has(visibleMonthKey);
	const monthLabel = visibleMonth.toLocaleDateString([], {
		month: "long",
		year: "numeric",
	});

	const calendarDays = useMemo(() => {
		const firstDay = new Date(
			visibleMonth.getFullYear(),
			visibleMonth.getMonth(),
			1,
		);
		const start = new Date(firstDay);
		start.setDate(firstDay.getDate() - firstDay.getDay());
		return Array.from({ length: 42 }, (_, index) => {
			const date = new Date(start);
			date.setDate(start.getDate() + index);
			return date;
		});
	}, [visibleMonth]);

	const updateValue = (value: string) => {
		if (openTarget === "end") onEndDateChange(value);
		else onStartDateChange(value);
	};

	const moveMonth = (delta: number) => {
		setVisibleMonth(
			(current) =>
				new Date(current.getFullYear(), current.getMonth() + delta, 1),
		);
	};

	return (
		<div className="min-w-0 space-y-3">
			<div className="grid grid-cols-1 gap-2">
				<button
					type="button"
					onClick={() => setOpenTarget(openTarget === "start" ? null : "start")}
					className="flex w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-white/10 bg-black/40 p-2 text-left text-xs text-white outline-none transition-colors hover:border-emerald-500/50 focus:border-brand-500"
				>
					<span className="min-w-0">
						<span className="block text-[10px] uppercase tracking-wider text-neutral-500">
							Start
						</span>
						<span className="block truncate">
							{formatButtonLabel(startDate, "Choose start date")}
						</span>
					</span>
					<span className="material-symbols-outlined text-base text-emerald-400">
						calendar_clock
					</span>
				</button>
				<button
					type="button"
					onClick={() => setOpenTarget(openTarget === "end" ? null : "end")}
					className="flex w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-white/10 bg-black/40 p-2 text-left text-xs text-white outline-none transition-colors hover:border-emerald-500/50 focus:border-brand-500"
				>
					<span className="min-w-0">
						<span className="block text-[10px] uppercase tracking-wider text-neutral-500">
							End
						</span>
						<span className="block truncate">
							{formatButtonLabel(endDate, "Choose end date")}
						</span>
					</span>
					<span className="material-symbols-outlined text-base text-emerald-400">
						schedule
					</span>
				</button>
			</div>

			{openTarget && (
				<div className="rounded-xl border border-white/10 bg-black/70 p-3 shadow-2xl">
					<div className="mb-2 rounded-lg border border-white/5 bg-white/[0.03] px-2 py-1 text-[10px] text-neutral-500">
						{isVisibleMonthLoading
							? "Loading history markers…"
							: isVisibleMonthLoaded
								? "Green days contain confirmed metric history."
								: "History markers not loaded yet."}
					</div>
					<div className="mb-3 flex items-center justify-between gap-2">
						<button
							type="button"
							onClick={() => moveMonth(-1)}
							className="rounded-md bg-white/5 px-2 py-1 text-xs text-neutral-300 hover:bg-white/10"
							aria-label="Previous month"
						>
							‹
						</button>
						<p className="text-xs font-bold uppercase tracking-wider text-white">
							{monthLabel}
						</p>
						<button
							type="button"
							onClick={() => moveMonth(1)}
							className="rounded-md bg-white/5 px-2 py-1 text-xs text-neutral-300 hover:bg-white/10"
							aria-label="Next month"
						>
							›
						</button>
					</div>

					<div className="mb-1 grid grid-cols-7 gap-1 text-center text-[9px] font-bold uppercase text-neutral-600">
						{WEEKDAYS.map((day) => (
							<span key={day}>{day}</span>
						))}
					</div>
					<div className="grid grid-cols-7 gap-1">
						{calendarDays.map((date) => {
							const dayKey = toDateKey(date);
							const dayMonthKey = toMonthKey(date);
							const isCurrentMonth =
								date.getMonth() === visibleMonth.getMonth();
							const isMonthLoaded = loadedMonths.has(dayMonthKey);
							const isMonthLoading = loadingMonths.has(dayMonthKey);
							const hasHistory = availableDays.has(dayKey);
							const isSelected = selectedDay === dayKey;
							const dayClass = isSelected
								? "bg-brand-600 text-white"
								: hasHistory
									? "bg-emerald-500/25 text-emerald-100 ring-1 ring-emerald-500/40"
									: isMonthLoaded
										? "bg-white/[0.02] text-neutral-600"
										: isMonthLoading
											? "animate-pulse bg-white/[0.05] text-neutral-500"
											: "border border-dashed border-white/10 bg-transparent text-neutral-500 hover:bg-white/10";
							return (
								<button
									key={dayKey}
									type="button"
									onClick={() =>
										updateValue(setDatePart(selectedValue, dayKey))
									}
									title={hasHistory ? "Metric history available" : undefined}
									className={`relative rounded-md px-0 py-1.5 text-[10px] transition-colors ${dayClass} ${!isCurrentMonth ? "opacity-35" : ""}`}
								>
									{date.getDate()}
									{hasHistory && (
										<span className="absolute bottom-0.5 left-1/2 h-0.5 w-3 -translate-x-1/2 rounded-full bg-emerald-400" />
									)}
								</button>
							);
						})}
					</div>

					<label className="mt-3 block text-[10px] uppercase tracking-wider text-neutral-500">
						Time
						<input
							type="time"
							value={getTimePart(selectedValue)}
							onChange={(event) =>
								updateValue(setTimePart(selectedValue, event.target.value))
							}
							className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 p-2 text-xs text-white outline-none focus:border-brand-500"
						/>
					</label>
					<p className="mt-2 text-[10px] text-neutral-500">
						Unmarked days may still be loading; gray days are confirmed empty.
					</p>
				</div>
			)}

			{startDate && endDate && (
				<button
					type="button"
					onClick={onReset}
					className="mt-2 w-full rounded-lg bg-white/5 py-2 text-xs font-bold uppercase text-neutral-300 transition-colors hover:bg-white/10"
				>
					Reset to Live View
				</button>
			)}
		</div>
	);
};

export default DateTimeRangePicker;
