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

The system MUST provide default icon keys for Layer 2 switch, Layer 3 switch, router, server, SaaS, storage, cameras, video analytics, telecom radio, trunk link, access CI, and distribution CI category types. These defaults MUST apply through frontend name inference only and MUST NOT require backend/API/schema changes, automatic migration, or persisted category backfill.

#### Scenario: Known technology receives default icon

- GIVEN a category matches a supported technology type
- WHEN category icon metadata is initialized, read, or inferred
- THEN the category has the expected default `icon_key`

#### Scenario: Existing category without mapping uses generic icon

- GIVEN an existing category has no icon association and does not match a supported default name
- WHEN the category is displayed or returned to clients
- THEN the system MUST use a generic/default technology icon

#### Scenario: Existing persisted categories are not backfilled

- GIVEN an existing category has no persisted icon association
- WHEN the new frontend defaults are available
- THEN the system MUST NOT automatically persist a new `icon_key`
- AND explicit saved associations remain unchanged

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

### Requirement: Radio and Network Role Catalog Entries

The frontend controlled icon catalog MUST include exactly these new category icon keys: `radio_telecom`, `trunk_link`, `access_ci`, and `distribution_ci`. Each entry MUST have a non-empty fixed Material Symbol and MUST remain available to existing shared category icon consumers without requiring consumer-specific changes.

#### Scenario: Catalog exposes the four new keys

- GIVEN the category icon catalog is loaded
- WHEN the available entries are inspected
- THEN `radio_telecom`, `trunk_link`, `access_ci`, and `distribution_ci` are present
- AND each entry has a non-empty Material Symbol

#### Scenario: New keys are accepted as controlled keys

- GIVEN a category references one of the four new icon keys
- WHEN the frontend validates the key
- THEN the key is accepted as a valid category icon key
- AND the resolved entry is not the generic fallback

#### Scenario: Existing invalid-key fallback remains unchanged

- GIVEN a category references an unknown icon key
- WHEN the frontend resolves the category icon
- THEN the system MUST use the generic/default technology icon
- AND no blank or broken icon is returned

### Requirement: Bilingual Catalog Discovery

The frontend catalog MUST support English and Spanish aliases for the new radio, trunk, access, and distribution entries. Search and category-name inference MUST resolve these terms without changing existing icon mappings.

#### Scenario: English aliases find each new entry

- GIVEN an operator searches for radio, trunk, access, or distribution terms in English
- WHEN the catalog search runs
- THEN the matching new icon entry is returned
- AND unrelated existing entries are not required to change

#### Scenario: Spanish aliases find each new entry

- GIVEN an operator searches for radio, troncal, acceso, or distribución terms in Spanish
- WHEN the catalog search runs
- THEN the matching new icon entry is returned
- AND the result can be selected from the existing flat selector catalog

#### Scenario: Category names infer new defaults

- GIVEN a category name contains supported English or Spanish radio, trunk, access, or distribution terms
- WHEN the frontend infers the category icon key from the name
- THEN it resolves to the matching new key
- AND unrelated or unsupported category names still resolve to `generic`

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
