// frontend/services/itsm.ts — PR5 (WU 8) Service Management surface.
//
// Endpoint paths are stable per design.md §"Approved PR1 boundary adjustment":
// paths stay under /itsm/... and /users/...; only user-facing copy changes.

import { api } from "./api";
import type {
  ActiveUser,
  ImportValidationFailure,
  ServiceCatalogCreatePayload,
  ServiceCatalogResponse,
  ServiceCatalogUpdatePayload,
  TicketFolioCreatePayload,
  TicketFolioResponse,
  TicketFolioStatus,
  TicketFolioUpdatePayload,
} from "../types/itsm";

// ------------------------------------------------------------
// Service catalog
// ------------------------------------------------------------

export interface ServiceCatalogListOptions {
  signal?: AbortSignal;
}

export const listServiceCatalog = ({ signal }: ServiceCatalogListOptions = {}) =>
  api.get<ServiceCatalogResponse[]>("/itsm/service-catalog", { signal });

export const createServiceCatalog = (payload: ServiceCatalogCreatePayload) =>
  api.post<ServiceCatalogResponse>("/itsm/service-catalog", payload);

export const updateServiceCatalog = (serviceId: string, payload: ServiceCatalogUpdatePayload) =>
  api.put<ServiceCatalogResponse>(
    `/itsm/service-catalog/${encodeURIComponent(serviceId)}`,
    payload,
  );

export const deactivateServiceCatalog = (serviceId: string) =>
  api.post<ServiceCatalogResponse>(
    `/itsm/service-catalog/${encodeURIComponent(serviceId)}/deactivate`,
    {},
  );

// Catalog template + import (PR4 WU6 surface).
export const downloadCatalogTemplate = () => api.download("/itsm/service-catalog/template");

export const importCatalogWorkbook = async (file: File): Promise<unknown> => {
  const form = new FormData();
  form.append("file", file);
  return api.post("/itsm/service-catalog/import", form);
};

// ------------------------------------------------------------
// Ticket folio
// ------------------------------------------------------------

export interface TicketFolioListOptions {
  status?: TicketFolioStatus;
  service_catalog_id?: string;
  archived?: boolean;
  signal?: AbortSignal;
}

export const listTicketFolios = (options: TicketFolioListOptions = {}) => {
  const { signal, status, service_catalog_id, archived } = options;
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (service_catalog_id) params.set("service_catalog_id", service_catalog_id);
  if (archived !== undefined) params.set("archived", String(archived));
  const query = params.toString();
  const endpoint = query ? `/itsm/tickets?${query}` : "/itsm/tickets";
  return api.get<TicketFolioResponse[]>(endpoint, { signal });
};

export const createTicketFolio = (payload: TicketFolioCreatePayload) =>
  api.post<TicketFolioResponse>("/itsm/tickets", payload);

export const updateTicketFolio = (ticketId: number, payload: TicketFolioUpdatePayload) =>
  api.put<TicketFolioResponse>(`/itsm/tickets/${encodeURIComponent(String(ticketId))}`, payload);

export const transitionTicketFolio = (
  ticketId: number,
  nextStatus: TicketFolioStatus,
  closedReason?: string,
) =>
  api.post<TicketFolioResponse>(
    `/itsm/tickets/${encodeURIComponent(String(ticketId))}/transition`,
    {
      next_status: nextStatus,
      ...(closedReason ? { closed_reason: closedReason } : {}),
    },
  );

// Ticket template + import (PR4 WU7 surface).
export const downloadTicketTemplate = () => api.download("/itsm/tickets/template");

export const importTicketWorkbook = async (file: File): Promise<unknown> => {
  const form = new FormData();
  form.append("file", file);
  return api.post("/itsm/tickets/import", form);
};

// ------------------------------------------------------------
// User lifecycle — REQ-04 (active user lookup), REQ-05 (deactivate)
// ------------------------------------------------------------

export const listActiveUsers = async (): Promise<ActiveUser[]> => {
  const all = await api.get<ActiveUser[]>("/users/");
  // Backend exposes `disabled` (true = inactive). Filter for active users only.
  return all.filter((u) => u.disabled === false && u.is_active !== false);
};

export const deactivateUser = (username: string) =>
  api.post<void>(`/users/${encodeURIComponent(username)}/deactivate`, {});

// ------------------------------------------------------------
// Helpers
// ------------------------------------------------------------

// Type guard for the structured validation payload returned by the import routes.
// Exported so page tests can stub it cleanly; the implementation does not
// touch state and is safe to call directly.
export function isImportValidationFailure(value: unknown): value is ImportValidationFailure {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.status === "validation_failed" &&
    typeof candidate.message === "string" &&
    Array.isArray(candidate.errors) &&
    typeof candidate.error_count === "number"
  );
}

export function extractImportError(err: unknown): ImportValidationFailure | null {
  if (!err || typeof err !== "object") return null;
  const detail = (err as { detail?: unknown }).detail;
  if (isImportValidationFailure(detail)) return detail;
  if (isImportValidationFailure(err)) return err;
  return null;
}

export function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object") {
    const anyErr = err as { message?: string; detail?: unknown };
    if (typeof anyErr.message === "string" && anyErr.message) return anyErr.message;
    if (typeof anyErr.detail === "string") return anyErr.detail;
    if (anyErr.detail && typeof anyErr.detail === "object") {
      const inner = anyErr.detail as { message?: string };
      if (typeof inner.message === "string") return inner.message;
    }
  }
  return fallback;
}
