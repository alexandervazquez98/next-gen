# Visualization context tools

Visualization tools help the assistant explain what the operator sees in NEX-GEN
UI views. They do not mutate data.

## Scope

Planned visualization context families:

- `topology_view`: explain visible CI nodes, relationships, status colors,
  clusters, and dependency direction from provided UI context.
- `event_view`: explain selected incidents, severity, lifecycle state, comments,
  acknowledgements, diagnostics, and likely next steps.
- `metric_view`: explain metric charts, availability signals, recent samples,
  thresholds, and anomalies from provided context.

## Safety rules

- Treat visualization context as a snapshot, not the full source of truth.
- Do not infer hidden nodes, hidden events, credentials, or unseen topology.
- Do not claim a visualization action happened unless a result was provided.
- Prefer concise operator guidance: visible facts, meaning, and next inspection.

## Current status

This is a prompt contract only. The current backend chat path can receive
selected UI context in the user message, but it does not expose a separate
visualization harness result yet.
