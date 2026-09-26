# CMDB Graph Overview & Detail Contracts Specification

## Purpose

Define the wire-authoritative DTO contracts for `GET /graph/overview` and `GET /graph/detail/{cluster_id}` introduced by issue #390. This slice owns field shapes, codec rules, pagination/revision semantics, hidden/absent equivalence, visible-only search resolution vocabulary, and aggregate disclosure rules. Runtime query behavior, route handlers, and consumer migration live in #391 / #392 / #393. Runtime behavior invariants are pinned by the canonical `cmdb-graph-level-of-detail` spec; this spec ratifies the wire shape and must not contradict that spec.

## Requirements

### Requirement: Overview response DTO contract

The system MUST define an overview response shape as a typed Pydantic model with a mirrored TypeScript interface. The top-level object MUST contain exactly these fields:

| Field | Type | Notes |
|---|---|---|
| `axis` | string literal `"location"` | First-slice axis only. |
| `filters` | object | Echoed back, sanitized; CSV filters split into string arrays. |
| `generated_at` | string | RFC 3339 UTC timestamp. |
| `revision` | string | Opaque, visibility-scoped (see Revision requirement). |
| `aggregate_policy` | object | `{ minimum_count: int>=1, permission_required: string, safe_geo_precision: enum{city,region,none} }`. |
| `clusters[]` | array | Each: `{ cluster_id, display_label, visible_node_count, visible_link_count, aggregate_redacted: bool, suppression_reason?: string }`. |
| `inter_cluster_links[]` | array | Each: `{ from_cluster_id, to_cluster_id, visible_link_count, redacted: bool }`. |
| `legend` | object | Safe summary cards metadata only; no per-node data. |
| `page` | object | `{ next_cursor?: string, has_more: bool }`. |

The overview response MUST NOT include raw `public_ip`, raw internal `metadata` objects, exact geo coordinates, serial numbers, provider account identifiers, MAC addresses, or external DNS names.

#### Scenario: Well-formed overview response with multiple clusters
- GIVEN an authenticated principal with multiple visible location clusters,
- WHEN `GET /graph/overview` is called,
- THEN the response conforms to the field table above,
- AND every `cluster_id` is parseable by the cluster_id codec,
- AND `generated_at` is RFC 3339 UTC.

#### Scenario: No visible clusters
- GIVEN a principal whose `allowed_locations` is empty,
- WHEN `GET /graph/overview` is called,
- THEN `clusters` and `inter_cluster_links` are empty arrays,
- AND `page.has_more` is false.

#### Scenario: Single-cluster environment
- GIVEN exactly one visible location cluster,
- WHEN overview is built,
- THEN `clusters[]` length is 1,
- AND `inter_cluster_links[]` is empty,
- AND `page.has_more` is false.

#### Scenario: Hidden clusters present but redacted
- GIVEN hidden clusters exist outside the caller's scope,
- WHEN overview aggregates are computed,
- THEN hidden clusters MUST NOT appear in `clusters[]` or `inter_cluster_links[]`,
- AND aggregate counts over visible clusters MUST be unaffected by hidden cluster size.

#### Scenario: Low-cardinality bucket is redacted
- GIVEN a visible bucket with fewer than `aggregate_policy.minimum_count` records,
- WHEN the overview payload is built,
- THEN the bucket value is replaced with `redacted: true` and `redaction_reason: "low_cardinality"`,
- AND the exact count is not exposed.

#### Scenario: Geographic precision is truncated
- GIVEN a cluster with fewer than `aggregate_policy.minimum_count` visible nodes,
- WHEN `legend.geo` or aggregate geo summary is built,
- THEN the precision MUST be `safe_geo_precision`,
- AND raw endpoint coordinates MUST NOT appear.

### Requirement: Detail response DTO contract

The system MUST define a detail response shape for `GET /graph/detail/{cluster_id}`. The top-level object MUST contain exactly these fields:

