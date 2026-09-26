# Spec delta: cmdb-physical-link-utilization

## ADDED Requirements

### REQ-PHYSLINK-UTIL-1: Aggregation over interface counters

The system MUST aggregate interface counters per `PhysicalLink` over a configurable time window.

#### Scenario: aggregation correctness
- GIVEN a `PhysicalLink` connected via `CONNECTED_VIA` to 3 interfaces
- AND each interface reports `ifInOctets` deltas over the window
- WHEN the principal queries `GET /api/cmdb/physical-links/{id}/utilization?window=15m`
- THEN the response is `200 OK`
- AND the utilization is the sum (or appropriate aggregate) of the interface counters

#### Scenario: window parameter respected
- GIVEN the previous scenario
- WHEN the principal queries with `window=1h`
- THEN the response aggregates over 1 hour, not 15 minutes

### REQ-PHYSLINK-UTIL-2: Distinct "no data" state

The system MUST return a distinct "no data" state when no recent counters are available, NOT zero utilization.

#### Scenario: empty interfaces
- GIVEN a `PhysicalLink` with no connected interfaces
- WHEN the principal queries the utilization endpoint
- THEN the response is `200 OK`
- AND the utilization is `null` or absent
- AND `empty_reason: "no_data"`

#### Scenario: stale interfaces
- GIVEN a `PhysicalLink` whose interfaces have not reported within the staleness threshold
- WHEN the principal queries the utilization endpoint
- THEN the response carries `stale: true`
- AND the utilization is `null` or absent (NOT zero)

### REQ-PHYSLINK-UTIL-3: No impact on tunnel metric paths

The system MUST NOT change existing tunnel metric paths.

#### Scenario: tunnel metrics unchanged
- GIVEN the existing tunnel metric aggregation
- WHEN the physical-link utilization endpoint is deployed
- THEN tunnel metric responses are byte-equivalent to before

## MODIFIED Requirements

_None._

## REMOVED Requirements

_None._

## Cross-references

- Source proposal: `openspec/changes/feat-cmdb-physical-links-runtime/proposal.md`
- Related slice: #443 (interface-to-link polling integration feeds this read model)