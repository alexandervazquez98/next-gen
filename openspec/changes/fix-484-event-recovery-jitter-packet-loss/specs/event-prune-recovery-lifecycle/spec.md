# Delta for event-prune-recovery-lifecycle

## ADDED Requirements

### Requirement: ICMP-Jitter Reuses RECOVERED Events

The ICMP-jitter recovery writer MUST treat `RECOVERED` as eligible in its existing-event predicate so a subsequent failure reopens the existing ROOT Event rather than creating a new ROOT. The ICMP-jitter CREATE payloads MUST also include `created_at: datetime()` so that the cursor can paginate these rows reliably.

#### Scenario: DOWN–OK–DOWN reuses the ROOT for jitter

- GIVEN an ICMP-jitter ROOT transitions DOWN to OK and then DOWN again
- WHEN the second failure is written
- THEN the original ROOT event id is reused
- AND no new ROOT is created

#### Scenario: ICMP-jitter CREATE carries `created_at`

- GIVEN an ICMP-jitter CREATE payload is emitted
- WHEN the writer persists the new Event
- THEN the `created_at` property is set to the current timestamp
- AND the cursor can order this row by `created_at` without falling back to `id`

#### Scenario: ICMP-jitter recovery excludes PROPAGATED rows from direct match

- GIVEN an ICMP-jitter Event has `correlation_type='PROPAGATED'` and is currently OPEN
- WHEN the recovery writer runs for a CI whose jitter sample is OK
- THEN the row is NOT recovered by direct match
- AND the row is recovered only via its ROOT through the descendant branch when the ROOT transitions

### Requirement: ICMP-PacketLoss Reuses RECOVERED Events

The ICMP-packet-loss recovery writer MUST treat `RECOVERED` as eligible in its existing-event predicate so a subsequent failure reopens the existing ROOT Event rather than creating a new ROOT. The ICMP-packet-loss CREATE payloads MUST also include `created_at: datetime()` so that the cursor can paginate these rows reliably.

#### Scenario: DOWN–OK–DOWN reuses the ROOT for packet loss

- GIVEN an ICMP-packet-loss ROOT transitions DOWN to OK and then DOWN again
- WHEN the second failure is written
- THEN the original ROOT event id is reused
- AND no new ROOT is created

#### Scenario: ICMP-packet-loss CREATE carries `created_at`

- GIVEN an ICMP-packet-loss CREATE payload is emitted
- WHEN the writer persists the new Event
- THEN the `created_at` property is set to the current timestamp
- AND the cursor can order this row by `created_at` without falling back to `id`

#### Scenario: ICMP-packet-loss recovery excludes PROPAGATED rows from direct match

- GIVEN an ICMP-packet-loss Event has `correlation_type='PROPAGATED'` and is currently OPEN
- WHEN the recovery writer runs for a CI whose packet-loss sample is OK
- THEN the row is NOT recovered by direct match
- AND the row is recovered only via its ROOT through the descendant branch when the ROOT transitions

### Requirement: Synthetic Threshold Breach on CI DOWN for Jitter/PacketLoss

When a CI has `availability=0` for the current poll cycle and the CI has a configured `icmp.jitter` or `icmp.packet_loss` metric, the poll loop MUST inject a synthetic `THRESHOLD_BREACH` row into the corresponding jitter/packet-loss update list before the refresh helpers run. The synthetic row MUST carry `severity='CRITICAL'`, `value=NULL`, and `message='Unable to measure: CI unreachable (availability=0)'`. The synthetic breach MUST flow through the same write path (advisory lock, refresh helper, Neo4j persistence) as a real breach.

#### Scenario: Synthetic breach fires when CI is DOWN and metric is configured

- GIVEN a CI has `availability=0` for the current cycle
- AND the CI has `icmp.jitter` configured with a `HAS_METRIC` relationship
- WHEN `poll_snmp()` runs the ICMP update fan-out
- THEN a synthetic row is appended to `jitter_updates` with `severity='CRITICAL'`, `value=NULL`, `message='Unable to measure: CI unreachable (availability=0)'`
- AND the refresh helper persists a CRITICAL `THRESHOLD_BREACH` Event for that CI/metric in the same cycle

#### Scenario: Synthetic breach fires when CI is DOWN and packet loss is configured

- GIVEN a CI has `availability=0` for the current cycle
- AND the CI has `icmp.packet_loss` configured with a `HAS_METRIC` relationship
- WHEN `poll_snmp()` runs the ICMP update fan-out
- THEN a synthetic row is appended to `packet_loss_updates` with `severity='CRITICAL'`, `value=NULL`, `message='Unable to measure: CI unreachable (availability=0)'`
- AND the refresh helper persists a CRITICAL `THRESHOLD_BREACH` Event for that CI/metric in the same cycle

#### Scenario: Synthetic breach does NOT fire when CI is UP

- GIVEN a CI has `availability=1` for the current cycle
- AND the CI has both `icmp.jitter` and `icmp.packet_loss` configured
- WHEN `poll_snmp()` runs the ICMP update fan-out
- THEN no synthetic row is appended to either update list
- AND the existing real-sample path produces the normal output

### Requirement: Synthetic Breach Scope Guard

The synthetic breach injection MUST NOT run for a (CI, metric) pair when the metric is not configured on the CI. The guard MUST check the existence of a `HAS_METRIC` relationship from the CI to the relevant `MetricDef` node before injecting. The guard MUST be evaluated after the candidate extraction pass and before the refresh helper call so that misconfigured or newly-deleted metrics never produce spurious events.

#### Scenario: Synthetic breach skipped when metric is not configured

- GIVEN a CI has `availability=0` for the current cycle
- AND the CI has `icmp.availability` configured but NOT `icmp.jitter`
- WHEN `poll_snmp()` runs the ICMP update fan-out
- THEN no synthetic row is appended to `jitter_updates` for that CI
- AND no Event is created for jitter on that CI

#### Scenario: Synthetic breach skipped when HAS_METRIC relationship is missing

- GIVEN a CI has `availability=0` for the current cycle
- AND the CI's metric configuration was just deleted (no `HAS_METRIC` row)
- WHEN `poll_snmp()` runs the ICMP update fan-out
- THEN no synthetic breach is created
- AND the refresh helper sees no candidate row

### Requirement: Recovery Predicate Sites for Jitter and PacketLoss

The existing recovery predicate contract that asserts `RECOVERED` eligibility on collection-failures and ICMP-availability writers MUST be extended to include ICMP-jitter and ICMP-packet-loss writers. The regression test MUST enumerate six predicate sites (collection-failures, ICMP-availability, ICMP-latency, ICMP-jitter, ICMP-packet-loss, plus the propagated-descendant branch) and fail if the eligible status set is narrowed on any site.

#### Scenario: Regression contract covers all six sites

- GIVEN the regression test enumerates predicate sites for recovery writers
- WHEN the test runs against the current implementation
- THEN all six sites are asserted to retain `RECOVERED` in their existing-event predicates
- AND the test passes
