# ICMP Latency Threshold Environment Specification

## Purpose

Ensure containerized ICMP latency threshold consumers receive operator-configured warning and critical latency thresholds instead of silently falling back to application defaults.

## Requirements

### Requirement: Containerized Threshold Propagation

The system MUST provide `ICMP_LATENCY_WARNING_MS` and `ICMP_LATENCY_CRITICAL_MS` to every containerized service that evaluates ICMP latency thresholds.

#### Scenario: Operator-configured thresholds are available in affected containers

- GIVEN an operator configures ICMP latency warning and critical threshold values for the Compose deployment
- WHEN the affected services are rendered or started
- THEN each service that evaluates ICMP latency thresholds MUST receive both configured values in its environment
- AND ICMP latency evaluation MUST use those values through the existing settings contract

#### Scenario: Defaults are propagated when operators omit threshold values

- GIVEN an operator does not configure ICMP latency threshold values for the Compose deployment
- WHEN the affected services are rendered or started
- THEN each service that evaluates ICMP latency thresholds MUST receive warning and critical values matching the documented defaults
- AND behavior MUST remain equivalent to the existing default threshold behavior

#### Scenario: Non-consuming services remain unaffected

- GIVEN a containerized service does not evaluate ICMP latency thresholds
- WHEN the Compose deployment is rendered
- THEN the change SHOULD NOT require that service to receive ICMP latency threshold environment variables

### Requirement: Configuration-Only Behavior Preservation

The system MUST preserve existing ICMP latency threshold parsing, validation, defaults, and process-cached behavior.

#### Scenario: Application settings remain the source of validation

- GIVEN ICMP latency threshold environment values are present in affected containers
- WHEN the application reads ICMP latency settings
- THEN existing parsing and validation rules MUST apply without changed product semantics

#### Scenario: Invalid threshold values follow existing failure behavior

- GIVEN invalid ICMP latency threshold values are provided to an affected container
- WHEN the application reads ICMP latency settings
- THEN the existing invalid-configuration behavior MUST be preserved
