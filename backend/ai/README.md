# Backend AI prompt sources

This folder contains NEX-GEN-owned prompt and harness documentation for the
backend AI chat path. LM Studio does not load these Markdown files directly.

## Load model

1. Backend reads the prompt sources server-side.
2. Backend composes a compact `system` message for `/v1/chat/completions`.
3. Backend pre-resolves explicit allowed intents, such as `availability_check`
   and `event_list`, when authorized.
4. Backend includes the harness result in the final chat completion request.

The current runtime does not send an OpenAI-compatible `tools` array or execute
an LM Studio tool-call loop. That is reserved for a future slice.

The frontend cannot choose identity files, tool definitions, LM Studio URL, or
model.

## Files

| Path | Purpose |
| --- | --- |
| `identity/Soul.md` | Base read-only NEX-GEN assistant identity. |
| `identity/scope.md` | Permissions and safety boundaries. |
| `identity/context-policy.md` | Context budget and ordering rules. |
| `identity/session-bootstrap.md` | First interaction flow. |
| `tools/README.md` | Tool catalog summary. |
| `tools/availability_check.md` | Bounded ping harness contract. |
| `tools/event-list.md` | Bounded event-list harness contract. |
