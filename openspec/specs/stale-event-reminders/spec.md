# Stale Event Review Reminders Specification

## Purpose

Advisory surface for events lingering `OPEN`/`ACK` after their condition changed. Events MUST NOT be silently closed; this capability exposes read-only detection plus three audit-emitting quick actions (`dismiss`, `snooze`, `escalate`) that never mutate `Event`. First slice targets `event_type = COLLECTION_FAILURE` with `failure_family = SNMP_NO_RESPONSE`.

## Requirements

### Requirement: Stale event detection rules

The system MUST flag an `OPEN`/`ACK` event as stale when any reason code holds: `older_than_threshold` (`(now - coalesce(last_seen, created_at)) > STALE_EVENT_REMINDER_AGE_HOURS`, 24h default), `no_refresh_in_window` (`last_seen` not refreshed within `STALE_EVENT_REMINDER_REFRESH_WINDOW_HOURS`, 6h default), or `link_missing` (`OPTIONAL MATCH` against `:HAS_EVENT`/`:TRIGGERED_BY` returns no row). Detection MUST be read-only Cypher; no `Event`, `CI`, or `MetricDef` may be mutated.

#### Scenario: Open event past age threshold appears as older_than_threshold

- GIVEN an `OPEN` `COLLECTION_FAILURE` event with `failure_family = SNMP_NO_RESPONSE`, `last_seen = now - 25h`
- WHEN detection runs at default age threshold (24h)
- THEN it SHALL appear with `reason_code = older_than_threshold`; Event properties SHALL NOT be modified.

#### Scenario: Open event without recent refresh appears as no_refresh_in_window

- GIVEN an `OPEN` `COLLECTION_FAILURE` event with `last_seen = now - 8h`, 6h refresh window
- WHEN detection runs and event is younger than age threshold
- THEN it SHALL appear with `reason_code = no_refresh_in_window`.

#### Scenario: Event with missing CI link appears as link_missing

- GIVEN an `OPEN` `COLLECTION_FAILURE` event whose `:HAS_EVENT` edge points to a deleted `CI`
- WHEN detection runs
- THEN it SHALL appear with `reason_code = link_missing` regardless of age.

### Requirement: Recommendations endpoint and schema-versioned payload

The system MUST expose `GET /api/events/recommendations` (gated by `EVENT_VIEW`) returning paginated rows under schema id `stale-event-reminder-recommendation.v1`. Each row MUST include `event_id`, `title`, `severity`, `status`, `ci_id`, `ci_name`, `metricdef_id`, `metricdef_name`, `age_hours`, `last_seen`, `refresh_status`, `reason_code`, `quick_actions`. CI/MetricDef fields are nullable. The endpoint MUST be read-only; no write, ACK, close, prune, or mutate on any `Event`.

#### Scenario: Endpoint returns schema-versioned rows without mutating events

- GIVEN three matching stale events
- WHEN `GET /api/events/recommendations?limit=10` is called
- THEN rows SHALL be wrapped under `schema_version = stale-event-reminder-recommendation.v1`; `Event.status`, `Event.last_seen`, and edges SHALL be unchanged.

### Requirement: Quick actions write audit rows without mutating events

The system MUST accept `POST /api/events/recommendations/{event_id}/{dismiss|snooze|escalate}` (gated by `EVENT_VIEW`). Each handler MUST call `audit_service.record_critical_change()` with `event_type` ∈ {`STALE_EVENT_REMINDER_DISMISS`, `STALE_EVENT_REMINDER_SNOOZE`, `STALE_EVENT_REMINDER_ESCALATE`} and context keys (`event_id`, `reason_code`, `snooze_until`). Handlers MUST NOT mutate the `Event` node. `snooze` MUST record `snooze_until = now + STALE_EVENT_REMINDER_SNOOZE_TTL_HOURS` (24h default) in audit context only.

#### Scenario: Dismiss writes audit row and leaves event as-is

- GIVEN an `OPEN` event in recommendations
- WHEN an operator clicks `dismiss`
- THEN an audit row with `event_type = STALE_EVENT_REMINDER_DISMISS` SHALL be written; the event SHALL be unchanged.

#### Scenario: Snooze writes audit row with TTL and leaves event as-is

- GIVEN an `OPEN` event in recommendations
- WHEN an operator clicks `snooze`
- THEN an audit row with `event_type = STALE_EVENT_REMINDER_SNOOZE` SHALL include `snooze_until`; event SHALL remain `OPEN`.

#### Scenario: Escalate writes audit row and leaves event as-is

- GIVEN an `OPEN` event in recommendations
- WHEN an operator clicks `escalate`
- THEN an audit row with `event_type = STALE_EVENT_REMINDER_ESCALATE` SHALL be written; the event SHALL be unchanged.

### Requirement: Configuration and kill-switch

The system MUST expose `StaleEventReminderSettings` (mirroring `EventPruneSettings`) with envs `STALE_EVENT_REMINDER_ENABLED` (`true`), `STALE_EVENT_REMINDER_AGE_HOURS` (24), `STALE_EVENT_REMINDER_REFRESH_WINDOW_HOURS` (6), `STALE_EVENT_REMINDER_SNOOZE_TTL_HOURS` (24). When `STALE_EVENT_REMINDER_ENABLED=false`, recommendations MUST return empty; quick actions MUST return `503`.

#### Scenario: Kill-switch returns empty list

- GIVEN `STALE_EVENT_REMINDER_ENABLED=false`
- WHEN `GET /api/events/recommendations` is called
- THEN the response MUST contain zero rows.

### Requirement: No auto-close, no auto-prune, no auto-ACK

The system MUST NOT auto-close, auto-prune, auto-ACK, or mutate `Event` state from any path this capability introduces. `Event` mutation is the exclusive responsibility of operators via existing event lifecycle endpoints.

#### Scenario: Recommendation surface never triggers lifecycle changes

- GIVEN a stale event in recommendations
- WHEN an operator only views, dismisses, snoozes, or escalates
- THEN `Event.status` SHALL remain `OPEN` or `ACK`; no `Event` write path SHALL execute.