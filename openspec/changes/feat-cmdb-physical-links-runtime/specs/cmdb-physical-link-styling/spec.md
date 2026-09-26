# Spec delta: cmdb-physical-link-styling

## ADDED Requirements

### REQ-PHYSLINK-STYLE-1: Style registry per PhysicalLink.type

The system MUST provide a `PhysicalLinkStyleRegistry` (frontend) that maps each `PhysicalLink.type` to a distinct color, dash pattern, and label style.

#### Scenario: each type has distinct color
- GIVEN a `PhysicalLink` with `type: "fiber"`
- WHEN the topology layer renders the link
- THEN the color comes from the registry's `fiber` entry
- AND the color is distinct from `copper`, `microwave`, `wireless_ptp`

#### Scenario: dash pattern per type
- GIVEN a `PhysicalLink` with `type: "wireless_ptp"`
- WHEN the topology layer renders the link
- THEN the dash pattern comes from the registry's `wireless_ptp` entry
- AND the pattern is distinct from solid (`fiber`)

### REQ-PHYSLINK-STYLE-2: Legend

The system MUST render a default legend explaining the link-type colors.

#### Scenario: legend lists all types
- WHEN the topology view opens
- THEN the legend renders one entry per supported `PhysicalLink.type`
- AND each entry shows the color swatch and a one-line description

### REQ-PHYSLINK-STYLE-3: No override of tunnel styling

The system MUST NOT modify the existing tunnel link styling or the `medium` field semantics.

#### Scenario: tunnel links render unchanged
- GIVEN a tunnel link with `medium: "vpn"`
- WHEN the topology layer renders the link
- THEN the tunnel styling rules apply
- AND the `PhysicalLinkStyleRegistry` does not affect tunnel rendering

#### Scenario: tunnel legend separate
- WHEN the topology view renders
- THEN the link-type legend does NOT include tunnel types
- AND the existing tunnel legend (if any) remains visible

## MODIFIED Requirements

_None._

## REMOVED Requirements

_None._

## Cross-references

- Contract slice: #323 (`PhysicalLink` schema)
- Source proposal: `openspec/changes/feat-cmdb-physical-links-runtime/proposal.md`