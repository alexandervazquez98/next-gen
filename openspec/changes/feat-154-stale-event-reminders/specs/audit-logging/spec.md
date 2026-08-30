# Delta for audit-logging

## ADDED Requirements

### Requirement: Stale event reminder audit events

The system MUST emit audit rows for the three stale-event-reminder quick actions using `record_critical_change()` with `event_type` strings `STALE_EVENT_REMINDER_DISMISS`, `STALE_EVENT_REMINDER_SNOOZE`, and `STALE_EVENT_REMINDER_ESCALATE`. The audit context MUST use the allow-listed keys `event_id`, `reason_code`, and `snooze_until` only. The audit context MUST NOT contain raw refresh/access tokens, cookies, authorization headers, request bodies, or any field flagged as sensitive secret material.

#### Scenario: Dismiss emits an audit row with redacted context

- GIVEN an operator triggers the `dismiss` quick action on a stale event recommendation
- WHEN the audit row is written
- THEN the row MUST have `event_type = STALE_EVENT_REMINDER_DISMISS` and `target_type = Event`
- AND the context MUST contain `event_id` and `reason_code`
- AND the context MUST NOT contain tokens, cookies, authorization headers, or raw request bodies.

#### Scenario: Snooze emits an audit row including TTL and redacted context

- GIVEN an operator triggers the `snooze` quick action
- WHEN the audit row is written
- THEN the row MUST have `event_type = STALE_EVENT_REMINDER_SNOOZE`
- AND the context MUST contain `event_id`, `reason_code`, and `snooze_until`
- AND the context MUST NOT contain sensitive secret material.

#### Scenario: Escalate emits an audit row with redacted context

- GIVEN an operator triggers the `escalate` quick action
- WHEN the audit row is written
- THEN the row MUST have `event_type = STALE_EVENT_REMINDER_ESCALATE`
- AND the context MUST contain `event_id` and `reason_code`
- AND the context MUST NOT contain sensitive secret material.

#### Scenario: Quick action is denied when kill-switch is off

- GIVEN `STALE_EVENT_REMINDER_ENABLED=false`
- WHEN an operator triggers any quick action
- THEN the response MUST be `503` and no audit row SHALL be written.