# Tunnel Monitoring Specification

## Purpose

Define backend-only normalized health for eligible VPN, SD-WAN, and satellite tunnel links without changing node metrics, events, CI status, or frontend behavior.

## Requirements

### Requirement: Authoritative Tunnel State Rollup

The system MUST normalize Slice 2 tunnel health from SNMP/CLI authority only: authority `UP` SHALL produce `UP`, authority `DOWN` SHALL produce `DOWN`, and missing authority SHALL produce `UNKNOWN`. ICMP/public-IP liveness or RTT MUST remain context only and MUST NOT produce normalized `DEGRADED` or `DOWN`.

#### Scenario: Authority reports down

- GIVEN an eligible tunnel link has SNMP/CLI state `DOWN`
- WHEN tunnel health is normalized
- THEN normalized status MUST be `DOWN`
- AND ICMP liveness or RTT MUST NOT override it

#### Scenario: Authority up with poor ICMP context

- GIVEN an eligible tunnel link has SNMP/CLI state `UP`
- AND ICMP context is failed, unavailable, or exceeds accepted RTT thresholds
- WHEN tunnel health is normalized
- THEN normalized status MUST be `UP`
- AND ICMP liveness or RTT MUST remain separate context

#### Scenario: Authority unavailable

- GIVEN no SNMP/CLI authority sample is available for an eligible tunnel link
- WHEN tunnel health is normalized
- THEN normalized status MUST be `UNKNOWN`

### Requirement: ICMP Context Semantics

The system SHALL expose deterministic ICMP/public-IP liveness and RTT context only when available. Missing endpoint `public_ip`, ICMP failure, poor RTT, or missing ICMP sample MUST set `icmp.available`, `icmp.latency_ms`, `icmp.error`, and `icmp.reason` predictably and MUST NOT change the authority-driven normalized status.

#### Scenario: Missing public IP

- GIVEN an eligible tunnel link has an endpoint without `public_ip`
- WHEN tunnel health is read
- THEN ICMP context MUST report `available=false`, `latency_ms=null`, and `reason=missing_public_ip`
- AND normalized status MUST remain based only on SNMP/CLI authority

#### Scenario: No ICMP sample

- GIVEN an eligible tunnel link has no ICMP sample
- WHEN tunnel health is read
- THEN ICMP context MUST report `available=false`, `latency_ms=null`, and `reason=no_sample`

#### Scenario: ICMP failure while authority is up

- GIVEN SNMP/CLI state is `UP`
- AND ICMP liveness is failed for a public endpoint
- WHEN tunnel health is normalized
- THEN normalized status MUST remain `UP`
- AND liveness failure MUST be visible as context

### Requirement: Latest Tunnel Health Read Model

The system MUST persist and read the latest normalized tunnel health for an eligible tunnel link. Reads SHALL return deterministic fields: `status`, `authority.state`, `authority.source`, `authority.observed_at`, `authority.reason`, `icmp.available`, `icmp.latency_ms`, `icmp.error`, `icmp.reason`, and `observed_at`.

#### Scenario: Latest sample returned

- GIVEN an eligible tunnel link has a latest normalized health sample
- WHEN a client reads tunnel health
- THEN the response MUST include status, authority context, ICMP context, and observed timestamp

#### Scenario: No sample exists

- GIVEN an eligible tunnel link exists but has no health sample
- WHEN a client reads tunnel health
- THEN the response MUST report `status=UNKNOWN`, `authority.reason=no_sample`, `authority.state=null`, and `observed_at=null`

### Requirement: Tunnel Health Endpoint

The backend SHALL expose an authenticated read endpoint for a single eligible tunnel link's latest health. The endpoint MUST reject malformed identifiers, return not found for non-tunnel, missing, or inaccessible links, enforce backend user/location scoping, and MUST NOT require vendor-specific adapters.

#### Scenario: Read eligible tunnel health

- GIVEN a link is eligible for tunnel monitoring
- WHEN a client requests its tunnel health endpoint
- THEN the backend MUST return its latest normalized health

#### Scenario: Inaccessible link is rejected server-side

- GIVEN a non-admin user lacks location scope for a tunnel link
- WHEN the user requests that link's health endpoint
- THEN the backend MUST return not found without leaking link health


### Requirement: Pipeline Isolation

Tunnel health normalization SHALL NOT mutate existing node metric, event, or CI status pipelines.

#### Scenario: Health update is isolated

- GIVEN tunnel health is normalized and saved
- WHEN existing metric, event, and CI status records are inspected
- THEN no node metric, event lifecycle, or CI status mutation is caused by tunnel health
