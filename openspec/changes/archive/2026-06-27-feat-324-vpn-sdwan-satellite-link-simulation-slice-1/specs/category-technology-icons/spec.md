# Delta for Category Technology Icons

## ADDED Requirements

### Requirement: Tunnel and VPN Hub Icon Keys

The system MUST include controlled icon keys `vpn_tunnel`, `sd_wan_tunnel`, `satellite_link`, and `vpn_hub` in the category technology icon catalog. These icons MUST remain technology identifiers and MUST NOT represent operational status, severity, or tunnel health.

#### Scenario: [Slice 1] Tunnel icon keys resolve from the catalog

- GIVEN a category or tunnel visual references `vpn_tunnel`, `sd_wan_tunnel`, `satellite_link`, or `vpn_hub`
- WHEN the icon is rendered
- THEN the controlled catalog returns a stable material symbol for that key
- AND missing metadata still falls back to the generic icon

#### Scenario: [Slice 3] Tunnel health styling stays separate

- GIVEN a tunnel has both a technology icon key and health `DEGRADED`
- WHEN the tunnel is rendered in topology or monitoring surfaces
- THEN the icon identifies the technology only
- AND health is rendered by separate state styling
