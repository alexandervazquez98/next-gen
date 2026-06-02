import { api } from "./api";
import type {
	AvailabilityReportResponse,
	EventDetail,
	EventSummary,
	GraphLink,
	GraphNode,
	MultiMetricHistoryResponse,
} from "../types";

export interface SystemStatus {
	cpu: number;
	ram: number;
	disk: number;
	neo4j: "CONNECTED" | "DISCONNECTED" | "UNKNOWN";
	collector: {
		status: string;
		last_run: string | null;
		stats: {
			cis_monitored: number;
			last_cycle_metrics_processed?: number;
			metrics_collected: number;
			metrics_failed: number;
			cycle_duration: number;
			jobs_per_min: number;
		};
	};
}

export interface OwnerRecord {
	name: string;
}

export interface CategoryRecord {
	name: string;
}

export interface GraphTopologyResponse {
	nodes: GraphNode[];
	links: GraphLink[];
}

export const fetchSystemStatus = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<SystemStatus>("/system/status", { signal });

export const fetchNodes = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<GraphNode[]>("/nodes", { signal });

export const fetchLinks = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<GraphLink[]>("/links", { signal });

export const fetchCategories = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<CategoryRecord[]>("/categories", { signal });

export const fetchActiveEvents = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<EventSummary[]>("/events?status=CONSOLE", { signal });

export interface FetchAvailabilityReportOptions {
	start?: string;
	end?: string;
	signal?: AbortSignal;
}

export const fetchAvailabilityReport = ({
	start,
	end,
	signal,
}: FetchAvailabilityReportOptions = {}) => {
	const params = new URLSearchParams();
	if (start) params.set("start", start);
	if (end) params.set("end", end);
	const query = params.toString();
	return api.get<AvailabilityReportResponse>(
		`/events/availability-report${query ? `?${query}` : ""}`,
		{ signal },
	);
};

export const fetchEventDetail = (
	eventId: string,
	{ signal }: { signal?: AbortSignal } = {},
) => api.get<EventDetail>(`/events/${eventId}`, { signal });

export const fetchRelatedEvents = (
	ciId: string,
	{ signal }: { signal?: AbortSignal } = {},
) => api.get<EventSummary[]>(`/events/related/${ciId}`, { signal });

type GraphFilterValue = string | string[];

export interface FetchGraphTopologyOptions {
	layer?: GraphFilterValue;
	location?: GraphFilterValue;
	owner?: GraphFilterValue;
	signal?: AbortSignal;
}

export const fetchGraphTopology = ({
	layer,
	location,
	owner,
	signal,
}: FetchGraphTopologyOptions = {}) => {
	const params = new URLSearchParams();
	const setFilterParam = (key: string, value?: GraphFilterValue) => {
		if (Array.isArray(value)) {
			const selected = value.filter(Boolean);
			if (selected.length > 0) params.set(key, selected.join(","));
			return;
		}
		if (value) params.set(key, value);
	};
	setFilterParam("layer", layer);
	setFilterParam("location", location);
	setFilterParam("owner", owner);
	const query = params.toString();
	return api.get<GraphTopologyResponse>(
		`/graph/full${query ? `?${query}` : ""}`,
		{
			signal,
		},
	);
};

export const fetchOwners = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<OwnerRecord[]>("/owners", { signal });

export const fetchNodesSearch = ({
	q,
	signal,
}: {
	q: string;
	signal?: AbortSignal;
}) =>
	api.get<GraphNode[]>(`/nodes/search?q=${encodeURIComponent(q)}`, { signal });

export interface FetchNodeMetricHistoryOptions {
	nodeId: string;
	metricId: string;
	hours?: number;
	startTime?: string;
	endTime?: string;
	limit?: number;
	signal?: AbortSignal;
}

export const fetchNodeMetricHistory = async (
	options: FetchNodeMetricHistoryOptions,
): Promise<Array<{ time: string; value: number | string }>> => {
	const {
		nodeId,
		metricId,
		hours,
		startTime,
		endTime,
		limit = 1000,
		signal,
	} = options;
	const params = new URLSearchParams();
	params.set("limit", String(limit));
	if (hours !== undefined) params.set("hours", String(hours));
	if (startTime) params.set("start_time", startTime);
	if (endTime) params.set("end_time", endTime);

	const url = `/metrics/${encodeURIComponent(nodeId)}/${encodeURIComponent(metricId)}/history?${params.toString()}`;
	return api.get<Array<{ time: string; value: number | string }>>(url, {
		signal,
	});
};

export interface FetchNodeMetricHistoryDaysOptions {
	nodeId: string;
	metricId: string;
	startTime?: string;
	endTime?: string;
	signal?: AbortSignal;
}

export const fetchNodeMetricHistoryDays = async ({
	nodeId,
	metricId,
	startTime,
	endTime,
	signal,
}: FetchNodeMetricHistoryDaysOptions): Promise<string[]> => {
	const params = new URLSearchParams();
	if (startTime) params.set("start_time", startTime);
	if (endTime) params.set("end_time", endTime);

	const query = params.toString();
	const url = `/metrics/${encodeURIComponent(nodeId)}/${encodeURIComponent(metricId)}/history-days${query ? `?${query}` : ""}`;
	return api.get<string[]>(url, { signal });
};

export interface FetchMetricsHistoryOptions {
	nodeIds: string[];
	metricId: string;
	hours?: number;
	startTime?: string;
	endTime?: string;
	limit?: number;
	signal?: AbortSignal;
}

export const fetchMetricsHistory = async (
	options: FetchMetricsHistoryOptions,
): Promise<MultiMetricHistoryResponse> => {
	const {
		nodeIds,
		metricId,
		hours,
		startTime,
		endTime,
		limit = 1000,
		signal,
	} = options;
	const params = new URLSearchParams();
	// Only set hours if provided (backend defaults to 24)
	if (hours !== undefined) params.set("hours", String(hours));
	if (startTime) params.set("start_time", startTime);
	if (endTime) params.set("end_time", endTime);
	params.set("limit", String(limit));
	params.set("node_ids", nodeIds.join(","));

	const url = `/metrics/${encodeURIComponent(metricId)}/history?${params.toString()}`;
	return api.get<MultiMetricHistoryResponse>(url, { signal });
};
