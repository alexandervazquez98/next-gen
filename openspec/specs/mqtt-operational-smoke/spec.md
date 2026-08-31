# MQTT Operational Smoke Specification

## Purpose

Operator smoke proving `mqtt-subscriber` heartbeat transitions from absent to active via `/api/mqtt/status`, without mutating persistent state. Closes the gap tracked as `#387` in `docs/mqtt-monitoring.md`. Does NOT modify the `/api/mqtt/status` contract, subscriber implementation, or any schema.

## Requirements

### Requirement: Subscriber-Absent Detection

The smoke SHALL detect an absent `mqtt-subscriber` by reading `/api/mqtt/status` and asserting both `connected=false` AND `last_message_at` older than `MQTT_SUBSCRIBER_STALE_HEARTBEAT_SECONDS` (default `90`).

#### Scenario: Subscriber absent at start

- GIVEN `mqtt-subscriber` is not running and `/api/mqtt/status` returns `connected=false` with `last_message_at` older than the stale threshold
- WHEN the operator runs `sh scripts/mqtt-ops-smoke.sh`
- THEN the script exits non-zero, prints `subscriber absent`, and prints the status JSON with `connected=false` and the stale `last_message_at`

#### Scenario: Subscriber already active at start

- GIVEN `mqtt-subscriber` is running and `/api/mqtt/status` returns `connected=true` with fresh `last_message_at`
- WHEN the operator runs `sh scripts/mqtt-ops-smoke.sh`
- THEN the script skips the absent-state assertion and continues to the active-state assertion

### Requirement: Subscriber Activation

The smoke SHALL bring the subscriber up via `docker compose up -d mqtt-subscriber` (no `-v`, no `down`) and poll `/api/mqtt/status` until `connected=true` with fresh `last_message_at`.

#### Scenario: Up -d then connected

- GIVEN the subscriber starts absent
- WHEN the script runs `docker compose up -d mqtt-subscriber` and polls status
- THEN it exits zero once `connected=true` with `last_message_at` within the stale threshold

#### Scenario: Activation timeout

- GIVEN the subscriber starts absent and remains absent after activation
- WHEN the script polls past the activation deadline
- THEN it exits non-zero, prints the last status JSON, and still prints rollback

### Requirement: End-to-End Fixture Mode

When invoked with `--with-fixture`, the smoke SHALL publish a test MQTT message and assert visibility through `/api/mqtt/readings`.

#### Scenario: Fixture publish visible in readings

- GIVEN the subscriber is active and `--with-fixture` is passed
- WHEN the script publishes a uniquely tagged test message
- THEN it polls `/api/mqtt/readings` until the tag appears, then exits zero

#### Scenario: Fixture timeout

- GIVEN the subscriber is active but `/api/mqtt/readings` never returns the tag
- WHEN the fixture deadline elapses
- THEN the script exits non-zero and prints the last readings payload

### Requirement: Environment Validation

Before any status assertion, the smoke SHALL validate `MQTT_BROKER_URL` (via `docker compose config`) and `NEO4J_*` / `POSTGRES_*` (via `scripts/validate-env.sh`).

#### Scenario: Missing MQTT_BROKER_URL

- GIVEN `MQTT_BROKER_URL` is unset in the Compose project
- WHEN the operator runs the smoke
- THEN the script exits non-zero with `missing env: MQTT_BROKER_URL`

#### Scenario: Missing database credentials

- GIVEN `NEO4J_PASSWORD` or `POSTGRES_PASSWORD` is missing
- WHEN the operator runs the smoke
- THEN the script exits non-zero with `missing env:` followed by the offending variable names
- AND no Docker Compose action is taken

### Requirement: Forbidden Destructive Flags

The smoke MUST NOT invoke `docker compose down`, the `-v` flag, `rm`, or any volume-removing verb. The offline test harness `scripts/test-mqtt-ops-smoke.sh` SHALL grep the smoke source for those tokens and fail if present.

#### Scenario: Test harness rejects -v

- GIVEN `scripts/mqtt-ops-smoke.sh` is updated locally to include `docker compose down -v`
- WHEN `sh scripts/test-mqtt-ops-smoke.sh` runs
- THEN the test exits non-zero citing the forbidden `-v` token

#### Scenario: Test harness rejects compose down

- GIVEN the smoke source contains `docker compose down`
- WHEN the offline test runs
- THEN it exits non-zero citing `compose down`

### Requirement: Rollback Printout

The smoke SHALL print explicit rollback instructions on both success and failure exits, instructing the operator to run `docker compose stop mqtt-subscriber` and never to use `-v` or `down`.

#### Scenario: Success exit

- GIVEN the active-state assertion passes
- WHEN the script reaches its terminal print
- THEN it prints a rollback block with the `docker compose stop mqtt-subscriber` command

#### Scenario: Failure exit

- GIVEN any assertion fails or any validation aborts
- WHEN the script exits non-zero
- THEN the rollback block is printed before exit
