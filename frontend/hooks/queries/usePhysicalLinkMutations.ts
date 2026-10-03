/**
 * usePhysicalLinkMutations.ts
 *
 * Slice 2/4 of feat-444 (closes #444): React Query mutations for the
 * PhysicalLink CRUD API. Two surfaces:
 *
 *   - ``useCreatePhysicalLink`` — POST /api/cmdb/physical-links with the
 *     supplied payload. On success, invalidates the list cache so any
 *     consumer re-fetches and sees the new row.
 *   - ``useUpdatePhysicalLinkStatus`` — PATCH /api/cmdb/physical-links/{id}/
 *     status with `{ status }`. On success, invalidates BOTH the list cache
 *     and the detail cache so the table re-renders AND the detail panel
 *     reflects the new status.
 *
 * Cache keys come from ``frontend/services/queryKeys.ts`` (append-only).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createPhysicalLink,
  updatePhysicalLinkStatus,
  type PhysicalLinkCreatePayload,
  type PhysicalLinkStatus,
} from "../../services/physicalLinks";

function invalidatePhysicalLinkCaches(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["cmdb-physical-links"] });
}

export const useCreatePhysicalLink = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PhysicalLinkCreatePayload) => createPhysicalLink(payload),
    onSuccess: () => {
      invalidatePhysicalLinkCaches(queryClient);
    },
  });
};

export const useUpdatePhysicalLinkStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: PhysicalLinkStatus }) =>
      updatePhysicalLinkStatus(id, status),
    onSuccess: () => {
      invalidatePhysicalLinkCaches(queryClient);
    },
  });
};
