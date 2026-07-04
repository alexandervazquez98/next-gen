# AI Operator Guide

NEX-GEN AI chat is backend-owned. The frontend sends `/api/ai/chat`; the backend resolves permissions, context, prompt files, harness results, and the LM Studio request.

## Quick path

1. Start LM Studio and enable its OpenAI-compatible local server.
2. Configure the `LM_STUDIO_*` variables in `.env`.
3. Verify the OpenAI-compatible `/v1/chat/completions` endpoint with curl.
4. Use the NEX-GEN AI console; operational harnesses remain backend-controlled.

## LM Studio connection

NEX-GEN uses LM Studio through the OpenAI-compatible `/v1/chat/completions` endpoint. It does not use LM Studio native stateful chat as the primary integration path. The backend owns chat history and sends bounded `messages` on each request.

| Variable | Default | Notes |
|---|---:|---|
| `LM_STUDIO_ENABLED` | `false` | Enables the backend proxy. Keep disabled unless LM Studio is available. |
| `LM_STUDIO_BASE_URL` | Backend fallback: `http://localhost:1234/v1`; Compose `.env.example`: `http://host.docker.internal:1234/v1` | Standalone backend uses the localhost fallback when no environment value is set. Docker/Compose uses `host.docker.internal` so the container reaches LM Studio on the Docker host. For a separate LM Studio machine, use its LAN/VPN IP. |
| `LM_STUDIO_MODEL` | `local-model` | Must match the model loaded in LM Studio. |
| `LM_STUDIO_TIMEOUT_SECONDS` | `15` | Backend timeout, capped at `120` seconds. |
| `LM_STUDIO_MAX_TOKENS` | `800` | Completion cap, bounded `1..4096`. Raise for longer answers; expect more latency. |

Tune model size, context length, timeout, and max tokens together. Larger context and completion budgets improve completeness but can make local inference slow or unstable.

## Prompt and identity sources

LM Studio does not read NEX-GEN Markdown files directly. The backend loads selected files from `backend/ai/`, composes a compact system prompt, and sends it through the OpenAI-compatible `messages` array.

Key identity files:

| File | Purpose |
|---|---|
| `backend/ai/identity/Soul.md` | Base assistant identity. |
| `backend/ai/identity/scope.md` | Permissions and safety boundaries. |
| `backend/ai/identity/context-policy.md` | Context budget and ordering rules. |
| `backend/ai/identity/session-bootstrap.md` | First-interaction flow. |

Identity files grant no execution or write authority. The model must not directly write to Raven, SQLite, Neo4j, Postgres, the CMDB, or operational systems.

For operator-owned prompt overrides, use [`docs/ai-prompts-runbook.md`](ai-prompts-runbook.md). It explains the bundled defaults, Docker bind mount, first-boot seed, and edit workflow.

## Harness and tool boundary

Current harnesses are backend-owned and pre-resolved:

1. Backend infers an allowed intent such as event listing or availability check.
2. Backend verifies the user's permission before any harness execution.
3. Backend resolves targets from stored NEX-GEN data; the browser cannot provide shell commands, IP targets, base URLs, or models.
4. Backend executes the bounded harness or prepares compact operational facts.
5. Backend injects the result into the prompt or renders deterministic template output for supported harnesses.
6. Backend persists chat metadata and supports follow-up resolution from server-side history.

NEX-GEN does not send an OpenAI `tools` array or run an LM Studio tool-call loop by default. Provider-native toolcalling is a future adapter path, not the primary runtime contract for this change.

## Reasoning models and deterministic rendering

Some reasoning-capable local models return useful `reasoning_content` but empty assistant `content`, especially when the completion budget is too small. For deterministic harness types, NEX-GEN can render a safe backend-owned response from already-resolved facts instead of depending on model prose. For non-harness chat, increase `LM_STUDIO_MAX_TOKENS`, reduce prompt/context size, or choose a model that emits final content reliably.

## Response policies and templates

Runtime policy and template files live under `backend/ai/policies/` and `backend/ai/templates/`. They document boundaries such as no invented harness execution, no unsupported root-cause claims, bounded ping semantics, and event-list formatting.

Edit operator-owned prompt copies through the runbook workflow; treat tracked `backend/ai/` files as bundled defaults that change through code review.

## Related docs

- [`docs/lm-studio-ai-chat.md`](lm-studio-ai-chat.md) — LM Studio setup, curl verification, endpoint flow, and troubleshooting.
- [`docs/ai-prompts-runbook.md`](ai-prompts-runbook.md) — prompt override lifecycle and Docker bind-mount workflow.
- [`backend/ai/README.md`](../backend/ai/README.md) — bundled AI file map and load model.
- [`backend/ai/policies/lmstudio-runtime.md`](../backend/ai/policies/lmstudio-runtime.md) — runtime policy for LM Studio and reasoning-model behavior.
