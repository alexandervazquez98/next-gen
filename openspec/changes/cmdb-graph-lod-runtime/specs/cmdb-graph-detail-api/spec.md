# Spec delta: cmdb-graph-detail-api

## ADDED Requirements

### REQ-DETAIL-1: Detail endpoint

The system MUST expose `GET /graph/detail/{cluster_id}` returning a `GraphDetailResponse` (per `backend/schemas/graph.py::GraphDetailResponse` shipped in v1.17.6). The endpoint MUST be bounded and paginated.

#### Scenario: detail returns visible subgraph with pagination
- GIVEN a principal with `CMDB_READ` and a cluster `location:datacenter-east` with 200 visible CIs
- WHEN the principal calls `GET /graph/detail/location:datacenter-east?limit=50`
- THEN the response is `200 OK`
- AND the body contains up to 50 nodes and their incident edges
- AND the body includes a cursor for the next page

#### Scenario: detail pagination via cursor
- GIVEN the previous scenario, with a returned cursor `c`
- WHEN the principal calls `GET /graph/detail/location:datacenter-east?limit=50&cursor=c`
- THEN the response continues from where the cursor left off
- AND no CIs from previous pages are duplicated

### REQ-DETAIL-2: Cluster ID parsing

The system MUST parse `cluster_id` per `backend/contracts/cluster_id.py` (case-insensitive match, axis-derived display).

#### Scenario: valid cluster_id parses
- GIVEN a path parameter `location:datacenter-east`
- WHEN the detail handler resolves the cluster
- THEN the axis is `location`
- AND the key normalizes to lowercase `datacenter-east`
- AND the display preserves the original case if different

#### Scenario: invalid cluster_id rejected
- GIVEN a path parameter `invalid-format`
- WHEN the detail handler resolves the cluster
- THEN the response is `400 Bad Request`
- AND the error body matches the contract `{error, reason, cluster_id}` shape

### REQ-DETAIL-3: Cursor semantics

The system MUST use the cursor codec (`backend/contracts/cursor.py`) for pagination state.

#### Scenario: cursor encodes principal hash
- GIVEN a principal with identity hash `h1`
- WHEN a cursor is issued for that principal
- THEN the cursor contains `principal_hash: h1`
- AND decoding the cursor as principal with hash `h2` (after permission change) raises `PermissionChangedError`

#### Scenario: stale cursor raises StaleCursorError
- GIVEN a cursor issued at revision `r1`
- WHEN the server's current revision is `r2 != r1`
- AND the client presents the stale cursor
- THEN the response is `409 Conflict`
- AND the body includes `current_revision: r2`

#### Scenario: invalid cursor raises InvalidCursorError
- GIVEN a malformed cursor string
- WHEN the client presents it
- THEN the response is `400 Bad Request`
- AND no server state changes

### REQ-DETAIL-4: Hidden ≡ absent parity (detail)

The detail endpoint MUST respond identically for hidden and absent clusters (mirror of REQ-OVERVIEW-3).

#### Scenario: hidden cluster detail
- GIVEN a cluster `location:datacenter-east` that exists
- AND the principal's visible set excludes it
- WHEN the principal calls `GET /graph/detail/location:datacenter-east`
- THEN the response is `200 OK` with `cluster: null`
- AND `empty_reason: "hidden_absent"`

#### Scenario: absent cluster detail
- GIVEN a cluster `location:nonexistent` that does not exist
- WHEN the principal calls `GET /graph/detail/location:nonexistent`
- THEN the response is byte-equivalent to the hidden cluster response

### REQ-DETAIL-5: Detail projection policy

The system MUST apply `DetailProjectionPolicy` (from `backend/contracts/projection.py`) to each node in the detail response.

#### Scenario: sensitive metadata omitted without permission
- GIVEN a principal lacks `graph:sensitive_metadata:read`
- WHEN the principal calls `GET /graph/detail/location:datacenter-east`
- THEN each `DetailNode` omits sensitive fields
- AND `sensitive_source` is null or absent per DTO contract

#### Scenario: sensitive metadata included with permission
- GIVEN a principal has `graph:sensitive_metadata:read`
- AND the principal explicitly requested sensitive fields
- WHEN the principal calls `GET /graph/detail/location:datacenter-east?show_sensitive=true`
- THEN each `DetailNode` includes sensitive fields
- AND `sensitive_source` is populated

## MODIFIED Requirements

_None — additive._

## REMOVED Requirements

_None._

## Cross-references

- DTOs: `backend/schemas/graph.py::GraphDetailResponse`, `GraphDetailNode`, `GraphDetailEdge`, `DetailCluster`, `BoundaryStub`, `ProjectionFlags`, `SensitiveSource`, `EmptyReason` (shipped v1.17.6)
- Value objects: `backend/contracts/cursor.py`, `backend/contracts/cluster_id.py`, `backend/contracts/projection.py`, `backend/contracts/revision.py` (shipped v1.17.6)
- Frozen fixtures: `fixtures/graph-contracts/detail_*.json` (shipped v1.17.6)
- Source proposal: `openspec/changes/cmdb-graph-lod-runtime/proposal.md`