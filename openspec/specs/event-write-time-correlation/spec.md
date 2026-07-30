# Event Write-Time Correlation Specification

## Purpose

Define deterministic same-cycle correlation for the production-default external SNMP worker so a parent failure and its dependent CI failures produce one ROOT Event with idempotent affected-CI annotations instead of N+1 ROOT Events.

## Requirements

### REQ-001: Same-Cycle Root Suppression

The external worker SHALL correlate collection failures, ICMP availability failures, and ICMP latency or threshold breaches observed in one collection cycle before dependent Event nodes are created. For a parent failure and N correlatable child failures, it SHALL persist one ROOT Event and SHALL NOT persist Event nodes for those children.

### REQ-002: Order-Independent Resolution

Correlation results SHALL be independent of observation input order. The worker SHALL identify and materialize eligible current-cycle root candidates before resolving dependent observations against persisted root Events.

### REQ-003: Affected-CI Attachment

Each correlated dependent CI SHALL be attached to the resolved ROOT Event through `affected_ci_ids`, and `affected_ci_count` SHALL equal the number of unique affected CI identifiers. Multiple affected metrics from the same child CI SHALL NOT duplicate that CI.

### REQ-004: Repeated-Cycle Idempotency

Repeated processing of the same unresolved failure state SHALL update the existing ROOT Event and affected-CI set without creating duplicate ROOT Events, child Events, affected-CI identifiers, or equivalent attachment effects.

### REQ-005: Safe Independent-Root Behavior

An observation SHALL remain ROOT when no eligible parent relationship or open parent Event can be resolved, when its metric is non-propagating, or when correlation lookup fails. A lookup failure SHALL NOT discard or delay the observation's normal Event write.

### REQ-006: Parent Recovery Consistency

When a parent recovery and dependent failures occur in the same cycle, the worker SHALL apply existing root recovery semantics and SHALL NOT attach new dependents to a parent Event that is no longer eligible after recovery processing. Dependents that cannot resolve another eligible open parent SHALL fall back to ROOT.

### REQ-007: Existing Coordination Invariants

All correlation passes SHALL preserve the existing Event advisory-lock ordering, transaction/session boundaries, collector identity fallback, Event deduplication, and root enrichment semantics.

## Scenario Matrix

| ID | Case | WHEN | THEN |
|---|---|---|---|
| SCN-001 | Parent then N children | WHEN a cycle observes a new parent failure before N correlatable child failures | THEN exactly one ROOT Event is persisted and N unique child CIs are attached to it |
| SCN-002 | Children then parent | WHEN the same observations arrive with all children before the parent | THEN the persisted ROOT Event and affected-CI set are identical to SCN-001 |
| SCN-003 | Interleaved order | WHEN parent and child observations arrive in any interleaving | THEN correlation output is independent of ordering and no child Event is persisted |
| SCN-004 | Multi-affected-metric parent | WHEN one parent failure has children with multiple affected metrics, including repeated metrics for one CI | THEN one ROOT Event contains each affected CI once and its count equals the unique CI total |
| SCN-005 | Repeated cycles | WHEN the same parent and child failures are processed in later cycles | THEN no duplicate Event or affected-CI attachment is created and the unique count remains stable |
| SCN-006 | No parent relationship | WHEN a failing CI has no resolvable eligible parent | THEN its failure is persisted as an independent ROOT Event |
| SCN-007 | Non-propagating metric | WHEN a child failure uses a metric that cannot propagate | THEN it is not attached to a parent and is handled as ROOT |
| SCN-008 | Parent recovery in same cycle | WHEN an open parent recovers in the cycle while a dependent failure is observed | THEN the recovered parent receives no new attachment and an unresolved dependent falls back to ROOT |
| SCN-009 | Lookup failure | WHEN correlation lookup raises an error or returns no usable result | THEN each unresolved observation safely follows ROOT write behavior without data loss |
| SCN-010 | Pass-3 attachment idempotency | WHEN affected-CI attachment is retried for the same root and dependent set | THEN `affected_ci_ids` contains unique IDs, `affected_ci_count` is unchanged, and no duplicate attachment effect occurs |
| SCN-011 | Event-family parity | WHEN equivalent parent and dependent failures occur in any supported external-worker event family | THEN each family enforces the same one-ROOT-plus-affected-CIs invariant |

## Out of Scope

- **P1:** Legacy in-process collector parity and changes to its persisted child-Event behavior.
- **P2:** Public API fields, event filtering, frontend KPI calculations, and monitoring presentation.
- **P3:** Leased queue writer parity, topology backfill, AP parent synthesis, or relationship remediation.
