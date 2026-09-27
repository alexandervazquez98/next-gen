// frontend/services/graphLod.ts — #392 PR4
//
// Fetch helpers for the CMDB graph LOD endpoints. Wraps the URL
// builders in ``graphContract.ts`` with the ``api.get`` client so
// callers can use a single import for both URL composition and
// network I/O.
//
// The overview endpoint returns the location-cluster summary
// (REQ-1); the detail endpoint returns the bounded subgraph for
// a single cluster (REQ-2). Both consume the value objects shipped
// in v1.18.0 backend runtime slice.

import { api } from "./api";
import type { DetailResponse, OverviewResponse } from "../types/graph";
import {
  buildDetailUrl,
  buildOverviewUrl,
  isDetailResponse,
  isOverviewResponse,
  type DetailFilters,
  type OverviewFilters,
} from "./graphContract";

export type { DetailFilters, OverviewFilters };

/**
 * Fetch the LOD overview payload for the current principal.
 *
 * Filters are forwarded verbatim to the URL builder. The response is
 * narrowed via ``isOverviewResponse`` so callers see a typed
 * ``OverviewResponse`` rather than ``unknown``.
 */
export async function fetchGraphOverview(
  filters: OverviewFilters = {},
  signal?: AbortSignal,
): Promise<OverviewResponse> {
  // graphContract URL builders include the "/api" prefix; api.get prepends
  // API_BASE="/api" again, so strip the leading "/api" before delegating.
  const url = buildOverviewUrl(filters).replace(/^\/api/, "");
  const body = await api.get<unknown>(url, signal ? { signal } : {});
  if (!isOverviewResponse(body)) {
    throw new Error("fetchGraphOverview: response did not match OverviewResponse shape");
  }
  return body;
}

/**
 * Fetch the bounded subgraph for a single cluster.
 *
 * Cluster ID is validated at URL-build time by ``buildDetailUrl``; a
 * malformed cluster_id throws synchronously before any network call.
 */
export async function fetchGraphDetail(
  clusterId: string,
  filters: DetailFilters = {},
  signal?: AbortSignal,
): Promise<DetailResponse> {
  // See fetchGraphOverview for the /api prefix stripping rationale.
  const url = buildDetailUrl(clusterId, filters).replace(/^\/api/, "");
  const body = await api.get<unknown>(url, signal ? { signal } : {});
  if (!isDetailResponse(body)) {
    throw new Error(
      `fetchGraphDetail: response did not match DetailResponse shape for cluster_id=${clusterId}`,
    );
  }
  return body;
}
