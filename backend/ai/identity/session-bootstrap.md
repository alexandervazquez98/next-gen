# Session bootstrap

This is the first interaction flow for backend-owned AI chat sessions.

1. Frontend sends the user question and allowed UI context to `/api/ai/chat`.
2. Backend loads identity docs server-side and builds a compact system prompt.
3. Backend selects a small incident context for the user message.
4. Backend pre-resolves explicit allowed intents, such as `availability_check`
   and `event_list`, when authorized.
5. Backend sends the OpenAI-compatible request to LM Studio with `messages` and
   any backend harness result.
6. LM Studio returns the assistant answer.
7. Backend persists the exchange and harness metadata.

The current slice does not send an OpenAI-compatible `tools` array or execute an
LM Studio tool-call loop. Harnesses stay provider-neutral and backend-owned.

The frontend cannot control assistant identity, prompt files, tool definitions,
LM Studio base URL, or selected model.
