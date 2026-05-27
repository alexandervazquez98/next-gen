export const formatMetricValue = (
	value: string | number | null | undefined,
	unit?: string,
): string => {
	if (value === null || value === undefined || value === "") return "--";

	const numericValue = typeof value === "number" ? value : Number(value);
	if (unit === "ms" && Number.isFinite(numericValue)) {
		return numericValue.toFixed(2);
	}

	return String(value);
};
