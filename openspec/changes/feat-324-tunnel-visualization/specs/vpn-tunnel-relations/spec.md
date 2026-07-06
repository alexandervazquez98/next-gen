# Delta for VPN Tunnel Relations

## ADDED Requirements

### Requirement: Visual Relationship Tunnel Medium Editing

VisualRelationshipEditor MUST support creating, editing, and displaying tunnel relation `medium` values `vpn`, `sd_wan`, and `satellite` without changing existing relationship-type compatibility or backend tunnel-health normalization.

#### Scenario: Create tunnel medium from editor

- GIVEN an operator creates a relationship between valid tunnel endpoints
- WHEN the operator selects `vpn`, `sd_wan`, or `satellite` as the medium and saves
- THEN the saved relation MUST expose the selected medium on subsequent reads

#### Scenario: Edit existing tunnel medium

- GIVEN an existing editable tunnel relation has a medium
- WHEN the operator changes the medium to another allowed tunnel value
- THEN subsequent graph/link/editor reads MUST show the updated medium

#### Scenario: Existing medium and health context display

- GIVEN the editor renders an existing tunnel relation
- WHEN medium or tunnel health context is available
- THEN the editor MUST display the medium and shared visual health state without making ICMP authoritative

## MODIFIED Requirements

### Requirement: API Read/Write Contract

The system MUST accept and return `public_ip`, `vpn_hub`, and tunnel `medium` metadata through node, link, and graph APIs without changing existing node status or event fields. API/frontend graph and node contracts SHALL expose `public_ip` consistently enough for tunnel tooltip consumers, preferring a top-level nullable field when needed while preserving existing metadata compatibility. Top-level `public_ip` MUST only be emitted from server-side scoped `/nodes`, `/graph/full`, and any topology payload feeding CIDetailModal; clients MUST NOT receive `public_ip` for CIs outside their authorized location scope.
(Previously: APIs accepted and returned public_ip/vpn_hub/medium metadata without requiring consistent top-level frontend exposure for tunnel tooltips.)

#### Scenario: [Slice 1] Graph payload includes tunnel metadata

- GIVEN a tunnel relation has `medium: satellite`
- WHEN a client fetches links or the full graph
- THEN the payload includes the tunnel medium
- AND node status/event fields are unchanged

#### Scenario: Public IP is available to tooltip consumers

- GIVEN a node has a valid `public_ip`
- WHEN graph, node, or topology consumers build tunnel tooltip context
- THEN the frontend contract MUST provide the public IP consistently as top-level `public_ip` or a documented compatible fallback
- AND existing `metadata.public_ip` consumers MUST remain compatible

#### Scenario: Non-admin empty scope does not leak public IP

- GIVEN a non-admin user has no allowed locations
- WHEN the user fetches `/nodes`, `/graph/full`, or CIDetailModal topology data
- THEN no out-of-scope node or top-level `public_ip` MUST be present

#### Scenario: Non-admin limited scope only sees scoped public IPs

- GIVEN a non-admin user is limited to one location and other CIs have public IPs
- WHEN scoped node, graph, or topology data is returned
- THEN only in-scope CIs MAY include top-level `public_ip`
- AND out-of-scope infrastructure addresses MUST NOT appear in nodes, links, metadata, or topology context

#### Scenario: Admin scope preserves authorized public IPs

- GIVEN an admin user requests node or graph topology data
- WHEN scoped repository access authorizes all relevant locations
- THEN in-scope public IP fields MAY be projected top-level without removing `metadata.public_ip`

#### Scenario: Missing public IP remains explicit

- GIVEN a tunnel endpoint has no public IP
- WHEN a tooltip is built for ICMP context
- THEN the frontend contract MUST expose the absence as nullable/missing public IP
- AND the tooltip MUST NOT infer a public IP from private `ip` fields