| Field | Type | Notes |
|---|---|---|
| `cluster` | object \| null | Nullable for non-enumerating hidden/absent (REQ-7). Shape: `{ cluster_id, axis, display_label, visible_node_count, visible_link_count }`. |
| `filters` | object | Echoed back, sanitized. |
| `generated_at` | string | RFC 3339 UTC. |
| `revision` | string | Opaque, visibility-scoped. |
| `nodes[]` | array | Each: `{ id, display_label, kind, ci_type, allowed_public_axes: string[] }`. No raw `public_ip`, no internal `metadata` object. |
| `links[]` | array | Each: `{ source_node_id, target_node_id, relationship }`. No extra fields beyond what `/graph/full` already returns. |
| `boundary_stubs[]` | array | Optional, max 1 per adjacent cluster. Each: `{ cluster_id, visible_link_count }`. |
| `projection_flags` | object | `{ show_sensitive_metadata: bool, sensitive_source: enum{never, principal_scope, principal_with_permission} }`. |
| `empty_reason` | enum \| null | One of: `none`, `no_visible_members`, `hidden_absent`, `unavailable`. |
| `page` | object | `{ next_cursor?: string, has_more: bool }`. |

The detail response MUST apply the existing `/graph/full` projection policy to node/link fields; any stronger redaction is out of scope for #390.

#### Scenario: Detail with visible nodes
- GIVEN a visible cluster with N visible nodes,
- WHEN `GET /graph/detail/{cluster_id}` is called,
- THEN `cluster` is non-null and contains the cluster fields,
- AND `nodes[]` contains N entries,
- AND `links[]` contains only internal links within the cluster.

#### Scenario: Detail with zero visible nodes but cluster visible
- GIVEN a visible cluster whose committed filters hide all visible members,
- WHEN detail is fetched,
- THEN `cluster` is non-null,
- AND `nodes[]` and `links[]` are empty,
- AND `empty_reason` is `no_visible_members`.

#### Scenario: Hidden cluster returns 200 with `unavailable`
- GIVEN a cluster outside the caller's scope OR a nonexistent cluster_id,
- WHEN detail is fetched,
- THEN HTTP status is 200,
- AND `cluster` is null, `nodes`/`links`/`boundary_stubs` are empty arrays,
- AND `empty_reason` is `unavailable`.

#### Scenario: Detail with boundary stubs
- GIVEN a visible cluster with internal links plus visible external endpoints,
- WHEN detail is built,
- THEN `boundary_stubs[]` contains at most one entry per adjacent cluster,
- AND each stub exposes only `cluster_id` and `visible_link_count` (no detail).

### Requirement: `/graph/full` compatibility

The DTO contracts MUST NOT alter `/graph/full`. The system MUST add a snapshot test that captures the current `/graph/full` `{nodes, links}` response and asserts byte-equality against the frozen shape. Any drift MUST cause a hard test failure before #391 ships.

#### Scenario: `/graph/full` returns identical shape
- GIVEN a frozen pre-#390 `/graph/full` snapshot,
- WHEN `/graph/full` is called against the same fixture graph,
- THEN the response MUST match the snapshot byte-for-byte.

#### Scenario: No new fields added
- GIVEN the existing `/graph/full` node/link field set,
- WHEN DTOs are introduced,
- THEN no field MAY be added to the `/graph/full` response.

#### Scenario: No fields removed
- GIVEN the existing `/graph/full` node/link field set,
- WHEN DTOs are introduced,
- THEN no field MAY be removed from the `/graph/full` response.

#### Scenario: Ordering preserved
- GIVEN a fixture with stable node/link ordering,
- WHEN `/graph/full` is called repeatedly,
- THEN the ordering MUST be preserved across calls.

### Requirement: cluster_id codec

The system MUST define a `cluster_id` codec with these rules:

- Format: `<axis>:<url-safe-key>`.
- First-slice accepted `axis` value: `location` only.
- `location:<key>`: `key` is the lowercased, URL-safe location label, percent-encoded only when needed.
- Reserved sentinel: `location:__unassigned__` for nodes lacking location metadata.
- `key` MUST be non-empty after trimming; MUST NOT contain `/`; case-insensitive on match; case-preserving on display.
- A conflicting `axis` query parameter MUST be rejected with 400 before any authorization-sensitive lookup.
- Malformed `cluster_id` MUST yield 400 with structured error `{ error: "invalid_cluster_id", reason: string, cluster_id: string }`. The error MUST NOT leak cluster metadata.

