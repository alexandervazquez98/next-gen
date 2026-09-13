import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useProposalsQuery } from "../hooks/queries/useProposalsQuery";
import { ProposalList } from "../components/cmdb/proposals/ProposalList";
import { ProposalDetail } from "../components/cmdb/proposals/ProposalDetail";

interface ProposalsCmdbPageProps {
  detailMode?: boolean;
}

export const ProposalsCmdbPage: React.FC<ProposalsCmdbPageProps> = ({ detailMode }) => {
  const { hasPermission } = useAuth();
  const canApprove = hasPermission("CI_APPROVE_PROPOSAL");
  const canView = hasPermission("CI_VIEW");
  const canViewAudit = hasPermission("AUDIT_VIEW");

  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(
    () => ({
      status: searchParams.get("status") ?? "",
      category: searchParams.get("category") ?? "",
      proposed_by: searchParams.get("proposed_by") ?? "",
    }),
    [searchParams],
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const query = useProposalsQuery({
    status: (filters.status as "DRAFT" | "APPROVED" | "REVOKED" | undefined) || undefined,
    category: filters.category || undefined,
    proposed_by: filters.proposed_by || undefined,
    page_size: 50,
  });

  if (!canView) {
    return (
      <div className="p-6">
        <h1 className="text-xl font-bold mb-2">Access denied</h1>
        <p className="text-sm text-neutral-400">You need CI_VIEW to view CMDB proposals.</p>
      </div>
    );
  }

  const onFiltersChange = (next: { status: string; category: string; proposed_by: string }) => {
    const params = new URLSearchParams();
    Object.entries(next).forEach(([k, v]) => {
      if (v) params.set(k, v);
    });
    setSearchParams(params);
  };

  if (detailMode && selectedId) {
    return (
      <div className="p-6" data-testid="proposals-cmdb-detail">
        <button
          type="button"
          onClick={() => setSelectedId(null)}
          className="text-xs uppercase tracking-widest text-neutral-400 hover:text-white"
        >
          ← Back to list
        </button>
        <ProposalDetail
          proposalId={selectedId}
          canApprove={canApprove}
          canViewAudit={canViewAudit}
          auditEntries={[]}
          auditLoading={false}
        />
      </div>
    );
  }

  return (
    <div className="p-6" data-testid="proposals-cmdb-list">
      <header className="mb-4">
        <h1 className="text-2xl font-black uppercase tracking-widest text-white">CMDB Proposals</h1>
        <p className="text-sm text-neutral-400">AI-submitted CI manifests awaiting human review.</p>
      </header>
      <ProposalList
        rows={query.data?.rows ?? []}
        loading={query.isLoading}
        error={query.error}
        filters={filters}
        onFiltersChange={onFiltersChange}
      />
    </div>
  );
};

export default ProposalsCmdbPage;
