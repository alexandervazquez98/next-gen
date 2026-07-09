# ITSM Service Catalog Specification

## Purpose

The first slice SHALL provide a dedicated ITSM Service Catalog domain and an independent Ticket/Folio domain so teams can manage services and request/incident records without coupling to existing inventory catalog behavior or event-response automation.

## Requirements

### Requirement: Service Catalog is the ITSM source of truth

The system SHALL provide full CRUD for a dedicated Service Catalog domain that is independent of inventory catalog entities.

The Service Catalog record SHALL include, at minimum, English-named technical fields such as `service_id`, `name`, `owner_team`, `category`, `tier`, `criticality`, `sla_target_minutes`, `active`, `created_at`, `updated_at`, and `updated_by`.

#### Scenario: Create, read, update, and deactivate a catalog service

- GIVEN an authorized user provides a valid Service Catalog payload
- WHEN the service is created
- THEN the system SHALL persist it with `active=true`.
- WHEN the same service is updated with valid fields
- THEN the system SHALL persist the new values and update `updated_at`.
- WHEN the service is marked inactive
- THEN it SHALL remain queryable for historical consistency with `active=false`.

### Requirement: Service Catalog values are validated with deterministic defaults

The system SHALL validate Service Catalog inputs at create/update time and apply deterministic defaults where fields are optional.

The system SHALL require a non-empty `name` and a non-negative numeric `sla_target_minutes`.

The system SHALL reject invalid payloads with a deterministic validation error and MUST NOT partially persist changes.

#### Scenario: Invalid SLA target is rejected

- GIVEN a Service Catalog payload with negative `sla_target_minutes`
- WHEN an upsert operation is executed
- THEN the system SHALL return a validation failure
- AND no catalog changes SHALL be saved.

### Requirement: Ticket/Folio records support independent CRUD

The system SHALL provide independent CRUD for Ticket/Folio records with initial types limited to `request` and `incident`.

Ticket/Folio records SHALL include English-named technical fields such as `ticket_id`, `type`, `title`, `description`, `service_catalog_id`, `status`, `closed_reason`, `created_at`, `updated_at`, and `updated_by`.

#### Scenario: Create/read/update/close a ticket folio

- GIVEN an authorized user creates a `request` folio with valid payload
- WHEN the create API is called
- THEN the system SHALL persist the folio with initial `status=open`.
- WHEN the folio is read or updated
- THEN the system SHALL return current persisted values without requiring an event context.
- WHEN the folio is closed through the status lifecycle and updated to `closed`
- THEN the system SHALL persist the closure and preserve created history.

### Requirement: Ticket/Folio lifecycle is linear and validated

The system SHALL accept only the following status state machine for Ticket/Folio records in this slice: `open -> in_progress -> in_validation -> resolved -> closed`.

The system SHALL reject status updates that skip steps, regress (move backward), or transition from `closed` to any other status.

#### Scenario: Valid linear transition sequence

- GIVEN a ticket with status `open`
- WHEN status is updated to `in_progress`
- THEN the transition SHALL be accepted.
- WHEN status is updated to `resolved` directly from `open`
- THEN the transition SHALL be rejected.

### Requirement: Ticket/Folio and Service Catalog are decoupled from inventory catalog

The system SHALL keep ITSM domains separate from inventory catalog data models and surfaces.

A Service Catalog service SHALL NOT be a rebranded alias of inventory `Category`/CI catalog entities, and Ticket/Folio SHALL NOT depend on inventory catalog CRUD for lifecycle operations.

#### Scenario: Inventory operations do not drive ITSM CRUD

- GIVEN an inventory catalog item is created, updated, or deleted
- WHEN no explicit Service Catalog API call is made
- THEN no Ticket/Folio record SHALL be auto-created, auto-updated, or auto-deleted.
- WHEN an ITSM operator uses Service Catalog APIs
- THEN the result SHALL reflect ITSM data regardless of inventory catalog operations.

### Requirement: Event-to-folio association remains a future extension point

The system SHALL NOT implement automatic event-to-folio creation, linking, or mutation in this first slice.

The system SHALL preserve extension points (stable identifiers, documented boundaries, and explicit API version compatibility) so future work can add event-driven association without breaking existing Ticket/Folio records.

#### Scenario: Event ingestion stays behaviorally unchanged for folios

- GIVEN an event is processed under existing workflows
- WHEN the event engine runs
- THEN it SHALL NOT create, update, or close any Ticket/Folio record implicitly.
- WHEN an existing event arrives with the same payload as before this change
- THEN event response behavior SHALL remain unchanged.

### Requirement: Existing event SLA behavior remains compatible

The system SHALL maintain current event SLA behavior for snapshots and fallback resolution.

The system SHALL NOT mutate existing event SLA snapshots when Service Catalog entries are edited.

#### Scenario: SLA retrieval remains stable after catalog changes

- GIVEN an event record already contains SLA snapshot data
- WHEN the related Service Catalog service is updated in this change
- THEN subsequent reads of that historical event SHALL return the same snapshot values as before the update.
- WHEN the event path relies on existing fallback behavior
- THEN it SHALL continue to resolve SLA context using existing rules when snapshot data is present or when service lookups fail.

### Requirement: First-slice implementation scope remains bounded

The system SHALL not include event-response configuration, automatic routing, or external ITSM connector behavior in this slice.

The system SHALL include only capabilities directly required for independent Service Catalog CRUD, independent Ticket/Folio CRUD, and linear lifecycle validation.

#### Scenario: Out-of-scope features are not shipped in this slice

- GIVEN the implementation of this slice
- WHEN a consumer tests ticket/folio and catalog behavior
- THEN no new endpoints SHALL automatically connect events to folios.
- AND no external workflow connectors for third-party ITSM tools SHALL be introduced.

## Risks

- The proposal does not contain a `Capabilities` section, so domain boundaries are inferred from proposal and exploration text; this assumption should be reviewed before implementation.
- The first slice combines two CRUD domains plus lifecycle validation and is likely to be large; if implementation exceeds the review budget, split into stacked PR slices.
- Permissions and route naming need explicit follow-up design decisions to avoid overlap with existing inventory catalog authorization and navigation.