#### Scenario: Parse a valid location id
- GIVEN `cluster_id="location:dc-1"`,
- WHEN the codec parses,
- THEN `axis="location"` and `key="dc-1"` are returned,
- AND the original display label `dc-1` is preserved for rendering.

#### Scenario: Parse `__unassigned__`
- GIVEN `cluster_id="location:__unassigned__"`,
- WHEN the codec parses,
- THEN `axis="location"` and `key="__unassigned__"` are returned,
- AND the sentinel is treated as a valid visible cluster key.

#### Scenario: Reject malformed id with 400 (no metadata leak)
- GIVEN `cluster_id="foo bar"` or `cluster_id=""` or `cluster_id=":"`,
- WHEN detail is fetched,
- THEN HTTP status is 400,
- AND the error body is `{ error: "invalid_cluster_id", reason: ..., cluster_id: ... }`,
- AND no cluster metadata (label, count, geo) is present in the error response.

#### Scenario: Reject conflicting axis query param
- GIVEN `cluster_id="location:dc-1"` and `?axis=tenant`,
- WHEN detail is fetched,
- THEN HTTP status is 400 with `error: "axis_conflict"`,
- AND no authorization-sensitive lookup is performed.

#### Scenario: Normalize case variants identically
- GIVEN `cluster_id="location:DC-1"` and `cluster_id="location:dc-1"`,
- WHEN both are parsed and matched against the same cluster,
- THEN they MUST resolve to the same cluster,
- AND display label preserves the canonical case.

### Requirement: Pagination, cursor, and limit

The system MUST define pagination semantics:

- `limit` query param: default 500, min 1, max 1000. Omitted limit uses 500.
- Cursor: opaque base64url string bound to `(cluster_id, filters, revision)`. Server tracks next-page state internally.
- Node ordering: `(ci_type, id)`.
- Link ordering: `(source_node_id, target_node_id, relationship)`.
- Invalid/expired cursor: 400 with `{ error: "invalid_cursor" }`.
- Stale cursor (revision changed): 409 with `{ error: "stale_cursor", current_revision: string }`.
- Overview cluster list paginates only when visible cluster count exceeds 200; otherwise `page.has_more=false`.

#### Scenario: First page request
- GIVEN a cluster with >500 visible nodes and no prior cursor,
- WHEN detail is fetched,
- THEN the first 500 nodes are returned ordered by `(ci_type, id)`,
- AND `page.next_cursor` is set, `page.has_more` is true.

#### Scenario: Follow next_cursor
- GIVEN a prior response with `next_cursor="abc"`,
- WHEN detail is fetched with `cursor=abc`,
- THEN the next page is returned in deterministic order,
- AND `page.has_more` reflects whether more pages remain.

#### Scenario: Explicit limit
- GIVEN `limit=100`,
- WHEN detail is fetched,
- THEN at most 100 nodes and the links incident to those nodes are returned,
- AND `page.next_cursor` reflects the truncated page.

#### Scenario: Invalid cursor → 400
- GIVEN `cursor="not-base64url-!"`,
- WHEN detail is fetched,
- THEN HTTP status is 400 with `{ error: "invalid_cursor" }`,
- AND no authorization-sensitive lookup is performed.

#### Scenario: Stale cursor → 409
- GIVEN a cursor bound to revision `rev-A` and current revision is `rev-B`,
- WHEN detail is fetched with the stale cursor,
- THEN HTTP status is 409 with `{ error: "stale_cursor", current_revision: "rev-B" }`.

#### Scenario: Large cluster paginates
- GIVEN a cluster with 1500 visible nodes,
- WHEN overview is built,
- THEN `page.has_more` is true once visible cluster count > 200,
- AND detail paginates via `next_cursor` across multiple pages.

