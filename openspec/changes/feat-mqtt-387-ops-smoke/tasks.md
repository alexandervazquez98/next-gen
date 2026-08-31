# Tasks: MQTT Operational Smoke (#387)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~250 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | POSIX smoke + offline grep test | PR 1 | `bash scripts/test-mqtt-ops-smoke.sh` | `sh scripts/mqtt-ops-smoke.sh --help` exit 0 | delete both scripts |
| 2 | Runbook section in `docs/mqtt-monitoring.md` | PR 1 | `grep -c '## Operational smoke' docs/mqtt-monitoring.md` | N/A — doc-only | delete appended section |
| 3 | Remove `#387` from `## Known gaps` | PR 1 | `grep -n '387' docs/mqtt-monitoring.md` (runbook only) | N/A — doc-only | restore removed line |

## Phase 1: Smoke + offline test

- [x] 1.1 **`scripts/mqtt-ops-smoke.sh`**. POSIX `set -eu`; `scripts/validate-env.sh`; broker probe via `docker compose config --format json | grep -q '"MQTT_BROKER_URL"'`; absent branch asserts `connected=false` + stale `last_message_at`; `docker compose up -d mqtt-subscriber`; bounded poll for `connected=true`; `trap EXIT` prints rollback. **Spec:** S-absent, S-already-active, S-up-d, S-missing-broker, S-missing-db, S-success-exit, S-failure-exit. **Test:** `sh -n scripts/mqtt-ops-smoke.sh && sh scripts/mqtt-ops-smoke.sh --help`. **Threat:** T1 (only `up -d`/`stop`), T2 (broker probe), T5 (`curl -fsS` fail-loud).
- [x] 1.2 **`scripts/test-mqtt-ops-smoke.sh`**. Greps smoke for whole-word forbidden (`down`, `rm`, `volume`, `-v`) + required (`up -d mqtt-subscriber`, `stop mqtt-subscriber`, `exec -T`) tokens; asserts `--help` exits 0 + mentions `--with-fixture`. RED: copy smoke to `/tmp`, inject forbidden token, re-run → non-zero. **Spec:** S-test-rejects-v, S-test-rejects-down. **Test:** `bash scripts/test-mqtt-ops-smoke.sh`. **Threat:** T1 RED, T5 RED, T6 RED.
- [x] 1.3 **`scripts/test-mqtt-ops-smoke.sh`**. Stub unset `MQTT_BROKER_URL`; assert `compose config --format json | grep -q '"MQTT_BROKER_URL"'` non-zero; compare shell vs compose env, mismatch → fail-loud. **Spec:** S-missing-broker. **Test:** `bash scripts/test-mqtt-ops-smoke.sh`. **Threat:** T2 RED, T4 RED.
- [x] 1.4 **`scripts/test-mqtt-ops-smoke.sh`**. Grep smoke for bounded poll (deadline + timeout branch). RED: copy without deadline → test fails. **Spec:** S-activation-timeout. **Test:** `bash scripts/test-mqtt-ops-smoke.sh`. **Threat:** T3 RED.
- [x] 1.5 **`scripts/mqtt-ops-smoke.sh`**. Add `--with-fixture`: publish tagged msg via `docker compose exec -T mqtt-subscriber mosquitto_pub`; poll `/api/mqtt/readings` until tag (bounded). **Spec:** S-fixture-visible, S-fixture-timeout. **Test:** `sh scripts/mqtt-ops-smoke.sh --help` mentions `--with-fixture`. **Threat:** T6.

## Phase 2: Runbook

- [x] 2.1 **`docs/mqtt-monitoring.md`** (append). `## Operational smoke (#387)`: prerequisites, smoke flow, `--with-fixture`, rollback (`docker compose stop mqtt-subscriber` — never `down`/`-v`). **Spec:** S-success-exit, S-failure-exit. **Test:** `grep -c '## Operational smoke' docs/mqtt-monitoring.md` = 1. **Threat:** N/A.

## Phase 3: Cleanup

- [x] 3.1 **`docs/mqtt-monitoring.md`** (modify). Remove `#387` line from `## Known gaps and follow-up work`. **Spec:** N/A. **Test:** `grep -n '387' docs/mqtt-monitoring.md` matches only runbook heading. **Threat:** N/A.

## Phase 4: Verification

- [x] 4.1 Run `bash scripts/test-mqtt-ops-smoke.sh`; assert exit 0. **Spec:** S-test-rejects-v, S-test-rejects-down, S-missing-broker, S-activation-timeout converge. **Test:** `bash scripts/test-mqtt-ops-smoke.sh` exits 0. **Threat:** T1–T6 RED converge.
- [x] 4.2 Run `sh scripts/mqtt-ops-smoke.sh --help`; assert exit 0 + mentions `--with-fixture`. **Spec:** S-success-exit. **Test:** `sh scripts/mqtt-ops-smoke.sh --help`. **Threat:** N/A (dry-run).