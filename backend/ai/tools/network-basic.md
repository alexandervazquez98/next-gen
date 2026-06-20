# Network basic tools

Network diagnostics are read-only and bounded. They help the operator inspect a
known CI, not discover new targets.

## Scope

Allowed network diagnostics:

- `availability_check`: check whether a stored CI target is reachable.
- `availability_check_batch`: check a small bounded list of stored CI targets.
- `ping`: same diagnostic family as `availability_check`.
- `traceroute`: planned path diagnostic for a stored CI target.
- `dns_lookup`: planned name-resolution diagnostic for a stored CI hostname.

`availability_check` and `availability_check_batch` are active today. The other
names define the intended scope for future backend harnesses.

## Safety rules

- Use only targets resolved by backend code from stored CI data.
- Do not accept user-provided IPs, hostnames, ports, flags, or shell snippets.
- Do not run arbitrary shell commands.
- Do not perform subnet discovery, port scanning, or credential checks.
- Keep results concise: status, target, latency or path summary, and uncertainty.

## Current active harness: availability_check

Input intent shape:

```json
{
  "type": "availability_check",
  "ci_ref": "Router-01"
}
```

Expected harness result shape:

```json
{
  "type": "availability_check",
  "ci_id": "ci-1",
  "ci_name": "Router-01",
  "target": "192.168.1.10",
  "status": "reachable",
  "latency_ms": 12.3,
  "detail": "1 packet received"
}
```

## Batch availability

Input intent shape:

```json
{
  "type": "availability_check_batch",
  "ci_refs": ["Router-01", "Switch-02"]
}
```

The backend caps batch checks to a small list and resolves every target from
stored CMDB data before running bounded ping.

Assistant response rule:

- If `Harness result` is present, explain the result and next practical check.
- If no `Harness result` is present, do not say ping or traceroute ran.
- Say the diagnostic needs a backend harness execution.
