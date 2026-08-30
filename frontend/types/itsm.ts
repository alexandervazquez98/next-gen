// frontend/types/itsm.ts — PR5 (WU 8) contract alignment with backend
// `backend/models/itsm.py` and `backend/models/user.py`.
//
// REQ-01: numeric server-generated `ticket_id`; clients must not supply it.
// REQ-02: catalog typed `incident | service_request`; immutable by type.
// REQ-03: ticket/catalog compatibility enforced in UI.
// REQ-04: exactly one active assignee per ticket.
// REQ-05: user deactivation preserves historical ticket context.

export type TicketFolioStatus = "open" | "in_progress" | "in_validation" | "resolved" | "closed";

// Canonical ticket type — must match `models.itsm.TicketFolioType` exactly.
export type TicketFolioType = "incident" | "service_request";

// Canonical catalog service_type — must match `models.itsm.TicketFolioType`.
export type ServiceCatalogType = "incident" | "service_request";

// ------------------------------------------------------------
// Ticket folio — REQ-01, REQ-03, REQ-04, REQ-05
// ------------------------------------------------------------

export interface TicketFolioResponse {
  ticket_id: number;
  type: TicketFolioType;
  title: string;
  description: string | null;
  service_catalog_id: string | null;
  assignee_username: string | null;
  assignee_display_name: string | null;
  assignee_active_at_assignment: boolean | null;
  assignee_currently_active: boolean | null;
  status: TicketFolioStatus;
  archived: boolean;
  closed_reason: string | null;
  created_at: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

// Wire payload: backend rejects client-supplied `ticket_id` (REQ-01).
// `assignee_username` is required and exactly one (REQ-04).
export interface TicketFolioCreatePayload {
  type: TicketFolioType;
  title: string;
  description?: string | null;
  service_catalog_id: string;
  assignee_username: string;
}

export interface TicketFolioUpdatePayload {
  title?: string;
  description?: string | null;
  service_catalog_id?: string | null;
  status?: TicketFolioStatus;
  closed_reason?: string | null;
  archived?: boolean;
}

// ------------------------------------------------------------
// Service catalog — REQ-02, REQ-03
// ------------------------------------------------------------

export interface ServiceCatalogBase {
  service_id: string;
  name: string;
  owner_team: string | null;
  category: string | null;
  tier: string | null;
  criticality: string | null;
  sla_target_minutes: number;
  description: string;
  service_type: ServiceCatalogType;
  value_stream: string;
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
  description: string;
  service_type: ServiceCatalogType;
  value_stream: string;
  active?: boolean;
}

// Update path: `service_type` is immutable; backend strips it when unchanged.
// Including it is allowed only when value matches current persisted type.
export interface ServiceCatalogUpdatePayload {
  service_id?: string;
  name?: string;
  owner_team?: string | null;
  category?: string | null;
  tier?: string | null;
  criticality?: string | null;
  sla_target_minutes?: number;
  description?: string | null;
  service_type?: ServiceCatalogType;
  value_stream?: string;
  active?: boolean;
}

// ------------------------------------------------------------
// Assignee selector — REQ-04
// ------------------------------------------------------------

// Active user shape for the assignee selector. The backend `users/` list
// returns `disabled` (inverted from `is_active`); `disabled === false` is active.
export interface ActiveUser {
  username: string;
  disabled?: boolean;
  is_active?: boolean;
}

// ------------------------------------------------------------
// XLSX import error contract — REQ-06, REQ-07
// Must mirror `backend/services/itsm_imports/errors.py` exactly.
// ------------------------------------------------------------

export type ImportValidationStatus = "validation_failed" | "success";

export interface RowFieldError {
  row: number | null;
  field: string;
  code: string;
  reason: string;
}

export interface ImportValidationFailure {
  status: "validation_failed";
  message: string;
  errors: RowFieldError[];
  error_count: number;
}

// ------------------------------------------------------------
// Type guards
// ------------------------------------------------------------

export function isTicketFolioType(value: unknown): value is TicketFolioType {
  return value === "incident" || value === "service_request";
}

export function isServiceCatalogType(value: unknown): value is ServiceCatalogType {
  return value === "incident" || value === "service_request";
}