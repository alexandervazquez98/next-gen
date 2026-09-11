# Metric Values Retention Specification

## Purpose

Bound the unbounded growth of the TimeScaleDB `metric_values` hypertable — the primary store for SNMP polling metrics — by enforcing a configurable retention window that drops chunks older than the operator-configured interval. Issue #457 documented storage-growth evidence: a `pg_dump -Fc` step that ran in <30 s on an empty install expanded to 5+ minutes and produced >250 MB dumps on established deployments, blocking operator iteration in every `safe-rebuild.sh` window. This capability adds a forward-looking retention policy only; it does not backfill or retroactively prune existing rows.

## Requirements

### Requirement: REQ-MVR-001 — TimeScaleDB retention policy on `metric_values`

The system MUST apply a TimeScaleDB retention policy to the `metric_values` hypertable, anchoring the window to the configured interval and re-applying the policy defensively on every scheduler tick.

#### Scenario: Policy applied on first boot inside `create_hypertable`

- GIVEN a fresh install where the `metric_values` hypertable is created by `create_hypertable('metric_values', 'time', if_not_exists => TRUE)`
- WHEN boot-time retention application runs after hypertable creation and retention is enabled
- THEN the system MUST invoke `add_retention_policy('metric_values', INTERVAL '<N> days')` idempotently
- AND the call MUST NOT raise when a matching policy already exists.

#### Scenario: Scheduler re-applies a missing policy defensively

- GIVEN the `metric_values` policy was removed or never installed on an established deployment
- WHEN the scheduler entrypoint runs on its tick
- THEN the system MUST detect the missing policy and re-create it
- AND subsequent scheduler ticks MUST find exactly one matching policy for the hypertable.

### Requirement: REQ-MVR-002 — Operator-configurable retention interval

The system MUST read the retention interval from `METRIC_RETENTION_DAYS` (default 90, range 1..3650) and reject invalid values by falling back to the default without raising.

#### Scenario: Default interval applies when env var is unset

- GIVEN `METRIC_RETENTION_DAYS` is not set
- WHEN the scheduler entrypoint initializes
- THEN the configured interval MUST be 90 days.

#### Scenario: Operator override of 30 days takes effect

- GIVEN `METRIC_RETENTION_DAYS=30`
- WHEN the policy is applied
- THEN the `config` column of `timescaledb_information.jobs` MUST read `30 days 00:00:00`.

#### Scenario: Invalid value preserves the default

- GIVEN `METRIC_RETENTION_DAYS` is set to a non-integer or out-of-range value
- WHEN the settings are loaded
- THEN the system MUST fall back to the 90-day default
- AND MUST NOT raise an exception during startup.

### Requirement: REQ-MVR-003 — Kill-switch via `METRIC_RETENTION_ENABLED`

The system MUST register the scheduler entrypoint only when `METRIC_RETENTION_ENABLED` is truthy (default `true`), mirroring `EVENT_PRUNE_ENABLED`.

#### Scenario: Enabled by default registers the entrypoint

- GIVEN `METRIC_RETENTION_ENABLED` is unset or `true`
- WHEN `backup_scheduler.add_job(...)` is invoked during startup
- THEN the entrypoint MUST be registered
- AND the registered job id MUST identify the metric retention job.

#### Scenario: Disabled by env var skips registration

- GIVEN `METRIC_RETENTION_ENABLED=false`
- WHEN startup completes
- THEN `backup_scheduler` MUST NOT contain the metric retention job
- AND no retention-related errors MUST be logged on the disabled code path.

### Requirement: REQ-MVR-004 — Idempotent `apply_metric_retention`

The system MUST make `apply_metric_retention(retention_days: int)` idempotent — repeated calls with the same interval MUST NOT create duplicate policies and MUST NOT raise.

#### Scenario: Two consecutive calls produce a single job row

- GIVEN a clean `metric_values` hypertable with no retention policy
- WHEN `apply_metric_retention(90)` is called twice in succession
- THEN `timescaledb_information.jobs` MUST contain exactly one row whose `hypertable_name = 'metric_values'`.

#### Scenario: Same-interval re-application does not error

- GIVEN an existing `metric_values` retention policy with interval 30 days
- WHEN `apply_metric_retention(30)` is invoked again
- THEN the call MUST NOT raise
- AND the existing policy MUST remain unchanged.

### Requirement: REQ-MVR-005 — Retention excludes out-of-window rows from query results

The system MUST guarantee that rows older than the configured interval are excluded from standard `metric_values` queries once the policy is active.

#### Scenario: Row older than window is excluded

- GIVEN the retention policy interval is 30 days and the policy is active
- WHEN a smoke-scan query `SELECT * FROM metric_values WHERE ...` runs against an inserted row with `time` 100 days ago
- THEN the inserted row MUST NOT be returned.

#### Scenario: Row within window is queryable

- GIVEN the retention policy interval is 30 days and the policy is active
- WHEN the same query runs against a row with `time` 1 day ago
- THEN the inserted row MUST be returned normally.

### Requirement: REQ-MVR-006 — Forward-looking retention semantics

The system MUST treat the retention policy as forward-looking only; the policy MUST NOT retroactively delete rows that were already older than the window at the moment of application.

#### Scenario: Pre-existing old rows survive application and drop on chunk roll-over

- GIVEN a `metric_values` hypertable that already contains rows older than the configured interval before the policy is applied
- WHEN the policy is applied and subsequent chunk roll-overs occur
- THEN rows older than the window at policy-application time MUST remain queryable until their chunk is dropped by the scheduler
- AND no out-of-process purge or backfill is added to accelerate removal.