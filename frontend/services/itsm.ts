import { api } from "./api";
import type {
  ServiceCatalogCreatePayload,
  ServiceCatalogResponse,
  ServiceCatalogUpdatePayload,
  TicketFolioCreatePayload,
  TicketFolioResponse,
  TicketFolioStatus,
  TicketFolioUpdatePayload,
} from "../types/itsm";

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

export interface TicketFolioListOptions {
  status?: TicketFolioStatus;
  service_catalog_id?: string;
  archived?: boolean;
  signal?: AbortSignal;
}

export const listTicketFolios = ({ signal, ...params }: TicketFolioListOptions = {}) =>
  api.get<TicketFolioResponse[]>("/itsm/tickets", { signal, params });

export const createTicketFolio = (payload: TicketFolioCreatePayload) =>
  api.post<TicketFolioResponse>("/itsm/tickets", payload);

export const updateTicketFolio = (ticketId: string, payload: TicketFolioUpdatePayload) =>
  api.put<TicketFolioResponse>(`/itsm/tickets/${encodeURIComponent(ticketId)}`, payload);

export const transitionTicketFolio = (
  ticketId: string,
  nextStatus: TicketFolioStatus,
  closedReason?: string,
) =>
  api.post<TicketFolioResponse>(`/itsm/tickets/${encodeURIComponent(ticketId)}/transition`, {
    next_status: nextStatus,
    ...(closedReason ? { closed_reason: closedReason } : {}),
  });
