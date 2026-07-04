# Delta for category-technology-icons

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Initial Technology Defaults

The system MUST provide default icon keys for Layer 2 switch, Layer 3 switch, router, server, SaaS, storage, cameras, video analytics, telecom radio, trunk link, access CI, and distribution CI category types. These defaults MUST apply through frontend name inference only and MUST NOT require backend/API/schema changes, automatic migration, or persisted category backfill.

(Previously: Defaults covered Layer 2 switch, Layer 3 switch, router, server, SaaS, storage, cameras, and video analytics category types.)

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
