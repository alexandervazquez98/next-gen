# availability_check_batch deterministic template

Use this reviewed structure for `availability_check_batch` harness results.

## Summary

Include count and one per-CI row with CI/ref, status, target, latency, and detail.

## Interpretation

Results describe current bounded ping checks only. The batch is capped at 5 CIs / máximo 5 CIs.

## Limitations

Ping reachability does not confirm complete service health, root cause, or automatic event closure.
