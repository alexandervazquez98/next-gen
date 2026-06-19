# LM Studio AI Chat Integration

NEX-GEN AI chat now uses a backend proxy to talk to LM Studio's OpenAI-compatible local API. The browser only calls `/api/ai/chat`; it never receives or controls the LM Studio base URL or model.

## Quick path

1. Start LM Studio and enable the local server.
2. Configure the backend environment variables below.
3. Send chat from the NEX-GEN AI console; the backend posts to `/v1/chat/completions`.

## Environment

| Variable | Required | Example | Notes |
|---|---:|---|---|
| `LM_STUDIO_ENABLED` | Yes | `true` | Keeps the proxy opt-in. |
| `LM_STUDIO_BASE_URL` | Yes | `http://localhost:1234/v1` | Use `host.docker.internal` or a LAN IP from Docker. |
| `LM_STUDIO_MODEL` | Yes | `qwen2.5-coder-7b-instruct` | Must match a model loaded in LM Studio. |
| `LM_STUDIO_TIMEOUT_SECONDS` | No | `15` | Bounded backend request timeout. |

## Docker networking

Inside the backend container, `localhost` is the container itself, not your host machine. Use one of these instead:

```env
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1
# or
LM_STUDIO_BASE_URL=http://192.168.1.50:1234/v1
```

The Compose backend service maps `host.docker.internal` to the Linux Docker host gateway so the default URL works on Linux as well as Docker Desktop environments.

## Endpoint flow

| Step | Component | Action |
|---:|---|---|
| 1 | Frontend | `chatWithAIAgent(query, context)` posts to `/api/ai/chat`. |
| 2 | Backend | Auth validates the current user cookie/session. |
| 3 | Harness | Optional `availability_check` first requires diagnostic permission, then resolves a stored CI and runs one bounded ping. |
| 4 | LM Studio proxy | Backend sends a non-streaming OpenAI-compatible chat completion request. |
| 5 | Persistence | Backend stores the user message, assistant answer, timestamp, model, context, and harness metadata. |

## Safe harness behavior

The first harness is intentionally small: CI availability check by ping. The browser may request an `availability_check` intent with a CI id/name, but it cannot provide a shell command, host target, base URL, or model. The backend resolves the CI from stored CMDB data and validates the stored IP/hostname before running `ping -c 1 -W 2`.

Persisted chat history is stored server-side for authenticated application users who already have backend data access. This slice does not add a separate retention policy or encryption layer for AI chat records; deployers should treat chat history as operational data and align database access, backups, and cleanup with their existing operational data retention controls.

## Assistant identity and harness files

LM Studio does not consume Markdown prompt files directly. The backend reads the identity Markdown files, composes a bounded `system` message, and sends that through the OpenAI-compatible `messages` array.

NEX-GEN-owned prompt and harness source files live under `backend/ai/`:

| File | Purpose |
|---|---|
| [`backend/ai/README.md`](../backend/ai/README.md) | Load model and file map. |
| [`backend/ai/identity/Soul.md`](../backend/ai/identity/Soul.md) | Base read-only assistant identity. |
| [`backend/ai/identity/scope.md`](../backend/ai/identity/scope.md) | Permissions and mutation boundaries. |
| [`backend/ai/identity/context-policy.md`](../backend/ai/identity/context-policy.md) | Compact incident context strategy. |
| [`backend/ai/identity/session-bootstrap.md`](../backend/ai/identity/session-bootstrap.md) | First interaction flow. |
| [`backend/ai/tools/README.md`](../backend/ai/tools/README.md) | Current backend-owned tool catalog. |
| [`backend/ai/tools/availability_check.md`](../backend/ai/tools/availability_check.md) | Bounded ping harness contract. |

At runtime, backend code loads `Soul.md`, `scope.md`, and `context-policy.md` for the system prompt. The current first slice pre-resolves explicit backend intents such as `availability_check`, authorizes them server-side, and includes the harness result in the prompt. It does not yet run an LM Studio tool-call loop or send an OpenAI `tools` array.

## Known limitations

- Chat is non-streaming for this first slice.
- History is persisted server-side, but the current UI only displays the active browser session.
- LM Studio errors are mapped to safe frontend messages; backend logs should be used for operator diagnostics.
- The ping harness is Linux-focused and isolated in `services/ai_chat_service.py` for tests and future portability work.
- LM Studio tool calls are not enabled yet; explicit backend intents are pre-resolved before the final chat completion request.

## Future improvements

- Add streaming responses once the proxy contract is stable.
- Add an LM Studio tool-call loop with OpenAI-compatible `tools` payloads once the intent pre-resolution path is stable.
- Add a conversation history endpoint for UI reloads.
- Add more bounded, allow-listed harness tools with per-action audit and authorization checks.
