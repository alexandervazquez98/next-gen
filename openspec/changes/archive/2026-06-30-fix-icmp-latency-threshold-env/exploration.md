## Exploration: fix-icmp-latency-threshold-env

### Current State
`backend/config.py` defines `ICMPSettings.from_env()` with `ICMP_LATENCY_WARNING_MS` defaulting to `100` and `ICMP_LATENCY_CRITICAL_MS` defaulting to `500`. The latency threshold values are used by the queue writer path in `backend/polling/writer_pool.py`, the legacy SNMP/ICMP worker in `backend/engines/snmp_worker.py`, and ICMP sidecar `MetricDef` initialization in `backend/repositories/topology_repo.py`.

The root `.env.example` already documents `ICMP_LATENCY_WARNING_MS` and `ICMP_LATENCY_CRITICAL_MS`, but `docker-compose.yml` only injects `ICMP_TIMEOUT_MS`, `ICMP_RETRIES`, and `ICMP_DEBOUNCE_COUNT` into `snmp-engine`. The `backend` service currently does not receive any ICMP env vars. Because Docker Compose `.env` values are used for interpolation and are not automatically exported into containers, containerized code paths that call `get_icmp_settings()` can fall back to the code defaults unless the variables are listed in a service environment.

### Affected Areas
- `docker-compose.yml` — must pass `ICMP_LATENCY_WARNING_MS` and `ICMP_LATENCY_CRITICAL_MS` into the service environments that execute ICMP latency threshold logic.
- `backend/config.py` — source of the current defaults and validation; likely no application-code change is needed.
- `backend/polling/writer_pool.py` — queue writer emits latency threshold events using `get_icmp_settings()`.
- `backend/engines/snmp_worker.py` — legacy ICMP polling evaluates latency warning/critical status using `get_icmp_settings()`.
- `backend/repositories/topology_repo.py` — sidecar MetricDef initialization writes warning/critical properties from `get_icmp_settings()`.
- `.env.example` — already contains both threshold variables; likely no change needed unless comments are clarified.

### Approaches
1. **Inject latency thresholds into all runtime services that read ICMP settings** — Add `ICMP_LATENCY_WARNING_MS=${ICMP_LATENCY_WARNING_MS:-100}` and `ICMP_LATENCY_CRITICAL_MS=${ICMP_LATENCY_CRITICAL_MS:-500}` to both `backend` and `snmp-engine` service environments.
   - Pros: Covers both known `get_icmp_settings()` runtime contexts: backend-side initialization/writer code and snmp-engine polling/event code; keeps defaults aligned with `backend/config.py`; minimal and explicit Compose fix.
   - Cons: Slight duplication across service environment blocks.
   - Effort: Low

2. **Inject latency thresholds only into `snmp-engine`** — Add the two variables only beside the existing ICMP env vars in the `snmp-engine` service.
   - Pros: Smallest patch; directly fixes the most likely active polling path.
   - Cons: Leaves backend code paths that call `get_icmp_settings()` vulnerable to defaults, including sidecar MetricDef initialization if it runs in the backend container and queue writer behavior if enabled there.
   - Effort: Low

3. **Use a shared env anchor or env_file pattern** — Centralize ICMP env vars and reference them from services.
   - Pros: Reduces duplication if more ICMP settings are added later.
   - Cons: Larger Compose refactor for a two-variable bug fix; higher risk of unintended Compose merge/interpolation behavior.
   - Effort: Medium

### Recommendation
Use Approach 1: explicitly pass `ICMP_LATENCY_WARNING_MS=${ICMP_LATENCY_WARNING_MS:-100}` and `ICMP_LATENCY_CRITICAL_MS=${ICMP_LATENCY_CRITICAL_MS:-500}` to both `backend` and `snmp-engine`. This is the smallest robust fix because every container that can evaluate or initialize ICMP latency thresholds receives the same runtime configuration, while preserving the current code defaults and validation.

### Risks
- Compose validation should be run after the change because YAML list-style environment entries are easy to misplace.
- If operators already have containers running, they must recreate/restart affected services for new environment values to take effect.
- `get_icmp_settings()` is a singleton inside each Python process, so env changes are only picked up on process/container restart.

### Ready for Proposal
Yes — propose a configuration-only Compose fix that injects the two latency threshold env vars into `backend` and `snmp-engine`, with validation via `docker compose config --quiet` and a targeted check that rendered service environments include the configured values.
