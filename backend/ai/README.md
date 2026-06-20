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

## User overrides (operator-owned prompts)

The files in this folder are the **bundled defaults**: the foundations NEX-GEN
ships. Operators are expected to reshape them to their own network's needs, so
at runtime the backend reads from a separate, operator-owned folder instead of
this read-only tree.

- Set `AI_PROMPTS_DIR` to point at the operator folder.
  - Leave it empty to keep legacy behavior (read these bundled files in place).
- On first boot, if the folder is empty, the backend **seeds** it with a full
  copy of this tree. After that the folder is a **frozen snapshot**: the backend
  never overwrites or adds files. Edit them freely.
- For any file missing from the operator folder, the loader falls back to the
  bundled default here (invisible safety net), so new features that need a new
  `.md` keep working.

In Docker the container path is `/data/ai`, bind-mounted to
`${AI_PROMPTS_DIR_HOST:-.docker/ai}` on the host — edit the files on the host
and restart the container. In local dev, set `AI_PROMPTS_DIR=./.ai` (gitignored).

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
