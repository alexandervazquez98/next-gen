# VPN Tunnel Relations Specification

## Purpose

Define Slice 1 data primitives for VPN, SD-WAN, and satellite tunnels without backfilling existing CIs or replacing existing node status/event semantics.

## Requirements

### Requirement: Public IP and VPN Hub CI Metadata

The system MUST support nullable CI metadata field `public_ip` and CI type `vpn_hub`. `public_ip` MUST be validated as an IP address when present, and `vpn_hub` MUST be distinct from `router` with icon key `vpn_hub`.

#### Scenario: [Slice 1] Save CI with public IP

- GIVEN a new or edited CI has a valid `public_ip`
- WHEN the CI is saved through the API
- THEN reads return the same `public_ip`
- AND existing `ip` remains unchanged

#### Scenario: [Slice 1] Reject invalid public IP

- GIVEN a CI payload contains an invalid `public_ip`
- WHEN the CI is saved
- THEN the system MUST reject the payload
- AND no partial metadata update is persisted

#### Scenario: [Slice 1] Existing CIs are not backfilled

- GIVEN existing CIs do not have `public_ip`
- WHEN this capability is enabled
- THEN the system MUST NOT infer or backfill `public_ip`

### Requirement: Tunnel Medium Metadata

The system MUST persist tunnel relation metadata `medium` with allowed values `vpn`, `sd_wan`, or `satellite`. Tunnel metadata MAY be attached to existing CI-to-CI relationship types, but invalid values MUST be rejected.

#### Scenario: [Slice 1] Create tunnel relation medium

- GIVEN two CIs are linked with `medium: vpn`
- WHEN the relationship is created
- THEN reads expose `medium: vpn`
- AND the relationship type remains compatible with existing link consumers

#### Scenario: [Slice 1] Reject unsupported medium

- GIVEN a link payload contains `medium: microwave`
- WHEN the relationship is created or edited
- THEN the system MUST reject it

### Requirement: Tunnel Endpoint Validation

The system MUST require every tunnel relation with `medium` to connect two CIs and at least one endpoint MUST be type `vpn_hub`. This keeps hubs first-class while allowing routers, servers, sites, or services as the remote endpoint.

#### Scenario: [Slice 1] Hub-to-remote tunnel is valid

- GIVEN one endpoint is `vpn_hub` and the other endpoint is a CI
- WHEN a tunnel relation is saved
- THEN the relation is accepted

#### Scenario: [Slice 1] Non-hub tunnel is rejected

- GIVEN neither endpoint is `vpn_hub`
- WHEN a tunnel relation with `medium` is saved
- THEN the system MUST reject the relation

### Requirement: API Read/Write Contract

The system MUST accept and return `public_ip`, `vpn_hub`, and tunnel `medium` metadata through node, link, and graph APIs without changing existing node status or event fields.

#### Scenario: [Slice 1] Graph payload includes tunnel metadata

- GIVEN a tunnel relation has `medium: satellite`
- WHEN a client fetches links or the full graph
- THEN the payload includes the tunnel medium
- AND node status/event fields are unchanged

### Requirement: Eligible Tunnel Health Link Reads

The system MUST let backend tunnel-health consumers identify eligible tunnel links without changing Slice 1 relation contracts. A link SHALL be eligible when it connects two CIs, has `medium` of `vpn`, `sd_wan`, or `satellite`, and satisfies existing tunnel endpoint validation. Link reads used for tunnel health MUST preserve existing node status, event fields, relationship type compatibility, and tunnel metadata.

#### Scenario: Eligible tunnel link can be read

- GIVEN a valid tunnel relation has `medium: vpn` and one endpoint is `vpn_hub`
- WHEN backend tunnel-health logic reads eligible links
- THEN the relation MUST be included with enough identity to request latest tunnel health
- AND existing link metadata remains unchanged

#### Scenario: Non-tunnel link is excluded

- GIVEN a CI-to-CI relationship has no tunnel `medium`
- WHEN backend tunnel-health logic reads eligible links
- THEN the relationship MUST NOT be treated as tunnel-health eligible

#### Scenario: Slice 1 contract remains stable

- GIVEN clients read links or graph data after tunnel-health support is added
- WHEN the payload includes tunnel relations
- THEN `public_ip`, `vpn_hub`, and `medium` behavior MUST remain compatible with Slice 1
- AND node status and event fields MUST remain unchanged

### Requirement: Tunnel Health Link Identity Validation

Tunnel health link identifiers MUST be deterministic unpadded base64url JSON with only `source`, `relationship`, `target`, and `medium` fields in canonical order. Decoding MUST reject payloads larger than 512 bytes, unknown fields, missing fields, invalid tunnel media, and any relationship not accepted by the existing CI relationship whitelist before repository Cypher is constructed.

#### Scenario: Valid canonical identifier

- GIVEN an eligible tunnel relation has source, whitelisted relationship, target, and tunnel medium
- WHEN a tunnel health link id is encoded and decoded
- THEN the decoded identity MUST match the original fields exactly

#### Scenario: Unsafe identifier rejected

- GIVEN a link id decodes to an unknown field, oversized payload, or non-whitelisted relationship
- WHEN the tunnel health endpoint validates it
- THEN the request MUST be rejected before dynamic Cypher is constructed
