/**
 * physicalLinks.ts — frontend service for /api/cmdb/physical-links.
 *
 * Slice 2/4 of feat-444 (closes #444). Mirrors the `queryResources.ts` /
 * `cmdbProposals.ts` pattern so the React Query hook layer (and the
 * `PhysicalLinkPreview` showcase component) can call a small, type-safe
 * surface against the backend CRUD API added in slice 2.
 *
 * The wire shapes match the backend `PhysicalLinkResponse` schema in
 * `backend/schemas/physical_link.py` byte-for-byte. The `endpoints` field is
 * projected as `[string, string]` (a JSON list) to match the backend wire
 * response and the frontend `PhysicalLink.endpoints` DTO in
 * `frontend/types.ts`.
 */

import { api } from "./api";
import type { PhysicalLink, PhysicalLinkType } from "../types";

/**
 * Wire alias. The backend uses `"UP" | "DOWN" | "UNKNOWN" | "PLANNED"` —
 * keep this in sync with `frontend/types.ts` `PhysicalLink.status`.
 */
export type PhysicalLinkStatus = PhysicalLink["status"];

export interface PhysicalLinkFilters {
  ci_id?: string;
  type?: PhysicalLinkType;
  status?: PhysicalLinkStatus;
  limit?: number;
  offset?: number;
}

export interface PhysicalLinkCreatePayload {
  id: string;
  type: PhysicalLinkType;
  /** Two-element tuple of CI ids — mirrors backend `tuple[str, str]`. */
  endpoints: [string, string];
  status?: PhysicalLinkStatus;
  capacity_gbps?: number | null;
  install_date?: string | null;
}

export interface PhysicalLinkUpdateStatusPayload {
  status: PhysicalLinkStatus;
}

function toQueryString(filters: PhysicalLinkFilters = {}): string {
  const params = new URLSearchParams();
  if (filters.ci_id) params.set("ci_id", filters.ci_id);
  if (filters.type) params.set("type", filters.type);
  if (filters.status) params.set("status", filters.status);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const fetchPhysicalLinks = (
  filters: PhysicalLinkFilters = {},
  signal?: AbortSignal,
): Promise<PhysicalLink[]> =>
  api.get<PhysicalLink[]>(
    `/cmdb/physical-links${toQueryString(filters)}`,
    signal ? { signal } : {},
  );

export const fetchPhysicalLink = (id: string, signal?: AbortSignal): Promise<PhysicalLink> =>
  api.get<PhysicalLink>(`/cmdb/physical-links/${encodeURIComponent(id)}`, signal ? { signal } : {});

export const createPhysicalLink = (payload: PhysicalLinkCreatePayload): Promise<PhysicalLink> =>
  api.post<PhysicalLink>(`/cmdb/physical-links`, payload);

export const updatePhysicalLinkStatus = async (
  id: string,
  status: PhysicalLinkStatus,
): Promise<PhysicalLink> => {
  // The ``api`` helper does not yet expose PATCH, so this slice uses a raw
  // fetch with credentials:include to keep parity with the rest of the
  // service file. The auth refresh flow (when the cookie rotates) is
  // intentionally not reused here — the operator's status-update action
  // is a manual click and a stale token will surface as a 401 in the
  // component, which is fine for v1.
  const response = await fetch(`${"/api"}/cmdb/physical-links/${encodeURIComponent(id)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
    credentials: "include",
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      if (data && typeof data.detail === "string") message = data.detail;
    } catch {
      // body was not JSON — fall through with statusText
    }
    throw new Error(message || `HTTP ${response.status}`);
  }
  return (await response.json()) as PhysicalLink;
};
