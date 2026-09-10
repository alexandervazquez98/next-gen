// frontend/types/graph.ts — REQ-1, REQ-2, REQ-8, REQ-9
//
// TypeScript mirrors of the CMDB LOD Pydantic DTOs in
// ``backend/schemas/graph.py``. MUST stay byte-compatible with the
// backend DTOs; drift is caught by the parity gate in
// ``frontend/__tests__/parity.test.ts``.
//
// Conventions:
// - Snake_case (matches Python wire format, not TS idioms).
// - String literal unions for enums (NOT TS enums — keeps the wire
//   format plain).
// - Every DTO is exported as both an interface (for type-checking) and a
//   constant array of literal values (for runtime validation).

// ---------------------------------------------------------------------------
// REQ-1 / REQ-2 / REQ-9 — Aggregate disclosure + safe geo precision
// ---------------------------------------------------------------------------

export const SAFE_GEO_PRECISION_VALUES = ["city", "region", "none"] as const;
export type SafeGeoPrecision = (typeof SAFE_GEO_PRECISION_VALUES)[number];

export const AGGREGATE_POLICY_PERMISSION_REQUIRED =
    "graph:aggregate_breakdown:read" as const;

export interface AggregatePolicy {
    minimum_count: number; // >= 1
    permission_required: typeof AGGREGATE_POLICY_PERMISSION_REQUIRED;
    safe_geo_precision: SafeGeoPrecision;
}

// ---------------------------------------------------------------------------
// REQ-5 — Pagination
// ---------------------------------------------------------------------------

export interface Page {
    next_cursor: string | null;
    has_more: boolean;
}

// ---------------------------------------------------------------------------
// REQ-1 — Overview response
// ---------------------------------------------------------------------------

export interface OverviewCluster {
    cluster_id: string;
    display_label: string;
    visible_node_count: number;
    visible_link_count: number;
    aggregate_redacted: boolean;
    suppression_reason: string | null;
}

export interface InterClusterLink {
    from_cluster_id: string;
    to_cluster_id: string;
    visible_link_count: number;
    redacted: boolean;
}

export interface Legend {
    cards: string[];
}

export interface OverviewResponse {
    axis: "location";
    filters: Record<string, unknown>;
    generated_at: string; // RFC 3339 UTC
    revision: string; // opaque
    aggregate_policy: AggregatePolicy;
    clusters: OverviewCluster[];
    inter_cluster_links: InterClusterLink[];
    legend: Legend;
    page: Page;
}

// ---------------------------------------------------------------------------
// REQ-2 — Detail response
// ---------------------------------------------------------------------------

export interface DetailCluster {
    cluster_id: string;
    axis: "location";
    display_label: string;
    visible_node_count: number;
    visible_link_count: number;
}

export interface DetailNode {
    id: string;
    display_label: string;
    kind: string;
    ci_type: string;
    allowed_public_axes: string[];
}

export interface DetailLink {
    source_node_id: string;
    target_node_id: string;
    relationship: string;
}

export interface BoundaryStub {
    cluster_id: string;
    visible_link_count: number;
    redacted: boolean;
    redaction_reason: string | null;
}

export const SENSITIVE_SOURCE_VALUES = [
    "never",
    "principal_scope",
    "principal_with_permission",
] as const;
export type SensitiveSource = (typeof SENSITIVE_SOURCE_VALUES)[number];

export interface ProjectionFlags {
    show_sensitive_metadata: boolean; // ALWAYS false by default (REQ-9)
    sensitive_source: SensitiveSource;
}

export const EMPTY_REASON_VALUES = [
    "none",
    "no_visible_members",
    "hidden_absent",
    "unavailable",
] as const;
export type EmptyReason = (typeof EMPTY_REASON_VALUES)[number];

export interface DetailResponse {
    cluster: DetailCluster | null; // null for hidden/absent (REQ-7)
    filters: Record<string, unknown>;
    generated_at: string;
    revision: string;
    nodes: DetailNode[];
    links: DetailLink[];
    boundary_stubs: BoundaryStub[];
    projection_flags: ProjectionFlags;
    empty_reason: EmptyReason;
    page: Page;
}

// ---------------------------------------------------------------------------
// REQ-4 — cluster_id codec error body
// ---------------------------------------------------------------------------

export interface InvalidClusterIdErrorBody {
    error: "invalid_cluster_id";
    reason: string;
    cluster_id: string;
}

export interface AxisConflictErrorBody {
    error: "axis_conflict";
    reason: string;
}

export type GraphContractErrorBody =
    | InvalidClusterIdErrorBody
    | AxisConflictErrorBody
    | { error: "invalid_cursor" }
    | { error: "stale_cursor"; current_revision: string }
    | { error: "stale_cursor"; reason: "permission_changed" };

// ---------------------------------------------------------------------------
// REQ-8 — Search resolution vocabulary
// ---------------------------------------------------------------------------

export const SEARCH_VOCABULARY_VALUES = [
    "single_visible_cluster",
    "multiple_visible_clusters",
    "no_visible_cluster",
    "ambiguous",
] as const;
export type SearchVocabulary = (typeof SEARCH_VOCABULARY_VALUES)[number];

// ---------------------------------------------------------------------------
// REQ-4 / REQ-7 — Sanity constants for sensitive-field omission checks
// ---------------------------------------------------------------------------

/**
 * Field names that MUST NEVER appear on an overview response (REQ-9).
 * Used by the parity + omission tests as a single source of truth.
 */
export const OVERVIEW_FORBIDDEN_FIELDS: ReadonlyArray<string> = [
    "public_ip",
    "metadata",
    "geo_coordinates",
    "serial_number",
    "provider_account_id",
];

/**
 * Field names that MUST NEVER appear on a detail node (REQ-9 — same
 * sensitive fields as overview, plus internal-only keys).
 */
export const DETAIL_NODE_FORBIDDEN_FIELDS: ReadonlyArray<string> = [
    "public_ip",
    "metadata",
    "internal_metadata",
];
