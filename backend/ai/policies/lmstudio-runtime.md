# LM Studio runtime policy

NEX-GEN uses LM Studio through the OpenAI-compatible `/v1/chat/completions` endpoint. Native LM Studio stateful `/api/v1/chat` is not the default integration path.

The backend owns backend-owned history and sends bounded chat `messages` for each request. Provider state is not required for continuity.

Reasoning-capable models may return populated `reasoning_content` with empty assistant `content`. Harness-backed deterministic rendering prevents operational answers from failing when model content is blank.

Tune `LM_STUDIO_MAX_TOKENS`, `LM_STUDIO_TIMEOUT_SECONDS`, and model context length together: larger context and completion budgets can improve completeness but increase latency and timeout risk.
