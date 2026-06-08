import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { useAuth } from "../context/AuthContext";

type AuditSort = "created_at_desc" | "created_at_asc";

interface AuditEvent {
	id: number;
	event_type: string;
	outcome: string;
	actor_username: string | null;
	target_type: string | null;
	target_id: string | null;
	target_label: string | null;
	source: string | null;
	ip_address: string | null;
	user_agent: string | null;
	context: Record<string, unknown> | null;
	created_at: string;
}

interface AuditEventsResponse {
	items: AuditEvent[];
	total: number;
	page: number;
	page_size: number;
}

interface Filters {
	actor: string;
	eventType: string;
	outcome: string;
	startTime: string;
	endTime: string;
	page: number;
	pageSize: number;
	sort: AuditSort;
}

const EMPTY = { actor: "", eventType: "", outcome: "", startTime: "", endTime: "", pageSize: 25, sort: "created_at_desc" as AuditSort };
const OUTCOMES = ["SUCCESS", "DENIED", "VALIDATION_FAILURE", "FAILURE"] as const;
const EVENT_TYPES = [
	"LOGIN_SUCCESS","LOGIN_FAILURE","LOGOUT","CI_CREATE_OR_UPDATE","CI_DELETE","CI_UPDATE_METADATA","USER_CREATE","USER_UPDATE","USER_DELETE","USER_PASSWORD_RESET","ROLE_CREATE","ROLE_UPDATE","ROLE_DELETE","SYSTEM_CONFIG_UPDATE",
];
const PAGE_SIZES = [10, 25, 50, 100];
const PLACEHOLDER = "Not captured";
const normalizeIso = (value: string) => {
	if (!value) return;
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) throw new Error("Invalid datetime");
	return date.toISOString();
};
const formatCell = (value: string | null | undefined) => (value?.trim() ? value : PLACEHOLDER);
const formatTs = (value: string) => {
	const date = new Date(value);
	return Number.isNaN(date.getTime()) ? PLACEHOLDER : date.toLocaleString();
};
const targetLabel = (event: AuditEvent) => event.target_label || event.target_id || PLACEHOLDER;
const contextText = (event: AuditEvent) => {
	const pieces = [
		event.ip_address ? `IP ${event.ip_address}` : null,
		event.user_agent ? `UA ${event.user_agent}` : null,
		event.context && Object.keys(event.context).length > 0
			? `Context ${JSON.stringify(event.context)}`
			: null,
	].filter(Boolean);
	return pieces.length ? pieces.join(" | ") : PLACEHOLDER;
};

