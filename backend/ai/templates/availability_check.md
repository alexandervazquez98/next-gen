# availability_check deterministic template

Use this reviewed structure for one `availability_check` harness result.

## Result

Include CI identity or reference, status, target when available, latency when available, and detail when available.

## Interpretation

`reachable` means only that the current bounded ping responded at execution time. `unreachable` means only that the current bounded ping did not receive a response.

## Limitations

A ping result does not confirm complete service health, root cause, or automatic event closure.
