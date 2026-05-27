const millisecondMetricIds = new Set(["icmp_latency_ms", "icmp_jitter_ms"]);

export const formatMetricValue = (
	value: string | number | null | undefined,
	unit?: string,
	metricName?: string,
): string => {
	if (value === null || value === undefined || value === "") return "--";

	const numericValue = typeof value === "number" ? value : Number(value);
	const isMillisecondMetric =
		unit === "ms" || (metricName ? millisecondMetricIds.has(metricName) : false);
	if (isMillisecondMetric && Number.isFinite(numericValue)) {
		return numericValue.toFixed(2);
	}

	return String(value);
};