const AuditLogPage: React.FC = () => {
	const { hasPermission } = useAuth();
	const canViewAudit = hasPermission("AUDIT_VIEW") || hasPermission("ADMIN");
	const [draft, setDraft] = useState({ ...EMPTY });
	const [filters, setFilters] = useState<Filters>({ ...EMPTY, page: 1, pageSize: EMPTY.pageSize, sort: EMPTY.sort });
	const [events, setEvents] = useState<AuditEvent[]>([]);
	const [total, setTotal] = useState(0);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState("");
	const [accessDenied, setAccessDenied] = useState(false);
	const totalPages = useMemo(() => Math.max(1, Math.ceil(total / filters.pageSize || 1)), [total, filters.pageSize]);

	const fetchEvents = useCallback(async () => {
		setLoading(true);
		setError("");
		setAccessDenied(false);
		try {
			const params = new URLSearchParams({ page: String(filters.page), page_size: String(Math.min(filters.pageSize, 100)), sort: filters.sort });
			if (filters.actor.trim()) params.set("actor", filters.actor.trim());
			if (filters.eventType) params.set("event_type", filters.eventType);
			if (filters.outcome) params.set("outcome", filters.outcome);
			const st = normalizeIso(filters.startTime); if (st) params.set("start_time", st);
			const et = normalizeIso(filters.endTime); if (et) params.set("end_time", et);
			const response = await api.get<AuditEventsResponse>(`/audit/events?${params.toString()}`);
			setEvents(response.items);
			setTotal(response.total);
		} catch (err) {
			if ((err as { status?: number } | undefined)?.status === 403) return setAccessDenied(true);
			setError(err instanceof Error ? err.message : "Unable to load audit log events");
		} finally {
			setLoading(false);
		}
	}, [filters]);

	useEffect(() => {
		if (canViewAudit) fetchEvents();
	}, [canViewAudit, fetchEvents]);

	if (!canViewAudit) return <div className="p-8 text-neutral-400">Access denied. Required: AUDIT_VIEW</div>;
	if (accessDenied) return <div className="p-8 text-red-400">Access denied by permission policy</div>;

	return (
		<div className="p-6 lg:p-8 space-y-6">
			<header className="flex items-center justify-between gap-4 flex-wrap">
				<div>
					<h1 className="text-2xl font-black uppercase tracking-tight text-white">Audit Log</h1>
					<p className="text-neutral-500 text-xs uppercase tracking-wide mt-1">Filterable audit events and outcomes.</p>
				</div>
				{loading && <span className="text-xs text-brand-400">Loading audit events…</span>}
			</header>

			<section className="glass border border-white/10 rounded-2xl p-4 space-y-4">
				<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
					{[
						["Actor", "actor", draft.actor, null as string[] | null],
						["Event type", "eventType", draft.eventType, EVENT_TYPES],
						["Outcome", "outcome", draft.outcome, OUTCOMES],
						["Start time", "startTime", draft.startTime, null as string[] | null, "datetime-local"],
						["End time", "endTime", draft.endTime, null as string[] | null, "datetime-local"],
					].map(([label, key, value, options, type]) => (
						<label key={label as string} className="text-xs space-y-1">
							<span className="text-neutral-400 uppercase">{label}</span>
							{Array.isArray(options) ? (
								<select
									value={draft[key as keyof typeof draft] as string}
									onChange={e => setDraft(p => ({ ...p, [key]: e.target.value }))}
									className="w-full bg-black/40 border border-white/10 px-3 py-2 rounded text-sm"
								>
									<option value="">Any</option>
									{(options as string[]).map(v => <option key={v} value={v}>{v}</option>)}
								</select>
							) : (
								<input
									type={(type as string) || "text"}
									value={value as string}
									onChange={e => setDraft(p => ({ ...p, [key]: e.target.value }))}
									className="w-full bg-black/40 border border-white/10 px-3 py-2 rounded text-sm"
								/>
							)}
						</label>
					))}
				</div>
				<div className="grid grid-cols-1 md:grid-cols-3 gap-3">
					<label className="text-xs space-y-1">
						<span className="text-neutral-400 uppercase">Page size</span>
						<select
							value={draft.pageSize}
							onChange={e => setDraft(p => ({ ...p, pageSize: Number(e.target.value) }))}
							className="w-full bg-black/40 border border-white/10 px-3 py-2 rounded text-sm"
						>
							{PAGE_SIZES.map(size => <option key={size} value={size}>{size}</option>)}
						</select>
					</label>
					<label className="text-xs space-y-1">
						<span className="text-neutral-400 uppercase">Sort</span>
						<select
							value={draft.sort}
							onChange={e => setDraft(p => ({ ...p, sort: e.target.value as AuditSort }))}
							className="w-full bg-black/40 border border-white/10 px-3 py-2 rounded text-sm"
						>
							<option value="created_at_desc">Newest first</option>
							<option value="created_at_asc">Oldest first</option>
						</select>
					</label>
					<button
						type="button"
						className="self-end bg-brand-600 hover:bg-brand-500 text-white px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider"
						onClick={() => setFilters({ ...draft, page: 1 })}
					>
						Apply filters
					</button>
				</div>
			</section>

			{error && <p className="text-red-400 text-sm">{error}</p>}
			<section className="glass border border-white/10 rounded-2xl overflow-auto">
				<table className="w-full text-left text-sm text-neutral-300">
					<thead className="bg-white/5 text-xs uppercase tracking-wide text-neutral-400">
						<tr>
							<th className="p-4">Timestamp</th><th className="p-4">Actor</th><th className="p-4">Event Type</th><th className="p-4">Target</th><th className="p-4">Outcome</th><th className="p-4">IP / Context</th><th className="p-4">Source</th>
						</tr>
					</thead>
					<tbody>
						{events.length === 0 && !loading ? (
						<tr><td className="p-6 text-center text-neutral-500" colSpan={7}>No audit events found.</td></tr>
						) : (
							events.map(event => (
								<tr key={event.id} className="border-b border-white/5">
									<td className="p-4 text-xs">{formatTs(event.created_at)}</td>
									<td className="p-4">{formatCell(event.actor_username)}</td>
									<td className="p-4">{formatCell(event.event_type)}</td>
									<td className="p-4">{targetLabel(event)} ({formatCell(event.target_type)})</td>
									<td className="p-4 uppercase">{formatCell(event.outcome)}</td>
									<td className="p-4 text-xs break-all">{contextText(event)}</td>
									<td className="p-4">{formatCell(event.source)}</td>
								</tr>
							))
						)}
					</tbody>
				</table>
			</section>
			<div className="flex items-center justify-end gap-3">
				<button type="button" disabled={filters.page <= 1} onClick={() => setFilters(p => ({ ...p, page: Math.max(1, p.page - 1) }))} className="px-4 py-2 rounded-lg border border-white/10 text-xs disabled:opacity-40">Previous</button>
				<span className="text-xs text-neutral-400">Page {filters.page} / {totalPages}</span>
				<button type="button" disabled={filters.page >= totalPages} onClick={() => setFilters(p => ({ ...p, page: Math.min(totalPages, p.page + 1) }))} className="px-4 py-2 rounded-lg border border-white/10 text-xs disabled:opacity-40">Next</button>
			</div>
		</div>
	);
};

export default AuditLogPage;
