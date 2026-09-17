import React from "react";
import type { ProposalRow } from "../../../services/cmdbProposals";

interface ProposalFiltersProps {
  status: string;
  category: string;
  proposedBy: string;
  onChange: (_next: { status: string; category: string; proposed_by: string }) => void;
}

export const ProposalFilters: React.FC<ProposalFiltersProps> = ({
  status,
  category,
  proposedBy,
  onChange,
}) => {
  return (
    <div
      data-testid="proposal-filters"
      className="flex flex-wrap items-center gap-3 p-3 bg-neutral-900/40 border border-white/5 rounded-xl"
    >
      <label className="text-[10px] uppercase tracking-widest text-neutral-400">
        Status
        <select
          aria-label="Filter by status"
          value={status}
          onChange={(e) => onChange({ status: e.target.value, category, proposed_by: proposedBy })}
          className="ml-2 bg-neutral-950 text-neutral-200 border border-white/10 rounded px-2 py-1 text-xs"
        >
          <option value="">All</option>
          <option value="DRAFT">DRAFT</option>
          <option value="APPROVED">APPROVED</option>
          <option value="REVOKED">REVOKED</option>
        </select>
      </label>
      <label className="text-[10px] uppercase tracking-widest text-neutral-400">
        Category
        <input
          aria-label="Filter by category"
          value={category}
          onChange={(e) => onChange({ status, category: e.target.value, proposed_by: proposedBy })}
          className="ml-2 bg-neutral-950 text-neutral-200 border border-white/10 rounded px-2 py-1 text-xs"
          placeholder="Router"
        />
      </label>
      <label className="text-[10px] uppercase tracking-widest text-neutral-400">
        Proposer
        <input
          aria-label="Filter by proposer"
          value={proposedBy}
          onChange={(e) => onChange({ status, category, proposed_by: e.target.value })}
          className="ml-2 bg-neutral-950 text-neutral-200 border border-white/10 rounded px-2 py-1 text-xs"
          placeholder="ai-bot"
        />
      </label>
    </div>
  );
};

interface ProposalListProps {
  rows: ProposalRow[];
  loading: boolean;
  error: Error | null;
  filters: { status: string; category: string; proposed_by: string };
  onFiltersChange: (_next: { status: string; category: string; proposed_by: string }) => void;
}

export const ProposalList: React.FC<ProposalListProps> = ({
  rows,
  loading,
  error,
  filters,
  onFiltersChange,
}) => {
  if (loading) {
    return (
      <div data-testid="proposal-list-skeleton" className="grid gap-2 animate-pulse">
        {Array.from({ length: 4 }).map((_, idx) => (
          <div key={idx} className="h-12 bg-neutral-900/60 border border-white/5 rounded-lg" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        data-testid="proposal-list-error"
        className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-300"
      >
        <p className="text-sm">Failed to load proposals.</p>
        <p className="text-xs text-red-400 mt-1">{error.message}</p>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div
        data-testid="proposal-list-empty"
        className="p-6 text-center text-neutral-400 border border-white/5 rounded-xl bg-neutral-900/40"
      >
        <p className="text-sm">No proposals match the current filters.</p>
        <p className="text-xs mt-1">
          Try clearing filters or check back after the next agent submit.
        </p>
      </div>
    );
  }

  return (
    <div data-testid="proposal-list" className="flex flex-col gap-3">
      <ProposalFilters
        status={filters.status}
        category={filters.category}
        proposedBy={filters.proposed_by}
        onChange={onFiltersChange}
      />
      <table className="w-full text-sm">
        <thead className="text-[10px] uppercase tracking-widest text-neutral-500 border-b border-white/5">
          <tr>
            <th className="text-left py-2 px-3">ID</th>
            <th className="text-left py-2 px-3">Proposer</th>
            <th className="text-left py-2 px-3">Category</th>
            <th className="text-left py-2 px-3">Status</th>
            <th className="text-left py-2 px-3">Version</th>
            <th className="text-left py-2 px-3">Created</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              data-testid={`proposal-row-${row.id}`}
              className="border-b border-white/5 hover:bg-white/5"
            >
              <td className="py-2 px-3 font-mono text-xs">{row.id}</td>
              <td className="py-2 px-3">{row.proposed_by}</td>
              <td className="py-2 px-3">{row.proposed_category ?? row.ci_id ?? "—"}</td>
              <td className="py-2 px-3">
                <span
                  className={
                    row.status === "DRAFT"
                      ? "text-amber-400"
                      : row.status === "APPROVED"
                        ? "text-emerald-400"
                        : "text-red-400"
                  }
                >
                  {row.status}
                </span>
              </td>
              <td className="py-2 px-3 font-mono">{row.version}</td>
              <td className="py-2 px-3 text-xs text-neutral-400">{row.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
