# LM Studio AI Chat Integration

NEX-GEN AI chat uses a backend proxy to talk to LM Studio's OpenAI-compatible local API. The browser only calls `/api/ai/chat`; it never receives or controls the LM Studio base URL, model, or harness targets.

## Quick path

1. Start LM Studio and enable the local server.
2. Configure the backend environment variables below.
3. Verify LM Studio responds on `/v1/chat/completions`.
4. Send chat from the NEX-GEN AI console; the backend posts to LM Studio.

## Environment

| Variable | Default | Bounds | Notes |
|---|---:|---:|---|
| `LM_STUDIO_ENABLED` | `false` | `true`/`false` | Keeps the proxy opt-in. Harness side effects stay blocked when disabled. |
| `LM_STUDIO_BASE_URL` | Backend fallback: `http://localhost:1234/v1`; Compose `.env.example`: `http://host.docker.internal:1234/v1` | OpenAI-compatible base URL | Standalone backend defaults to local host access when no environment value is set. Docker/Compose uses `host.docker.internal` so the container can reach LM Studio on the Docker host. |
| `LM_STUDIO_MODEL` | `local-model` | Loaded LM Studio model id | Must match the model selected/served by LM Studio. |
| `LM_STUDIO_TIMEOUT_SECONDS` | `15` | Max `120` seconds | Backend request timeout. Raise carefully for slow large models. |
| `LM_STUDIO_MAX_TOKENS` | `800` | `1..4096` | Completion token cap sent to LM Studio. Raise for longer operational answers; larger values increase latency. |

## Docker networking

Inside the backend container, `localhost` is the container itself, not your host machine. Use one of these instead:

```env
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1
# or
LM_STUDIO_BASE_URL=http://192.168.1.50:1234/v1
```

The Compose backend service maps `host.docker.internal` to the Linux Docker host gateway so the Compose `.env.example` URL works on Linux as well as Docker Desktop environments. This is different from the backend code fallback: when the backend runs directly on the host with no `LM_STUDIO_BASE_URL` set, it falls back to `http://localhost:1234/v1`.

For a separate LM Studio workstation or server, bind the LM Studio local server to the LAN interface and use that machine's LAN/VPN IP:

```env
LM_STUDIO_BASE_URL=http://10.53.1.121:1234/v1
```

Do not use `localhost` from Docker unless LM Studio is running inside the same backend container.

## Quick LM Studio verification

Run this with the same base URL your backend will use. Set `LM_STUDIO_URL` first so the command is copy-safe for both standalone and Docker deployments:

```bash
LM_STUDIO_URL=http://localhost:1234/v1
# For Docker/Compose, use the value from .env instead, for example:
# LM_STUDIO_URL=http://host.docker.internal:1234/v1

curl -sS "$LM_STUDIO_URL/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "local-model",
    "messages": [{"role": "user", "content": "Reply with: ok"}],
    "max_tokens": 32,
    "temperature": 0
  }'
```

Expected result: HTTP 200 with a `choices[0].message.content` response. If the model name is wrong, LM Studio returns an error before NEX-GEN can answer.

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

## Troubleshooting

| Symptom | Likely cause | Operator check |
|---|---|---|
| Backend returns AI unavailable / 502 | LM Studio is stopped, unreachable, or returned an upstream error. | Check backend logs, then run the curl command above from the same network namespace. |
| Model not found or immediate LM Studio error | `LM_STUDIO_MODEL` does not match the model served by LM Studio. | Copy the exact model id from LM Studio and restart the backend after `.env` changes. |
| Works on host, fails in Docker | `LM_STUDIO_BASE_URL=http://localhost:1234/v1` points at the backend container, not the host. | Use `host.docker.internal` or the LM Studio host LAN/VPN IP. |
| Timeouts on large answers | Model latency, context length, and `LM_STUDIO_MAX_TOKENS` exceed the timeout budget. | Increase `LM_STUDIO_TIMEOUT_SECONDS` up to `120`, reduce context/model size, or lower max tokens. |
| Answers are truncated | Completion budget is too small. | Raise `LM_STUDIO_MAX_TOKENS` within `1..4096`; Docker/backend default is `800`. |
| Reasoning model returns blank answer | Some models spend the budget in `reasoning_content` while assistant `content` is empty. | For deterministic harnesses, NEX-GEN renders a safe backend-owned fallback. For free chat, raise max tokens or use a model that emits final content reliably. |

## Future improvements

- Add streaming responses once the proxy contract is stable.
- Add an LM Studio tool-call loop with OpenAI-compatible `tools` payloads once the intent pre-resolution path is stable.
- Add a conversation history endpoint for UI reloads.
- Add more bounded, allow-listed harness tools with per-action audit and authorization checks.
