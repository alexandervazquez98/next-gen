import { api } from "./api";

export type CIProposalStatus = "DRAFT" | "APPROVED" | "REVOKED";

export interface ProposalListResponse {
  rows: ProposalRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProposalRow {
  id: string;
  status: CIProposalStatus;
  version: number;
  manifest_json: string;
  applied_manifest_json: string | null;
  proposed_by: string;
  proposed_role: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  resulted_ci_id: string | null;
  revoke_reason: string | null;
  proposed_category: string | null;
  ci_id: string | null;
}

export type ProposalDetailResponse = ProposalRow;

export interface ProposalDraftCountResponse {
  count: number;
}

export interface ProposalFilters {
  status?: CIProposalStatus;
  category?: string;
  proposed_by?: string;
  created_from?: string;
  created_to?: string;
  page?: number;
  page_size?: number;
}

function toQueryString(filters: ProposalFilters = {}): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") {
      params.append(k, String(v));
    }
  });
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const fetchProposals = (
  filters: ProposalFilters = {},
  signal?: AbortSignal,
): Promise<ProposalListResponse> =>
  api.get<ProposalListResponse>(
    `/cmdb/proposals${toQueryString(filters)}`,
    signal ? { signal } : {},
  );

export const fetchProposal = (
  id: string,
  signal?: AbortSignal,
): Promise<ProposalDetailResponse> =>
  api.get<ProposalDetailResponse>(
    `/cmdb/proposals/${encodeURIComponent(id)}`,
    signal ? { signal } : {},
  );

export const fetchProposalDraftCount = (
  signal?: AbortSignal,
): Promise<ProposalDraftCountResponse> =>
  api.get<ProposalDraftCountResponse>(
    "/cmdb/proposals/count?status=DRAFT",
    signal ? { signal } : {},
  );

export const approveProposal = (
  id: string,
  body: { version: number; expected_category?: string },
): Promise<{ proposal_id: string; status: "APPROVED"; version: number; resulted_ci_id: string }> =>
  api.post(`/cmdb/proposals/${encodeURIComponent(id)}/approve`, body);

export const revokeProposal = (
  id: string,
  body: { version: number; reason?: string },
): Promise<{ proposal_id: string; status: "REVOKED"; version: number }> =>
  api.post(`/cmdb/proposals/${encodeURIComponent(id)}/revoke`, body);