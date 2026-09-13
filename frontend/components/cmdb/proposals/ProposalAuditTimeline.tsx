import React from "react";

export interface AuditTimelineEntry {
  event_type: "CI_PROPOSAL_CREATE" | "CI_PROPOSAL_APPROVE" | "CI_PROPOSAL_REVOKE" | string;
  actor_username: string | null;
  actor_role: string | null;
  previous_state: string | null;
  next_state: string | null;
  version: number | null;
  created_at: string;
  reason?: string | null;
}

interface ProposalAuditTimelineProps {
  entries: AuditTimelineEntry[];
  loading: boolean;
}

const EVENT_COLORS: Record<string, string> = {
  CI_PROPOSAL_CREATE: "text-amber-400",
  CI_PROPOSAL_APPROVE: "text-emerald-400",
  CI_PROPOSAL_REVOKE: "text-red-400",
};

export const ProposalAuditTimeline: React.FC<ProposalAuditTimelineProps> = ({
  entries,
  loading,
}) => {
  if (loading) {
    return (
      <div data-testid="proposal-audit-loading" className="animate-pulse h-20 bg-neutral-900/40 rounded" />
    );
  }

  const sorted = [...entries].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );

  return (
    <ol
      data-testid="proposal-audit-timeline"
      className="flex flex-col gap-2"
    >
      {sorted.map((entry, idx) => (
        <li
          key={`${entry.event_type}-${entry.created_at}-${idx}`}
          className="border border-white/5 rounded-lg p-3 bg-neutral-900/40"
        >
          <div className="flex items-baseline gap-2">
            <span
              className={`text-xs font-black uppercase tracking-widest ${
                EVENT_COLORS[entry.event_type] ?? "text-neutral-300"
              }`}
            >
              {entry.event_type}
            </span>
            <span className="text-[10px] text-neutral-500">
              {entry.previous_state ?? "—"} → {entry.next_state ?? "—"} (v
              {entry.version ?? "?"})
            </span>
          </div>
          <p className="text-[10px] text-neutral-400 mt-1">
            by {entry.actor_username ?? "unknown"} ({entry.actor_role ?? "n/a"}) at{" "}
            {entry.created_at}
          </p>
          {entry.reason && (
            <p className="text-[10px] text-neutral-500 mt-1">reason: {entry.reason}</p>
          )}
        </li>
      ))}
    </ol>
  );
};