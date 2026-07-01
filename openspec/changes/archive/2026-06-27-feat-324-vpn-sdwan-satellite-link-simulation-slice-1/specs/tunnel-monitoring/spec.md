# Tunnel Monitoring Specification

> **NOTE**: Tunnel-monitoring spec is pending Slice 2 implementation. Not synced to canonical specs tree. Slice 2's archive will sync this spec to `openspec/specs/tunnel-monitoring/spec.md` once its polling/health work lands.

## Purpose

Define Slice 2 tunnel health polling and read API for VPN, SD-WAN, and satellite links. SNMP/CLI is authoritative for `UP` and `DOWN`; ICMP from `public_ip` supplies degradation context only.

## Requirements

### Requirement: Tunnel State Collection

The system MUST poll tunnel state for modeled tunnel links using SNMP or CLI placeholders selected by vendor metadata. Vendor-specific OIDs/commands MAY be configured later and MUST NOT be hard-coded as complete coverage in this change.

#### Scenario: [Slice 2] Collect SNMP tunnel state

- GIVEN a tunnel link has SNMP polling metadata
- WHEN the polling cycle runs
- THEN the sample records SNMP tunnel state
- AND SNMP remains authoritative for `UP`/`DOWN`

#### Scenario: [Slice 2] Unknown vendor uses placeholder

- GIVEN no vendor-specific OID or CLI command exists
- WHEN tunnel polling runs
- THEN health reports partial data instead of inventing vendor coverage

### Requirement: ICMP Degradation Context

The system MUST measure ICMP liveness and RTT against the related CI `public_ip` when present. ICMP MUST NOT mark a tunnel `DOWN`.

#### Scenario: [Slice 2] ICMP enriches UP tunnel

- GIVEN SNMP/CLI reports tunnel `UP` and ICMP RTT is normal
- WHEN health is rolled up
- THEN health is `UP`
- AND SNMP/CLI is the authority for `UP`

#### Scenario: [Slice 2] ICMP loss does not mark DOWN

- GIVEN SNMP/CLI reports tunnel `UP` and ICMP is unreachable
- WHEN health is rolled up
- THEN health is not `DOWN`
- AND SNMP/CLI remains authoritative for `UP`/`DOWN`

### Requirement: Health Rollup State Machine

The system MUST expose health `UP`, `DEGRADED`, or `DOWN`: `UP` when SNMP/CLI is up and ICMP is normal; `DEGRADED` when SNMP/CLI is up and ICMP latency or intermittent failure is unhealthy; `DOWN` only when SNMP/CLI reports down.

#### Scenario: [Slice 2] High latency degrades UP tunnel

- GIVEN SNMP/CLI reports tunnel `UP` and ICMP latency is above threshold
- WHEN health is rolled up
- THEN health is `DEGRADED`
- AND SNMP/CLI remains authoritative for `UP`/`DOWN`

#### Scenario: [Slice 2] SNMP down overrides ICMP success

- GIVEN SNMP/CLI reports tunnel `DOWN` and ICMP responds normally
- WHEN health is rolled up
- THEN health is `DOWN`
- AND ICMP does not override SNMP/CLI authority

### Requirement: Tunnel Health Endpoint and Samples

The system MUST provide `GET /api/tunnels/{link_id}/health` returning `link_id`, `medium`, `health`, `last_sample_at`, `health_source`, `rtt_ms`, and partial-data/error fields when available.

#### Scenario: [Slice 2] Read latest tunnel health

- GIVEN a tunnel has collected samples
- WHEN a client requests `/api/tunnels/{link_id}/health`
- THEN the response returns the latest health sample fields

#### Scenario: [Slice 2] SNMP timeout returns partial health

- GIVEN SNMP/CLI times out but ICMP has data
- WHEN health is requested
- THEN the response reports partial data or unknown authority
- AND ICMP does not mark the tunnel `DOWN`

#### Scenario: [Slice 2] No public IP skips ICMP context

- GIVEN neither related CI has `public_ip`
- WHEN tunnel health is rolled up
- THEN health is based on SNMP/CLI only
- AND the response indicates ICMP was unavailable
