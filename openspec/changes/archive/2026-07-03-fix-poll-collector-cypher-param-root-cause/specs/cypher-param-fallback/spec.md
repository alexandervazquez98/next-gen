# Delta for Cypher Param Fallback

## ADDED Requirements

### Requirement: Primary Event writer collector assignment correctness

Primary Event writer Cypher that updates existing Event nodes MUST property-qualify `poll_collector_id` assignments against the Event node alias. The primary writer MUST NOT rely on `cypher-param-fallback` to recover from malformed bare assignment syntax such as `poll_collector_id = $poll_collector_id`.

#### Scenario: Existing Event update uses property-qualified assignment

- GIVEN a primary SNMP Event writer updates an existing Event node
- WHEN the writer assigns a collector attribution value
- THEN the assignment MUST target the Event node property, not a bare Cypher variable
- AND the primary query MUST remain valid without invoking fallback for that assignment

#### Scenario: Bare collector assignment is rejected by regression coverage

- GIVEN primary SNMP worker query strings are inspected by regression tests
- WHEN a query contains `poll_collector_id = $poll_collector_id` without an Event node alias
- THEN the regression test MUST fail
- AND the failure MUST identify the malformed primary query shape

### Requirement: Fallback remains temporary operational protection

The fallback SHALL remain available as temporary defense-in-depth for the existing undefined-`poll_collector_id` error condition, but successful implementation of this change MUST reduce dependency on fallback by fixing malformed primary Event writer Cypher.

#### Scenario: Temporary fallback is preserved

- GIVEN the root-cause fix is implemented
- WHEN a matching undefined-`poll_collector_id` `ClientError` still occurs
- THEN the existing fallback behavior MUST remain available
- AND diagnostic logging requirements MUST still apply

#### Scenario: Primary malformed syntax is not normalized as expected fallback use

- GIVEN the direct primary query defect is present in source
- WHEN implementation verifies issue #343
- THEN fallback activation MUST NOT be treated as an acceptable steady-state outcome
- AND the primary query source MUST be corrected instead

### Requirement: Adjacent poll_collector_id audit boundary

Implementation MUST audit direct `poll_collector_id` Cypher usage in polling/Event writer paths. If suspicious adjacent Cypher outside the direct SNMP Event writer assignment scope is found, implementation MUST report the finding and stop before expanding scope.

#### Scenario: Suspicious adjacent Cypher is found

- GIVEN audit finds suspicious `poll_collector_id` Cypher outside the direct assignment defect
- WHEN the finding would expand implementation scope
- THEN implementation MUST report the finding before changing it
- AND implementation MUST wait for approval before expanding scope
