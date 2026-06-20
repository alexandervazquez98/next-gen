# `event_list` harness

Provider-neutral read-only event listing for the in-app AI chat.

## Purpose

Answer narrow operator questions such as:

- "List active events."
- "List open critical events."
- "What events have not recovered?"
- "Show current CI alerts."

## Input intent

```json
{
  "type": "event_list",
  "status": "OPEN",
  "severity": "CRITICAL",
  "limit": 10
}
```

Alias: `active_events` uses the same backend executor.

Allowed `status` values:

- `ACTIVE`: open and acknowledged events.
- `CONSOLE`: open, acknowledged, and recovered events.
- `OPEN`, `ACK`, `CLOSED`, `RECOVERED`: exact status filters.

Allowed `severity` values are `CRITICAL`, `WARNING`, and `INFO`. Omit severity
to list all severities for the selected status.

`limit` is bounded by backend schema from 1 to 25.

## Permission

Requires event visibility through either normal `EVENT_VIEW` permission or the
AI-scoped `AI_VIEW_ALL` permission.

## Output metadata

The harness returns compact JSON:

```json
{
  "type": "event_list",
  "status": "OPEN",
  "severity": "CRITICAL",
  "limit": 10,
  "count": 2,
  "truncated": false,
  "events": []
}
```

Each event may include only summary-safe fields: event id, CI id/name/hostname,
location, metric id/name/protocol, status, severity, message, event type,
correlation fields, `created_at`, and `last_seen`.

## Follow-up behavior

The backend stores chat exchanges and harness metadata. A follow-up such as
"verify if they are working" may use the latest `event_list` result to run a
bounded `availability_check_batch` against the listed CIs, if the user has the
required diagnostic permissions.

## Provider boundary

This harness is not tied to Gemma, Gemini, LM Studio, or any provider-native
function-calling format. Backend code executes the tool and appends the result as
provider-neutral chat context.

A future provider adapter may expose the same intent schema as OpenAI tools,
Gemini function declarations, or Ollama-compatible tools.

## Raven boundary

This harness lists NEX-GEN events only. A future Raven bridge should map event
summaries into Raven-normalized payloads and let Raven CLI/API validate ingest.
The model must not invent Raven `ci_id` values or write Raven storage directly.
