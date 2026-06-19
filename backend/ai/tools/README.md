# AI harness tools

Tools are backend-owned, allow-listed harnesses. The current runtime pre-resolves explicit backend intents before the final LM Studio request; it does not yet accept model-initiated tool calls.

## Current tools

| Tool | Purpose | Mutates data? |
|---|---|---:|
| `availability_check` | Resolve one stored CI and run one bounded ping to its stored IP or hostname. | No |

See `availability_check.md` for the exact contract.
