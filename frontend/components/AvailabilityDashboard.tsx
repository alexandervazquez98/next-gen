import type React from "react";
import { Fragment, useMemo, useState } from "react";
import { useAvailabilityReportQuery } from "../hooks/queries/useAvailabilityReportQuery";
import { useAvailabilitySnmpNoResponseQuery } from "../hooks/queries/useAvailabilitySnmpNoResponseQuery";
import type {
	AvailabilityReportRow,
	AvailabilitySnmpNoResponseResponse,
	SnmpCoverageSummary,
} from "../types";
import {
	averageSeconds,
	availabilityRowsToCsv,
	filterAvailabilityRows,
	formatDurationSeconds,
	getAvailabilityCategory,
} from "../utils/availabilityReport";

const formatPercent = (value?: number | null) =>
	value == null ? "—" : `${value.toFixed(2)}%`;

const formatSnmpFunctional = (summary?: SnmpCoverageSummary | null) => {
	if (!summary) return "—";
	return `${summary.functional_ci}/${summary.total_ci_with_snmp} (${formatPercent(summary.functional_percentage)})`;
};

const formatSnmpNoResponse = (summary?: SnmpCoverageSummary | null) => {
	if (!summary) return "—";
	return `${summary.no_response_ci} CIs / ${summary.no_response_event_count} events`;
};

const metadataEntries = (row: AvailabilityReportRow) => {
	const metadata = row.ci?.metadata ?? {};
	return Object.entries(metadata).map(([key, value]) => [
		key,
		typeof value === "object" && value !== null
			? JSON.stringify(value)
			: String(value ?? ""),
	]);
};

const downloadCsv = (csv: string) => {
	const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.href = url;
	link.download = "availability-report.csv";
	document.body.appendChild(link);
	link.click();
	link.remove();
	URL.revokeObjectURL(url);
};

