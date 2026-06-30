# Design: Fix ICMP Latency Threshold Environment Propagation

## Technical Approach

Apply a Compose-only fix: explicitly pass `ICMP_LATENCY_WARNING_MS` and `ICMP_LATENCY_CRITICAL_MS` into the two container services that execute backend Python code paths calling `get_icmp_settings()`: `backend` and `snmp-engine`. Keep `backend/config.py` as the source of parsing, validation, defaults, and singleton caching. This satisfies the delta spec by making operator-configured thresholds available to affected containers while preserving application behavior.

## Architecture Decisions

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Add threshold variables to `backend` and `snmp-engine` service `environment` lists | Duplicates two entries, but covers all known containerized `get_icmp_settings()` consumers | Chosen: explicit propagation is the smallest complete fix |
| Add variables only to `snmp-engine` | Smaller patch, but leaves backend-side MetricDef initialization and writer paths on defaults | Rejected because the spec requires every containerized threshold evaluator |
| Refactor Compose env handling with anchors or `env_file` | Reduces future duplication, but expands scope and risks unrelated Compose behavior changes | Rejected as out of scope for a focused bug fix |
| Modify Python defaults/parsing | Could mask missing env propagation, but changes product semantics and validation surface | Rejected because existing Python tests show the settings contract already works |

## Data Flow

```text
.env / shell env
      │
      ▼
docker compose interpolation
      │
      ├── backend.environment ──────┐
      │                             ▼
      └── snmp-engine.environment → get_icmp_settings()
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
writer_pool latency events   snmp_worker ICMP polling   topology MetricDef init
```

`get_icmp_settings()` remains process-cached, so changed values require container/process recreation before they take effect.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `docker-compose.yml` | Modify | Add `ICMP_LATENCY_WARNING_MS=${ICMP_LATENCY_WARNING_MS:-100}` and `ICMP_LATENCY_CRITICAL_MS=${ICMP_LATENCY_CRITICAL_MS:-500}` to `backend.environment` and `snmp-engine.environment`. |
| `backend/config.py` | Unchanged | Retains `ICMPSettings.from_env()`, validation, defaults, and singleton behavior. |
| `backend/tests/test_snmp_worker.py` | Unchanged | Existing ICMP settings tests already cover env parsing, defaults, ordering validation, and caching. |

## Interfaces / Contracts

No Python interface changes. The Compose deployment contract is extended so affected services receive these existing variables:

```yaml
- ICMP_LATENCY_WARNING_MS=${ICMP_LATENCY_WARNING_MS:-100}
- ICMP_LATENCY_CRITICAL_MS=${ICMP_LATENCY_CRITICAL_MS:-500}
```

Defaults intentionally match `ICMPSettings` (`100` warning, `500` critical) and `.env.example`.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Config render | Compose remains valid | Run `docker compose config --quiet`. |
| Integration/config evidence | `backend` and `snmp-engine` render both threshold env vars with configured/default values | Inspect `docker compose config` output for service environments. |
| Unit | Existing Python parsing and validation stay unchanged | Run targeted backend tests for `TestICMPSettings`, or document if unavailable. |
| E2E | Not required | This is environment propagation; rendered Compose plus existing settings tests provide sufficient evidence. |

## Migration / Rollout

No data migration required. Operators must recreate/restart `backend` and `snmp-engine` containers for new environment values to be loaded because settings are process-cached.

## Open Questions

None.
