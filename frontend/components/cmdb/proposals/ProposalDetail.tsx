import React from "react";
import { useProposalDetailQuery } from "../../../hooks/queries/useProposalsQuery";
import { ProposalActions } from "./ProposalActions";
import { ProposalDiffView } from "./ProposalDiffView";
import { ProposalAuditTimeline, AuditTimelineEntry } from "./ProposalAuditTimeline";

interface ProposalDetailProps {
  proposalId: string;
  canApprove: boolean;
  canViewAudit: boolean;
  auditEntries: AuditTimelineEntry[];
  auditLoading: boolean;
}

export const ProposalDetail: React.FC<ProposalDetailProps> = ({
  proposalId,
  canApprove,
  canViewAudit,
  auditEntries,
  auditLoading,
}) => {
  const { data, isLoading, error } = useProposalDetailQuery(proposalId);

  if (isLoading) {
    return (
      <div className="animate-pulse h-40 bg-neutral-900/40 rounded-xl" data-testid="proposal-detail-loading" />
    );
  }
  if (error || !data) {
    return (
      <div
        role="alert"
        data-testid="proposal-detail-error"
        className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-300"
      >
        Could not load proposal {proposalId}.
      </div>
    );
  }

  let manifestObj: Record<string, unknown> = {};
  try {
    manifestObj = data.manifest_json ? JSON.parse(data.manifest_json) : {};
  } catch {
    manifestObj = {};
  }

  return (
    <div data-testid="proposal-detail" className="flex flex-col gap-4">
      <header className="flex items-center justify-between gap-4 border-b border-white/5 pb-4">
        <div>
          <h2 className="text-lg font-black uppercase tracking-widest text-white">
            {data.id}
          </h2>
          <p className="text-xs text-neutral-400">
            Proposed by {data.proposed_by} ({data.proposed_role}) — v{data.version}, status{" "}
            <span className={data.status === "APPROVED" ? "text-emerald-400" : data.status === "REVOKED" ? "text-red-400" : "text-amber-400"}>
              {data.status}
            </span>
          </p>
        </div>
        <ProposalActions
          proposalId={data.id}
          version={data.version}
          ciId={data.ci_id}
          canApprove={canApprove}
          isApproved={data.status === "APPROVED"}
          isRevoked={data.status === "REVOKED"}
        />
      </header>

      <ProposalDiffView
        manifest={manifestObj}
        liveCi={null}
        liveCategories={[]}
        liveCiExists={false}
      />

      {canViewAudit && (
        <section data-testid="proposal-audit-section">
          <h3 className="text-xs uppercase tracking-widest text-neutral-400 mb-2">
            Audit Timeline
          </h3>
          <ProposalAuditTimeline entries={auditEntries} loading={auditLoading} />
        </section>
      )}
    </div>
  );
};