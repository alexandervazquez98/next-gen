// frontend/services/graphContract.ts — REQ-1, REQ-2
//
// Request builders for the CMDB LOD endpoints. The actual fetch is
// performed by ``fetchGraphOverview`` / ``fetchGraphDetail`` in
// ``frontend/services/api.ts`` (route ``/api/graph/overview`` and
// ``/api/graph/detail/{cluster_id}``); this module only builds the URL
// + query string and validates the caller-supplied inputs so the
// backend can never see malformed cluster_ids.
//
// Both builders are pure functions — they do not perform network I/O.
// Tests in ``frontend/__tests__/graphContract.test.ts`` assert the URL
// shape and that forbidden cluster_ids throw at build time.
//
// Run with ``npx tsc --noEmit`` for type-checking.

import type { DetailResponse, OverviewResponse } from "../types/graph";

/**
 * Query parameters accepted by ``GET /api/graph/overview``.
 *
 * The backend echoes sanitized filters back in the response payload —
 * CSV filters are split into string arrays. This interface is the
 * caller-facing shape; the backend translates it.
 */
export interface OverviewFilters {
  ci_type?: string | string[];
  location?: string | string[];
  status?: string | string[];
  text?: string;
  /** Pagination cursor returned by a previous response (REQ-5). */
  cursor?: string;
  /** Pagination override (1..1000). Defaults to 500 server-side. */
  limit?: number;
}

/**
 * Query parameters accepted by ``GET /api/graph/detail/{cluster_id}``.
 */
export interface DetailFilters extends Omit<OverviewFilters, "cursor"> {
  /** Pagination cursor (REQ-5). */
  cursor?: string;
  /**
   * Opt-in sensitive metadata gate (REQ-9). Server-side default is
   * ``false``; setting this to ``true`` is rejected unless the caller
   * has ``graph:aggregate_breakdown:read``.
   */
  sensitive?: "include" | "exclude";
}

/** Cluster ID wire regex — must match ``backend/contracts/cluster_id.py``. */
const CLUSTER_ID_RE = /^location:[A-Za-z0-9._-]{1,128}$/;

/**
 * Validate a cluster_id at build time so malformed values never reach
 * the backend. Throws an Error with a structured shape that the caller
 * can surface directly.
 */
function assertClusterId(clusterId: string): void {
  if (typeof clusterId !== "string" || clusterId === "") {
    throw new Error(
      JSON.stringify({
        error: "invalid_cluster_id",
        reason: "cluster_id is empty",
        cluster_id: String(clusterId),
      }),
    );
  }
  if (!CLUSTER_ID_RE.test(clusterId)) {
    throw new Error(
      JSON.stringify({
        error: "invalid_cluster_id",
        reason: "cluster_id must match '<axis>:<url-safe-key>'",
        cluster_id: clusterId,
      }),
    );
  }
}

/** Build the ``/api/graph/overview`` URL with the given filters. */
export function buildOverviewUrl(filters: OverviewFilters = {}): string {
  const params = new URLSearchParams();
  if (filters.ci_type !== undefined) {
    params.append("ci_type", toCsv(filters.ci_type));
  }
  if (filters.location !== undefined) {
    params.append("location", toCsv(filters.location));
  }
  if (filters.status !== undefined) {
    params.append("status", toCsv(filters.status));
  }
  if (filters.text !== undefined && filters.text !== "") {
    params.append("text", filters.text);
  }
  if (filters.cursor) {
    params.append("cursor", filters.cursor);
  }
  if (filters.limit !== undefined) {
    params.append("limit", String(filters.limit));
  }
  const qs = params.toString();
  return qs ? `/api/graph/overview?${qs}` : "/api/graph/overview";
}

/** Build the ``/api/graph/detail/{cluster_id}`` URL with the given filters. */
export function buildDetailUrl(clusterId: string, filters: DetailFilters = {}): string {
  assertClusterId(clusterId);
  const params = new URLSearchParams();
  if (filters.ci_type !== undefined) {
    params.append("ci_type", toCsv(filters.ci_type));
  }
  if (filters.location !== undefined) {
    params.append("location", toCsv(filters.location));
  }
  if (filters.status !== undefined) {
    params.append("status", toCsv(filters.status));
  }
  if (filters.text !== undefined && filters.text !== "") {
    params.append("text", filters.text);
  }
  if (filters.cursor) {
    params.append("cursor", filters.cursor);
  }
  if (filters.limit !== undefined) {
    params.append("limit", String(filters.limit));
  }
  if (filters.sensitive !== undefined) {
    params.append("sensitive", filters.sensitive);
  }
  const qs = params.toString();
  const base = `/api/graph/detail/${encodeURIComponent(clusterId)}`;
  return qs ? `${base}?${qs}` : base;
}

/**
 * Type guards — the wire body returned by the backend MUST satisfy the
 * DTO shape. Use these after a fetch to narrow the response before
 * handing it to React state.
 */
export function isOverviewResponse(value: unknown): value is OverviewResponse {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    v.axis === "location" &&
    typeof v.generated_at === "string" &&
    typeof v.revision === "string" &&
    Array.isArray(v.clusters) &&
    Array.isArray(v.inter_cluster_links)
  );
}

export function isDetailResponse(value: unknown): value is DetailResponse {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    (v.cluster === null || typeof v.cluster === "object") &&
    typeof v.generated_at === "string" &&
    typeof v.revision === "string" &&
    Array.isArray(v.nodes) &&
    Array.isArray(v.links) &&
    Array.isArray(v.boundary_stubs)
  );
}

/** Join an array-or-scalar into a comma-separated string. */
function toCsv(value: string | string[]): string {
  return Array.isArray(value) ? value.join(",") : value;
}
