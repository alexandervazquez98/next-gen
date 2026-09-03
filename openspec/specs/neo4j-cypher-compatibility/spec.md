# Neo4j Cypher Compatibility Specification

## Purpose

Define how the backend prevents, detects, and rejects Cypher syntax that is not valid against the deployed Neo4j 5.x / Cypher 5 grammar. The system MUST validate representative Cypher at process boot and MUST fail CI when unsupported ordering syntax — explicit `NULLS FIRST` / `NULLS LAST` — is reintroduced anywhere in the production backend. Together these two controls catch grammar regressions at the earliest possible moment (boot or CI) rather than at first live query.

## Requirements

### Requirement: Startup Cypher Smoke Query

The backend MUST run a minimal Cypher smoke query against the configured Neo4j driver during application startup, immediately after the connectivity check. The smoke MUST be wired at the startup hook and MUST NOT live inside `verify_connection()`, because `verify_connection()` is invoked from both startup and from the `/system/status` polling path. The smoke MUST issue a single read query (`RETURN 1 AS ok`) and MUST raise on any `ClientError` so a cold start fails loudly instead of serving traffic against a malformed schema.

#### Scenario: Healthy driver passes smoke

- GIVEN the Neo4j driver is reachable and supports the smoke query
- WHEN the backend boots
- THEN the smoke executes successfully
- AND startup proceeds without raising

#### Scenario: Incompatible driver fails startup loudly

- GIVEN the Neo4j driver returns `ClientError` for the smoke query
- WHEN the backend boots
- THEN the startup hook raises the exception
- AND the process exits non-zero before serving traffic

#### Scenario: Smoke is not re-invoked by `/system/status` polling

- GIVEN the backend has already booted successfully
- WHEN a client calls `GET /api/system/status`
- THEN no additional smoke query is issued per request
- AND the `/system/status` latency is unchanged

### Requirement: `DISABLE_NEO4J_SMOKE` Kill-Switch

The backend MUST honor the `DISABLE_NEO4J_SMOKE` environment variable. When set to a truthy value (`true`, `1`, case-insensitive), the startup smoke query MUST be skipped entirely. This enables test environments with stubbed Neo4j drivers to boot without raising.

#### Scenario: Kill-switch skips smoke

- GIVEN `DISABLE_NEO4J_SMOKE=true`
- WHEN the backend boots
- THEN the smoke query is not executed
- AND startup proceeds

#### Scenario: Default behavior runs smoke

- GIVEN `DISABLE_NEO4J_SMOKE` is unset or falsy
- WHEN the backend boots
- THEN the smoke query runs and its outcome governs startup

### Requirement: CI Regression Scan for `NULLS FIRST`/`NULLS LAST` Syntax

CI MUST include a regression scan that searches the production backend source tree (`backend/services/` and `backend/engines/`, excluding `backend/tests/`) for the regex pattern `NULLS\s+(FIRST|LAST)`. The scan MUST fail the build when any match is found and MUST report the offending file path and line number.

#### Scenario: Clean source tree passes scan

- GIVEN no `.py` file under `backend/services/` or `backend/engines/` contains `NULLS FIRST` or `NULLS LAST`
- WHEN the regression scan runs in CI
- THEN the build passes

#### Scenario: Reintroduced syntax fails scan

- GIVEN a `.py` file under `backend/services/` contains `NULLS LAST`
- WHEN the regression scan runs in CI
- THEN the scan reports the file path and line number
- AND the build fails before merge

#### Scenario: Test fixtures are excluded from the scan

- GIVEN a `.py` file under `backend/tests/` contains `NULLS FIRST` (e.g. a negative regression assertion)
- WHEN the regression scan runs in CI
- THEN the build is not failed by the test fixture