const AvailabilityDashboard: React.FC = () => {
	const { data, isLoading, error } = useAvailabilityReportQuery();
	const rows = data?.rows ?? [];
	const [searchTerm, setSearchTerm] = useState("");
	const [category, setCategory] = useState("ALL");
	const [expandedRowId, setExpandedRowId] = useState<string | null>(null);
	const [isSnmpDrilldownOpen, setIsSnmpDrilldownOpen] = useState(false);
	const snmpDrilldown = useAvailabilitySnmpNoResponseQuery({
		enabled: isSnmpDrilldownOpen,
	});

	const categories = useMemo(
		() => Array.from(new Set(rows.map(getAvailabilityCategory))).sort(),
		[rows],
	);
	const filteredRows = useMemo(
		() => filterAvailabilityRows(rows, searchTerm, category),
		[rows, searchTerm, category],
	);
	const averageMttr = averageSeconds(filteredRows.map((row) => row.mttr_seconds));
	const averageMtbf = averageSeconds(filteredRows.map((row) => row.mtbf_seconds));
	const activeEvents = filteredRows.reduce((sum, row) => sum + row.active_events, 0);
	const snmpCoverage = data?.snmp_coverage;
	const worstAvailability = filteredRows.reduce<number | null>((worst, row) => {
		if (row.availability_percentage == null) return worst;
		return worst == null ? row.availability_percentage : Math.min(worst, row.availability_percentage);
	}, null);

	if (isLoading) {
		return <div className="rounded-2xl border border-white/5 bg-surface-900 p-8 text-neutral-400">Loading availability metrics...</div>;
	}

	if (error) {
		return <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-8 text-red-200">Could not load availability metrics. The metrics graph section remains available.</div>;
	}

	return (
		<section className="space-y-6" aria-label="Availability analytics dashboard">
			<div className="flex flex-col gap-4 rounded-2xl border border-white/5 bg-surface-900 p-6 md:flex-row md:items-end md:justify-between">
				<div>
					<p className="text-xs font-bold uppercase tracking-widest text-brand-400">Availability</p>
					<h2 className="text-2xl font-black uppercase tracking-tight text-white">Availability MTTR/MTBF</h2>
					<p className="mt-1 text-sm text-neutral-500">Report window {data?.window_start ? new Date(data.window_start).toLocaleDateString() : "—"} → {data?.window_end ? new Date(data.window_end).toLocaleDateString() : "—"}</p>
				</div>
				<button
					type="button"
					onClick={() => downloadCsv(availabilityRowsToCsv(filteredRows))}
					className="rounded-lg bg-brand-600 px-4 py-2 text-xs font-bold uppercase tracking-widest text-white transition-colors hover:bg-brand-500 disabled:opacity-40"
					disabled={filteredRows.length === 0}
				>
					Export CSV
				</button>
			</div>

			<div className="grid grid-cols-1 gap-4 md:grid-cols-3 xl:grid-cols-6">
				<SummaryCard label="Average MTTR" value={formatDurationSeconds(averageMttr)} />
				<SummaryCard label="Average MTBF" value={formatDurationSeconds(averageMtbf)} />
				<SummaryCard label="Active events" value={String(activeEvents)} />
				<SummaryCard label="Worst availability" value={formatPercent(worstAvailability)} />
				<SummaryCard label="SNMP functional" value={formatSnmpFunctional(snmpCoverage)} />
				<SummaryCard
					label="SNMP no-response"
					value={formatSnmpNoResponse(snmpCoverage)}
					actionLabel={isSnmpDrilldownOpen ? "Hide affected CIs" : "Review affected CIs"}
					onAction={() => setIsSnmpDrilldownOpen((current) => !current)}
				/>
			</div>

			{isSnmpDrilldownOpen && (
				<SnmpNoResponseDrilldown
					data={snmpDrilldown.data}
					isLoading={snmpDrilldown.isLoading}
					error={snmpDrilldown.error}
				/>
			)}

			<div className="rounded-2xl border border-white/5 bg-surface-900 p-5">
				<div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-[1fr_240px]">
					<label className="block">
						<span className="mb-2 block text-xs font-bold uppercase tracking-widest text-neutral-500">Search availability</span>
						<input
							role="searchbox"
							aria-label="Search availability rows"
							value={searchTerm}
							onChange={(event) => setSearchTerm(event.target.value)}
							placeholder="Search any represented CI field..."
							className="w-full rounded-lg border border-white/10 bg-black/40 px-4 py-3 text-sm text-white outline-none transition-colors placeholder:text-neutral-600 focus:border-brand-500"
						/>
					</label>
					<label className="block">
						<span className="mb-2 block text-xs font-bold uppercase tracking-widest text-neutral-500">Category</span>
						<select
							aria-label="Category filter"
							value={category}
							onChange={(event) => setCategory(event.target.value)}
							className="w-full rounded-lg border border-white/10 bg-black/40 px-4 py-3 text-sm text-white outline-none transition-colors focus:border-brand-500"
						>
							<option value="ALL">ALL</option>
							{categories.map((option) => (
								<option key={option} value={option}>{option}</option>
							))}
						</select>
					</label>
				</div>

				{rows.length === 0 ? (
					<div className="rounded-xl border border-dashed border-white/10 p-10 text-center text-neutral-500">No availability incidents are present for this report window.</div>
				) : filteredRows.length === 0 ? (
					<div className="rounded-xl border border-dashed border-white/10 p-10 text-center text-neutral-500">No rows match the current search and category filters.</div>
				) : (
					<div className="overflow-x-auto">
						<table className="w-full min-w-[920px] text-left text-sm">
							<thead className="text-xs uppercase tracking-widest text-neutral-500">
								<tr className="border-b border-white/10">
									<th className="p-3">CI</th>
									<th className="p-3">Category</th>
									<th className="p-3">Event Type</th>
									<th className="p-3">Availability</th>
									<th className="p-3">MTTR</th>
									<th className="p-3">MTBF</th>
									<th className="p-3">Recovered</th>
									<th className="p-3">Active</th>
									<th className="p-3">Details</th>
								</tr>
							</thead>
							<tbody className="divide-y divide-white/5">
								{filteredRows.map((row) => {
									const rowId = `${row.ci_id}:${row.event_type}`;
									const isExpanded = expandedRowId === rowId;
									const name = row.ci?.label || row.ci_name || row.ci_id;
									return (
										<Fragment key={rowId}>
											<tr key={rowId} className="text-neutral-300">
												<td className="p-3"><p className="font-bold text-white">{name}</p><p className="font-mono text-xs text-neutral-500">{row.ci_id}</p></td>
												<td className="p-3">{getAvailabilityCategory(row)}</td>
												<td className="p-3">{row.event_type}</td>
												<td className="p-3">{formatPercent(row.availability_percentage)}</td>
												<td className="p-3">{formatDurationSeconds(row.mttr_seconds)}</td>
												<td className="p-3">{formatDurationSeconds(row.mtbf_seconds)}</td>
												<td className="p-3">{row.recovered_incidents}</td>
												<td className="p-3">{row.active_events}</td>
												<td className="p-3"><button type="button" aria-label={`Expand ${name}`} onClick={() => setExpandedRowId(isExpanded ? null : rowId)} className="rounded-lg border border-white/10 px-3 py-1 text-xs font-bold uppercase text-neutral-300 hover:border-brand-500 hover:text-white">{isExpanded ? "Hide" : "Expand"}</button></td>
											</tr>
											{isExpanded && (
												<tr key={`${rowId}:details`} className="bg-black/20 text-xs text-neutral-400">
													<td colSpan={9} className="p-4">
														<div className="grid grid-cols-1 gap-3 md:grid-cols-3">
															<Detail label="IP" value={row.ci?.ip} />
															<Detail label="Owner" value={row.ci?.owner} />
															<Detail label="Brand" value={row.ci?.brand} />
															<Detail label="Model" value={row.ci?.model} />
															<Detail label="First Failure" value={row.first_failure_at} />
															<Detail label="Last Failure" value={row.last_failure_at} />
															{metadataEntries(row).map(([key, value]) => <Detail key={key} label={key} value={value} />)}
														</div>
													</td>
												</tr>
											)}
										</Fragment>
									);
								})}
							</tbody>
						</table>
					</div>
				)}
			</div>
		</section>
	);
};

