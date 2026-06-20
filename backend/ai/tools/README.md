# AI tool system

This catalog tells the assistant which backend-owned tools may exist and how to
talk about them.

## Runtime contract

- The assistant does not execute tools directly.
- The frontend may send a structured intent to `/api/ai/chat`.
- The backend validates permission and resolves targets from stored NEX-GEN data.
- The backend runs the allow-listed harness and appends `Harness result`.
- The assistant may interpret a harness result, but must not invent tool output.
- If no tool result is present, say the diagnostic was not executed.

## Tool families

### Network diagnostics

- Prompt name: `network.basic`
- Status: partial
- Purpose: reachability and path checks.
- Contract: `tools/network-basic.md`

### Event listing

- Prompt name: `event_list` / `active_events`
- Status: active
- Purpose: list bounded active or console event summaries.
- Contract: `tools/event-list.md`

### Visualization

- Prompt name: `visualization.context`
- Status: planned
- Purpose: explain UI topology, events, and metrics.
- Contract: `tools/visualization.md`

## Current backend implementation

The active backend implementation supports `availability_check`,
`availability_check_batch`, and `event_list`. Availability checks run bounded
ping against CI targets resolved from the CMDB. `event_list` returns bounded and
optionally severity-filtered event summaries from NEX-GEN event storage.

Other tools in this catalog are scope definitions until their backend harnesses
are implemented.