### Requirement: Revision / cache invalidation semantics

The system MUST define `revision` as an opaque, deterministic, visibility-scoped string. It MUST change if and only if the caller's visible topology changes — i.e., nodes enter or leave the caller's scope, or inter-cluster visible link counts change for visible clusters. It MUST NOT change based on hidden cluster changes. Between two consecutive calls (overview then detail, or detail then overview) with no `generated_at` drift and identical filters, `revision` MUST be identical. Clients MAY use `revision` as a React Query cache key. Conditional request behavior (`ETag` / `If-None-Match`) is NOT part of this contract.

#### Scenario: Revision stable for identical visible state
- GIVEN the same principal, filters, and visible topology,
- WHEN overview is called twice within the same revision window,
- THEN both responses MUST have identical `revision`.

#### Scenario: Revision changes when a visible CI is added
- GIVEN a CI enters the caller's visible scope,
- WHEN overview is called next,
- THEN `revision` MUST differ from the prior response.

#### Scenario: Revision does NOT change on hidden cluster change
- GIVEN a hidden cluster's nodes change outside the caller's scope,
- WHEN overview is called,
- THEN `revision` MUST remain identical to the prior response.

#### Scenario: Revision differs across principals
- GIVEN two principals with different `allowed_locations` for identical filters,
- WHEN each calls overview,
- THEN their `revision` values MUST differ.

### Requirement: Non-enumerating hidden/absent behavior

The system MUST define identical externally observable responses for hidden (outside caller scope) and absent (nonexistent) clusters on `GET /graph/detail/{cluster_id}`:

- HTTP status: 200.
- Body: identical shape to a successful empty visible detail, with `cluster: null`, `nodes: []`, `links: []`, `boundary_stubs: []`, `empty_reason: "unavailable"`, `page` present.
- Headers: no `X-*` headers that reveal cluster existence; `Cache-Control` MAY be `no-store`.
- Timing: response time within ±20 ms of a successful empty visible cluster response, measured over at least 50 samples.
- `generated_at` and `revision` MUST be returned and MUST be caller-scope-valid.

#### Scenario: Hidden and absent produce same body
- GIVEN a hidden cluster_id and a nonexistent cluster_id,
- WHEN detail is fetched for each,
- THEN both responses have identical body shapes,
- AND `empty_reason` is `unavailable`.

#### Scenario: Server logs do not differentiate
- GIVEN the two requests above,
- WHEN server logs are inspected,
- THEN the log entries MUST NOT contain cluster_id, label, or distinguishing metadata beyond a generic "unavailable" event class.

#### Scenario: Timing parity verified
- GIVEN 50 alternating hidden/absent requests,
- WHEN response times are measured,
- THEN per-request latency MUST be within ±20 ms of matched empty visible cluster requests.

#### Scenario: No cluster metadata in headers
- GIVEN a hidden cluster request,
- WHEN response headers are inspected,
- THEN no header MAY contain cluster labels, counts, geo, or distinguishing identifiers,
- AND `Cache-Control: no-store` is permitted.

### Requirement: Visible-candidate-only search/filter target resolution

The system MUST define a search resolution vocabulary returned by server-side resolution: `single_visible_cluster`, `multiple_visible_clusters`, `no_visible_cluster`, `ambiguous`. The frontend uses this vocabulary to decide whether to fetch detail. Searchable fields are restricted to: `id`, `display_label`, `ci_type`, and any field listed in the cluster's `allowed_public_axes`. Filter precedence when multiple filters apply: `location` → `ci_type` → `text`. Server-side resolution is authoritative; the client MUST NOT compute the vocabulary from overview payload alone.

#### Scenario: Search resolves to single visible cluster
- GIVEN a search term matching exactly one visible cluster after authorization filtering,
- WHEN the server resolves the search,
- THEN the response vocabulary is `single_visible_cluster`,
- AND the client fetches detail for that cluster only.