const SnmpNoResponseDrilldown: React.FC<{
	data?: AvailabilitySnmpNoResponseResponse;
	isLoading: boolean;
	error: unknown;
}> = ({ data, isLoading, error }) => (
	<div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-5" aria-label="SNMP no-response affected CIs">
		<div className="mb-4 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
			<div>
				<p className="text-xs font-bold uppercase tracking-widest text-amber-300">SNMP no-response drilldown</p>
				<h3 className="text-lg font-black uppercase tracking-tight text-white">Affected CIs</h3>
				<p className="text-sm text-amber-100/70">Active or acknowledged SNMP collection failures with no response.</p>
			</div>
			{data && (
				<p className="text-xs text-amber-100/70">
					{data.summary.total_ci_with_no_response} CIs / {data.summary.total_events_with_no_response} events
				</p>
			)}
		</div>

		{isLoading ? (
			<div className="rounded-xl border border-white/10 bg-black/20 p-4 text-sm text-amber-100">Loading affected CIs...</div>
		) : error ? (
			<div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-100">Could not load SNMP no-response details.</div>
		) : !data || data.rows.length === 0 ? (
			<div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-amber-100/70">No active SNMP no-response CIs were found.</div>
		) : (
			<div className="overflow-x-auto">
				<table className="w-full min-w-[760px] text-left text-sm">
					<thead className="text-xs uppercase tracking-widest text-amber-100/60">
						<tr className="border-b border-white/10">
							<th className="p-3">CI</th>
							<th className="p-3">Category</th>
							<th className="p-3">Status</th>
							<th className="p-3">IP</th>
							<th className="p-3">Owner</th>
							<th className="p-3">Events</th>
							<th className="p-3">Latest</th>
						</tr>
					</thead>
					<tbody className="divide-y divide-white/10">
						{data.rows.map((row) => (
							<tr key={row.ci_id} className="text-amber-50/90">
								<td className="p-3">
									<p className="font-bold text-white">{row.ci_name || row.ci_id}</p>
									<p className="font-mono text-xs text-amber-100/50">{row.ci_id}</p>
									{row.events[0]?.message && <p className="mt-1 text-xs text-amber-100/70">{row.events[0].message}</p>}
								</td>
								<td className="p-3">{row.category || "—"}</td>
								<td className="p-3">{row.status || "—"}</td>
								<td className="p-3 font-mono text-xs">{row.ip || "—"}</td>
								<td className="p-3">{row.owner || "—"}</td>
								<td className="p-3">{row.event_count}</td>
								<td className="p-3">{row.latest_event_at ? new Date(row.latest_event_at).toLocaleString() : "—"}</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
		)}
	</div>
);

const SummaryCard: React.FC<{
	label: string;
	value: string;
	actionLabel?: string;
	onAction?: () => void;
}> = ({ label, value, actionLabel, onAction }) => (
	<div className="rounded-xl border border-white/5 bg-surface-900 p-5">
		<p className="text-xs font-bold uppercase tracking-widest text-neutral-500">{label}</p>
		<p className="mt-2 text-2xl font-black text-white">{value}</p>
		{actionLabel && onAction && (
			<button
				type="button"
				onClick={onAction}
				className="mt-3 rounded-lg border border-white/10 px-3 py-1 text-xs font-bold uppercase text-neutral-300 hover:border-brand-500 hover:text-white"
			>
				{actionLabel}
			</button>
		)}
	</div>
);

const Detail: React.FC<{ label: string; value?: string | number | null }> = ({ label, value }) => (
	<div className="rounded-lg border border-white/5 bg-white/[0.03] p-3">
		<p className="font-bold uppercase tracking-widest text-neutral-500">{label}</p>
		<p className="mt-1 break-words text-neutral-200">{value || "—"}</p>
	</div>
);

export default AvailabilityDashboard;
