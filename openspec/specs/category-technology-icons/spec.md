# Category Technology Icons Specification

## Purpose

Define category-owned technology icons so operators can recognize technology type consistently across catalog, inventory, monitoring, maps, topology, and detail views without confusing icons with operational status.

## Requirements

### Requirement: Category Icon Association

The system MUST persist an `icon_key` association for catalog categories. The icon key MUST identify a controlled selectable icon, not an uploaded custom asset.

#### Scenario: Category stores selected icon

- GIVEN an admin selects an allowed icon for a category
- WHEN the category is saved
- THEN the category exposes the selected `icon_key`
- AND future reads return the same association

#### Scenario: Invalid icon is rejected

- GIVEN a category update references an icon outside the allowed catalog
- WHEN the update is submitted
- THEN the system MUST reject the association
- AND the previous category icon remains unchanged

### Requirement: Initial Technology Defaults

The system MUST provide default icon keys for Layer 2 switch, Layer 3 switch, router, server, SaaS, storage, cameras, and video analytics category types.

#### Scenario: Known technology receives default icon

- GIVEN a category matches an initial technology type
- WHEN category icon metadata is initialized or read
- THEN the category has the expected default `icon_key`

#### Scenario: Existing category without mapping uses generic icon

- GIVEN an existing category has no icon association
- WHEN the category is displayed or returned to clients
- THEN the system MUST use a generic/default technology icon

### Requirement: Admin Icon Selection Experience

Admin category management MUST expose a visual icon selector showing the current icon, searchable controlled icon grid, preview, and generic/default option.

#### Scenario: Admin previews and saves icon

- GIVEN an admin is editing a category
- WHEN the admin searches the icon catalog and selects an icon
- THEN the UI previews the selection before save
- AND saving updates the category association

#### Scenario: Admin selects generic/default icon

- GIVEN an admin wants no specific technology icon
- WHEN the admin chooses the generic/default option
- THEN the category uses the generic/default technology icon

### Requirement: System-Wide Technology Rendering

The system MUST render category technology icons consistently anywhere category/type identity appears, especially maps and topology. Technology icons MUST NOT represent operational status, severity, or health.

#### Scenario: Shared icon appears across surfaces

- GIVEN a category has an `icon_key`
- WHEN the category appears in catalog, inventory, monitoring, detail, map, or topology surfaces
- THEN each surface renders the same technology icon for that category

#### Scenario: Status remains visually separate

- GIVEN a node has both a technology category and an operational status
- WHEN the node is rendered on maps or topology
- THEN the technology icon identifies category type only
- AND status indicators remain separate from the technology icon

### Requirement: Category Payload Compatibility

The system MUST expose category icon metadata without breaking existing category/type consumers, including `/nodes` consumers that rely on category values mapped into `type`.

#### Scenario: Existing type value remains compatible

- GIVEN a client reads node data that previously used category as `type`
- WHEN category icon metadata is added
- THEN the existing category/type value remains available
- AND icon metadata is available for rendering

#### Scenario: Missing icon metadata remains safe

- GIVEN a client receives a category without `icon_key`
- WHEN the client renders the category
- THEN it MUST display the generic/default icon
- AND no surface renders a blank or broken icon

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
