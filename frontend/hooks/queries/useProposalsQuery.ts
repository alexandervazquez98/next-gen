import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../../services/queryKeys";
import {
  approveProposal,
  fetchProposal,
  fetchProposalDraftCount,
  fetchProposals,
  ProposalFilters,
  revokeProposal,
} from "../../services/cmdbProposals";

export const useProposalsQuery = (filters: ProposalFilters = {}) =>
  useQuery({
    queryKey: queryKeys.cmdbProposals(filters),
    queryFn: ({ signal }) => fetchProposals(filters, signal),
    // The list is short-lived; reviewers re-open it to re-check status.
    refetchInterval: 15_000,
  });

export const useProposalDetailQuery = (id: string | undefined) =>
  useQuery({
    queryKey: queryKeys.cmdbProposalDetail(id ?? ""),
    queryFn: ({ signal }) => fetchProposal(id as string, signal),
    enabled: !!id,
  });

export const useProposalCountQuery = () =>
  useQuery({
    queryKey: queryKeys.cmdbProposalDraftCount(),
    queryFn: ({ signal }) => fetchProposalDraftCount(signal),
    refetchInterval: 5_000,
  });

function invalidateProposalRelatedQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["cmdb-proposals"] });
  queryClient.invalidateQueries({ queryKey: ["nodes"] });
  queryClient.invalidateQueries({ queryKey: ["graph-topology"] });
  queryClient.invalidateQueries({ queryKey: ["audit"] });
}

export const useApproveProposal = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      version,
      expected_category,
    }: {
      id: string;
      version: number;
      expected_category?: string;
    }) => approveProposal(id, { version, expected_category }),
    onSuccess: () => {
      invalidateProposalRelatedQueries(queryClient);
    },
  });
};

export const useRevokeProposal = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version, reason }: { id: string; version: number; reason?: string }) =>
      revokeProposal(id, { version, reason }),
    onSuccess: () => {
      invalidateProposalRelatedQueries(queryClient);
    },
  });
};
