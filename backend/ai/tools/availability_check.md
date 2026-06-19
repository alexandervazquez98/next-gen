# `availability_check` harness

Bounded read-only ping check for one stored CI.

## Purpose

Answer a narrow operator question: "is this known CI reachable right now?"

## Inputs

| Field | Source | Notes |
|---|---|---|
| `ci_ref` | User request or UI context | CI id or CI name only. |

The browser cannot provide shell commands, ping flags, raw targets, LM Studio settings, or model names.

## Permission

Requires backend diagnostic authorization for the current user and request. Tool execution is backend-authorized, not model-authorized.

## Target resolution

1. Resolve `ci_ref` against stored CMDB data.
2. Use the CI's stored `ip` first, then stored `hostname`.
3. Reject empty targets, unsafe hostnames, option-like values, and arbitrary user-supplied targets.

## Guardrails

- Executes one Linux-focused command: `ping -c 1 -W 2 <target>`.
- Backend subprocess timeout is bounded.
- No network scanning.
- No shell interpolation.
- No data mutation.

## Output metadata

| Field | Meaning |
|---|---|
| `type` | Always `availability_check`. |
| `ci_id`, `ci_name` | Resolved CI identity when available. |
| `target` | Stored IP or hostname used by the backend. |
| `status` | `reachable`, `unreachable`, `ci_not_found`, `invalid_target`, or `error`. |
| `latency_ms` | Parsed ping latency when available. |
| `detail` | Short diagnostic summary safe for the UI. |

## Failure modes

- CI reference does not match stored data.
- CI has no stored IP or hostname.
- Stored target fails safety validation.
- Ping command is unavailable, times out, or fails.
- Backend authorization denies the request.
