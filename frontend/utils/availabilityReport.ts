import type { AvailabilityReportRow } from "../types";

const CSV_COLUMNS = [
	"CI Name",
	"CI ID",
	"Category",
	"Type",
	"IP",
	"Owner",
	"Brand",
	"Model",
	"Event Type",
	"Availability %",
	"MTTR Seconds",
	"MTBF Seconds",
	"Recovered Incidents",
	"Active Events",
	"Downtime Seconds",
	"Active Downtime Seconds",
	"First Failure",
	"Last Failure",
];

export const formatDurationSeconds = (seconds?: number | null): string => {
	if (seconds == null || Number.isNaN(seconds)) return "—";
	if (seconds < 60) return `${Math.round(seconds)}s`;
	const minutes = seconds / 60;
	if (minutes < 60) return `${Math.round(minutes)}m`;
	const hours = minutes / 60;
	if (hours < 24) return `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h`;
	const days = hours / 24;
	return `${Number.isInteger(days) ? days : days.toFixed(1)}d`;
};

export const getAvailabilityCategory = (row: AvailabilityReportRow): string =>
	row.ci?.category || row.ci?.type || "Uncategorized";

const flattenSearchValues = (value: unknown): string[] => {
	if (value == null) return [];
	if (["string", "number", "boolean"].includes(typeof value)) {
		return [String(value)];
	}
	if (Array.isArray(value)) return value.flatMap(flattenSearchValues);
	if (typeof value === "object") {
		return Object.entries(value as Record<string, unknown>).flatMap(([key, nestedValue]) => [
			key,
			...flattenSearchValues(nestedValue),
		]);
	}
	return [];
};

export const buildAvailabilitySearchText = (row: AvailabilityReportRow): string =>
	[
		...flattenSearchValues(row),
		formatDurationSeconds(row.mttr_seconds),
		formatDurationSeconds(row.mtbf_seconds),
		getAvailabilityCategory(row),
	]
		.join(" ")
		.toLowerCase();

export const filterAvailabilityRows = (
	rows: AvailabilityReportRow[],
	searchTerm: string,
	category: string,
): AvailabilityReportRow[] => {
	const query = searchTerm.trim().toLowerCase();
	return rows.filter((row) => {
		const categoryMatches =
			category === "ALL" || getAvailabilityCategory(row) === category;
		const searchMatches =
			!query || buildAvailabilitySearchText(row).includes(query);
		return categoryMatches && searchMatches;
	});
};

const csvValue = (value: unknown): string => {
	if (value == null) return "";
	const text = String(value);
	if (/[",\n\r]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
	return text;
};

export const availabilityRowsToCsv = (rows: AvailabilityReportRow[]): string => {
	const lines = [CSV_COLUMNS.join(",")];
	rows.forEach((row) => {
		lines.push(
			[
				row.ci?.label || row.ci_name || row.ci_id,
				row.ci_id,
				getAvailabilityCategory(row),
				row.ci?.type,
				row.ci?.ip,
				row.ci?.owner,
				row.ci?.brand,
				row.ci?.model,
				row.event_type,
				row.availability_percentage,
				row.mttr_seconds,
				row.mtbf_seconds,
				row.recovered_incidents,
				row.active_events,
				row.downtime_seconds,
				row.active_downtime_seconds,
				row.first_failure_at,
				row.last_failure_at,
			].map(csvValue).join(","),
		);
	});
	return lines.join("\n");
};

export const averageSeconds = (values: Array<number | null | undefined>): number | null => {
	const valid = values.filter((value): value is number => typeof value === "number");
	if (valid.length === 0) return null;
	return valid.reduce((sum, value) => sum + value, 0) / valid.length;
};
