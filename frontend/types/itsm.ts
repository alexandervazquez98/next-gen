export type TicketFolioStatus =
  | "open"
  | "in_progress"
  | "in_validation"
  | "resolved"
  | "closed";

export type TicketFolioType = "request" | "incident";

export interface ServiceCatalogBase {
  service_id: string;
  name: string;
  owner_team: string | null;
  category: string | null;
  tier: string | null;
  criticality: string | null;
  sla_target_minutes: number;
  active: boolean;
}

export interface ServiceCatalogResponse extends ServiceCatalogBase {
  created_at: string;
  updated_at: string;
  updated_by: string | null;
}

export interface ServiceCatalogCreatePayload {
  service_id: string;
  name: string;
  owner_team?: string | null;
  category?: string | null;
  tier?: string | null;
  criticality?: string | null;
  sla_target_minutes: number;
  active?: boolean;
}

export interface ServiceCatalogUpdatePayload {
  service_id?: string;
  name?: string;
  owner_team?: string | null;
  category?: string | null;
  tier?: string | null;
  criticality?: string | null;
  sla_target_minutes?: number;
  active?: boolean;
}

export interface TicketFolioResponse {
  ticket_id: string;
  type: TicketFolioType;
  title: string;
  description: string | null;
  service_catalog_id: string | null;
  status: TicketFolioStatus;
  closed_reason: string | null;
  created_at: string;
  updated_at: string;
  updated_by: string | null;
}

export interface TicketFolioCreatePayload {
  ticket_id: string;
  type: TicketFolioType;
  title: string;
  description?: string | null;
  service_catalog_id?: string | null;
  status?: TicketFolioStatus;
  closed_reason?: string | null;
}

export interface TicketFolioUpdatePayload {
  title?: string;
  description?: string | null;
  service_catalog_id?: string | null;
  status?: TicketFolioStatus;
  closed_reason?: string | null;
}
