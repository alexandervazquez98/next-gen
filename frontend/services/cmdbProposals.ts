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
  // feat-489 Slice 1B: ``manifest_mode`` is "single" (chat / MCP) or
  // "bulk" (admin CSV import). ``ci_count`` is the number of CIs in the
  // manifest (always 1 for single, len(cis[]) for bulk).
  manifest_mode?: "single" | "bulk" | null;
  ci_count?: number | null;
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

export const fetchProposal = (id: string, signal?: AbortSignal): Promise<ProposalDetailResponse> =>
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

// ── bulk CSV import (feat-489 Slice 1B) ────────────────────────────────────────


export interface BulkValidationError {
  row: number;
  errors: string[];
}

export interface BulkValidationResponse {
  dry_run: true;
  cis_count: number;
  categories: string[];
  manifest: Record<string, unknown>;
}

export interface BulkImportResponse {
  proposal_id: string;
  status: "DRAFT";
  version: number;
  cis_count: number;
  manifest_mode: "bulk";
  created_at: string | null;
}

export interface BulkImportDenial {
  harness_result: {
    denied: true;
    status: "denied";
    reason: string;
    reason_code: "cooldown_active" | "bulk_threshold";
  };
}

export interface BulkImportError {
  reason:
    | "bulk_validation_failed"
    | "file_too_large"
    | "not_a_csv"
    | "too_many_rows"
    | "empty_csv"
    | "csv_parse_failed";
  errors?: BulkValidationError[];
  bytes?: number;
  max_bytes?: number;
  rows?: number;
  max_rows?: number;
  hint?: string;
  error?: string;
}

export const bulkValidateProposals = (
  file: File,
  defaultCategory?: string,
  defaultOwner?: string,
): Promise<BulkValidationResponse | BulkImportError> => {
  const form = new FormData();
  form.append("file", file);
  if (defaultCategory) form.append("default_category", defaultCategory);
  if (defaultOwner) form.append("default_owner", defaultOwner);
  return api.post<BulkValidationResponse | BulkImportError>(
    "/cmdb/proposals/bulk-validate",
    form,
    // multipart/form-data — let the browser set the boundary; do NOT
    // set Content-Type manually.
  );
};

export const bulkImportProposals = (
  file: File,
  defaultCategory?: string,
  defaultOwner?: string,
): Promise<BulkImportResponse | BulkImportDenial | BulkImportError> => {
  const form = new FormData();
  form.append("file", file);
  if (defaultCategory) form.append("default_category", defaultCategory);
  if (defaultOwner) form.append("default_owner", defaultOwner);
  return api.post<BulkImportResponse | BulkImportDenial | BulkImportError>(
    "/cmdb/proposals/bulk-import",
    form,
  );
};
