import { api } from "./api";
import type {
	AvailabilityReportResponse,
	AvailabilitySnmpNoResponseResponse,
	EventDetail,
	EventSummary,
	CategoryIconKey,
	GraphLink,
	GraphNode,
	MultiMetricHistoryResponse,
	TunnelHealthResponse,
} from "../types";

export interface DiskIoStatus {
	supported: boolean;
	read_bytes_total?: number | null;
	write_bytes_total?: number | null;
	read_bytes_per_sec?: number | null;
	write_bytes_per_sec?: number | null;
	busy_percentage?: number | null;
	sampled_at?: string | null;
}

export interface SystemStatus {
	cpu: number;
	ram: number;
	disk: number;
	disk_io?: DiskIoStatus | null;
	neo4j: "CONNECTED" | "DISCONNECTED" | "UNKNOWN";
	postgres?: "CONNECTED" | "DISCONNECTED" | "UNKNOWN";
	startup_time?: string | null;
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

export interface SystemStatusHistoryRow {
	recorded_at: string;
	cpu?: number | null;
	ram?: number | null;
	disk?: number | null;
	disk_io?: Pick<DiskIoStatus, "supported" | "read_bytes_per_sec" | "write_bytes_per_sec" | "busy_percentage"> | null;
	neo4j?: "CONNECTED" | "DISCONNECTED" | "UNKNOWN" | string | null;
	postgres?: "CONNECTED" | "DISCONNECTED" | "UNKNOWN" | string | null;
	collector: {
		status?: string | null;
		stats: {
			cis_monitored?: number | null;
			metrics_collected?: number | null;
			metrics_failed?: number | null;
			cycle_duration?: number | null;
			jobs_per_min?: number | null;
		};
	};
}

export interface SystemStatusHistoryResponse {
	generated_at: string;
	hours: number;
	limit: number;
	retention_days: number;
	snapshot_interval_seconds?: number;
	stale_threshold_seconds?: number;
	latest_recorded_at?: string | null;
	is_stale?: boolean;
	rows: SystemStatusHistoryRow[];
}

export interface OwnerRecord {
	name: string;
}

export interface CategoryRecord {
	name: string;
	icon_key?: CategoryIconKey | null;
}

export interface GraphTopologyResponse {
	nodes: GraphNode[];
	links: GraphLink[];
}

export const fetchSystemStatus = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<SystemStatus>("/system/status", { signal });

export interface FetchSystemStatusHistoryOptions {
	hours?: number;
	limit?: number;
	signal?: AbortSignal;
}

export const fetchSystemStatusHistory = ({
	hours = 168,
	limit = 24,
	signal,
}: FetchSystemStatusHistoryOptions = {}) => {
	const params = new URLSearchParams({ hours: String(hours), limit: String(limit) });
	return api.get<SystemStatusHistoryResponse>(`/system/status/history?${params.toString()}`, { signal });
};

export const fetchNodes = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<GraphNode[]>("/nodes", { signal });

export const fetchLinks = ({ signal }: { signal?: AbortSignal } = {}) =>
	api.get<GraphLink[]>("/links", { signal });

export const fetchTunnelHealth = (
	linkId: string,
	{ signal }: { signal?: AbortSignal } = {},
) => api.get<TunnelHealthResponse>(`/tunnels/${encodeURIComponent(linkId)}/health`, { signal });

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

export interface FetchSnmpNoResponseOptions {
	limit?: number;
	offset?: number;
	signal?: AbortSignal;
}

export const fetchAvailabilitySnmpNoResponse = ({
	limit = 25,
	offset = 0,
	signal,
}: FetchSnmpNoResponseOptions = {}) => {
	const params = new URLSearchParams();
	params.set("limit", String(limit));
	params.set("offset", String(offset));
	return api.get<AvailabilitySnmpNoResponseResponse>(
		`/events/availability-report/snmp-no-response?${params.toString()}`,
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
