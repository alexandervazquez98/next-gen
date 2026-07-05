# Delta for VPN Tunnel Relations

## ADDED Requirements

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
