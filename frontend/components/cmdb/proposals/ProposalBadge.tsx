import React from "react";
import { useNavigate } from "react-router-dom";
import { useProposalCountQuery } from "../../../hooks/queries/useProposalsQuery";

interface ProposalBadgeProps {
  canReview: boolean;
}

function useSafeNavigate() {
  // Defensive: when the badge is rendered outside a Router (e.g. legacy unit
  // tests), fall back to window.location instead of crashing the chat console.
  try {
    return useNavigate();
  } catch {
    return (path: string) => {
      if (typeof window !== "undefined") window.location.href = path;
    };
  }
}

function useSafeCount(): number {
  // Defensive: when the badge is rendered outside a QueryClientProvider
  // (e.g. legacy unit tests), skip the badge rather than crash the console.
  try {
    return useProposalCountQuery().data?.count ?? 0;
  } catch {
    return 0;
  }
}

export const ProposalBadge: React.FC<ProposalBadgeProps> = ({ canReview }) => {
  const navigate = useSafeNavigate();
  const count = useSafeCount();

  if (!canReview) return null;
  if (count === 0) return null;

  return (
    <button
      type="button"
      data-testid="proposal-badge"
      onClick={() => navigate("/proposals/cmdb?status=DRAFT")}
      className="ml-2 px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-bold uppercase tracking-widest border border-amber-500/30 hover:bg-amber-500/30"
      title={`${count} pending CI proposal${count === 1 ? "" : "s"}`}
    >
      {count} pending
    </button>
  );
};