/**
 * usePhysicalLinksQuery.ts
 *
 * Slice 2/4 of feat-444 (closes #444): React Query hooks for the
 * PhysicalLink CRUD API. Two surfaces:
 *
 *   - ``usePhysicalLinksQuery(filters)`` — list query against
 *     ``GET /api/cmdb/physical-links`` with optional ``ci_id`` / ``type`` /
 *     ``status`` filters.
 *   - ``usePhysicalLinkDetailQuery(id)`` — single-row query against
 *     ``GET /api/cmdb/physical-links/{id}``; disabled when id is undefined
 *     so a parent component can pass a possibly-empty id safely.
 *
 * Cache key shapes come from ``frontend/services/queryKeys.ts`` — append-only
 * additions to that registry (``physicalLinks`` / ``physicalLinkDetail``).
 *
 * The hooks sit on top of ``frontend/services/physicalLinks.ts``, which
 * mirrors the ``queryResources.ts`` / ``cmdbProposals.ts`` pattern: every
 * fetch goes through the shared ``api`` wrapper so 401s trigger the cookie
 * refresh flow uniformly with the rest of the app.
 */

import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../services/queryKeys";
import {
  fetchPhysicalLink,
  fetchPhysicalLinks,
  type PhysicalLinkFilters,
} from "../../services/physicalLinks";

export const usePhysicalLinksQuery = (filters: PhysicalLinkFilters = {}) =>
  useQuery({
    queryKey: queryKeys.physicalLinks(filters),
    queryFn: ({ signal }) => fetchPhysicalLinks(filters, signal),
  });

export const usePhysicalLinkDetailQuery = (id: string | undefined) =>
  useQuery({
    queryKey: queryKeys.physicalLinkDetail(id ?? ""),
    queryFn: ({ signal }) => fetchPhysicalLink(id as string, signal),
    enabled: !!id,
  });