#### Scenario: Search resolves to multiple visible clusters
- GIVEN a search term matching multiple visible clusters,
- WHEN the server resolves,
- THEN the vocabulary is `multiple_visible_clusters`,
- AND the client MUST NOT fetch detail until the operator selects one visible target.

#### Scenario: Search resolves to no visible cluster
- GIVEN a search term with zero visible matches (hidden candidates may exist),
- WHEN the server resolves,
- THEN the vocabulary is `no_visible_cluster`,
- AND the client MUST show the empty overview/search state and MUST NOT fetch full topology detail.

#### Scenario: Ambiguous search
- GIVEN a search term matching multiple visible candidates or allowed public axes,
- WHEN the server resolves,
- THEN the vocabulary is `ambiguous`,
- AND the client MUST request refinement or explicit visible-cluster selection.

#### Scenario: Search restricted to allowed public axes
- GIVEN a search term attempting to match a sensitive field not in `allowed_public_axes`,
- WHEN the server resolves,
- THEN the term MUST NOT match against the sensitive field,
- AND hidden candidates MUST NOT affect the vocabulary.

### Requirement: Aggregate disclosure and sensitive-field policy

The system MUST define aggregate suppression and a sensitive-field policy:

- `aggregate_policy.minimum_count` default: 5.
- Any count, weight, geo summary, or "has more" signal with fewer than `minimum_count` visible items MUST be either omitted or replaced with `{ redacted: true, redaction_reason: "low_cardinality" }`. This applies to overview cluster counts, inter-cluster link counts, legend bucket counts, and any "has more" page signal.
- An aggregate-breakdown permission — recommended name `graph:aggregate_breakdown:read` — gates per-bucket detail. Without this permission, only the redacted form is returned. This permission is NOT yet defined in `UserPermission` and is a prerequisite for #391.
- Overview: MUST NEVER return `public_ip`, raw internal `metadata`, exact geo coordinates, serial numbers, provider account identifiers, or comparable sensitive fields.
- Detail: applies the EXISTING `/graph/full` projection policy (same fields minus raw `public_ip` for non-permitted principals). The exact policy helper is defined in #391.

#### Scenario: Low-cardinality bucket redacted
- GIVEN a status bucket with 3 visible records and `minimum_count=5`,
- WHEN overview is built,
- THEN the bucket value is replaced with `{ redacted: true, redaction_reason: "low_cardinality" }`.

#### Scenario: Permitted principal sees per-bucket detail
- GIVEN a principal with `graph:aggregate_breakdown:read`,
- WHEN overview is built for a cluster with buckets ≥ `minimum_count`,
- THEN exact bucket values are returned without redaction.

#### Scenario: Non-permitted principal sees only redacted form
- GIVEN a principal without `graph:aggregate_breakdown:read`,
- WHEN overview is built for any cluster,
- THEN every bucket below `minimum_count` is redacted,
- AND no exact value for that bucket is exposed.

#### Scenario: Sensitive fields never appear in overview
- GIVEN any principal,
- WHEN overview is built,
- THEN the response MUST NOT contain `public_ip`, raw `metadata`, exact geo, serial numbers, or provider account identifiers.

#### Scenario: Detail `show_sensitive_metadata: true` requires permission
- GIVEN a detail node projection with `show_sensitive_metadata: true`,
- WHEN the response is built,
- THEN `projection_flags.sensitive_source` MUST be `principal_with_permission`.

## Non-goals

- No Neo4j aggregation or detail queries (owned by #391).
- No `/graph/overview` or `/graph/detail/{cluster_id}` route handlers (owned by #391).
- No consumer migration (`GraphCMDB`, `NetworkVisualizer`) — owned by #392 and #393.
- No redaction change to `/graph/full` — that endpoint is frozen.
- No OpenAPI-to-TypeScript codegen pipeline.

## Prerequisites

- The `graph:aggregate_breakdown:read` permission MUST be added to `UserPermission` before #391 ships.
- The detail projection policy helper that reuses the existing `/graph/full` projection policy MUST be defined in #391.
- The `cluster_id` codec error path MUST NOT leak cluster metadata; this is asserted in REQ-4 and REQ-7.
