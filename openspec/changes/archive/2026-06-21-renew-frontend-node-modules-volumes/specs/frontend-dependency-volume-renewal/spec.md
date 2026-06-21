# Frontend Dependency Volume Renewal Specification

Capability ID: `frontend-dependency-volume-renewal`  
Status: `Proposed`  
Change: `renew-frontend-node-modules-volumes`  
Issue: `alexandervazquez98/next-gen#306`  
TDD policy: `strict_tdd`

## Purpose

The dev `frontend` service bind-mounts source code into `/app` and keeps `/app/node_modules` as an anonymous Docker volume for hot reload. When `frontend/pnpm-lock.yaml` changes, that build-artifact volume can mask dependencies baked into a freshly rebuilt image.

This capability preserves data volumes while renewing only the frontend build-artifact volume when dependency state changes. It separates operational hygiene for disposable `node_modules` state from destructive database or backup volume cleanup.

## Requirements

### Requirement R1: Safe rebuild skips renewal when lockfile hash is unchanged

The system MUST NOT pass `--renew-anon-volumes` during `scripts/safe-rebuild.sh` when `$BACKUP_DIR/frontend-pnpm-lock.sha256` matches the current `frontend/pnpm-lock.yaml` hash.

Rationale: Unchanged dependency state should not recreate the frontend container or churn anonymous volumes unnecessarily.

#### Scenario: Matching sentinel skips anonymous volume renewal

- GIVEN the sentinel hash matches the current frontend lockfile hash
- WHEN `scripts/safe-rebuild.sh` runs normally
- THEN no Docker command includes `--renew-anon-volumes`

### Requirement R2: Safe rebuild renews only frontend when lockfile hash changed

The system MUST run `docker compose up -d --force-recreate --renew-anon-volumes frontend` when the stored frontend lockfile hash differs from the current hash.

Rationale: The stale `/app/node_modules` anonymous volume must be replaced without affecting unrelated service state.

#### Scenario: Changed lockfile renews frontend anonymous volume

- GIVEN the sentinel hash differs from the current frontend lockfile hash
- WHEN `scripts/safe-rebuild.sh` runs normally
- THEN it runs `docker compose up -d --force-recreate --renew-anon-volumes frontend`
- AND the renewal is scoped to the `frontend` service

### Requirement R3: Safe rebuild dry-run reports renewal without Docker execution

The system MUST print the frontend renewal command and MUST NOT execute any `docker` command during `scripts/safe-rebuild.sh --dry-run`.

Rationale: Operators need previewable rebuild plans, and strict dry-run behavior prevents accidental container or volume changes.

#### Scenario: Dry-run changed lockfile previews renewal

- GIVEN the frontend lockfile hash changed
- WHEN `scripts/safe-rebuild.sh --dry-run` runs
- THEN it prints `docker compose up -d --force-recreate --renew-anon-volumes frontend`
- AND no `docker` executable is invoked

### Requirement R4: Safe rebuild never uses destructive volume cleanup

The system MUST NEVER invoke `docker compose down -v` or `docker volume rm` from any safe-rebuild path.

Rationale: Safe rebuilds may refresh disposable build-artifact volumes but must not risk database, backup, or operator data volumes.

#### Scenario: Recorded safe-rebuild commands are non-destructive

- GIVEN Docker commands are recorded for any safe-rebuild execution path
- WHEN the command log is inspected
- THEN it contains no `docker compose down -v`
- AND it contains no `docker volume rm`

### Requirement R5: Refresh script renews frontend dependencies normally

The system SHALL provide `scripts/refresh-frontend-deps.sh` that prints and runs `docker compose up -d --force-recreate --renew-anon-volumes frontend` during normal execution.

Rationale: Operators need a single-purpose recovery command for stale dev frontend dependencies without learning volume internals.

#### Scenario: Normal refresh runs frontend-scoped renewal

- GIVEN Docker is available
- WHEN `scripts/refresh-frontend-deps.sh` runs
- THEN it prints `+ docker compose up -d --force-recreate --renew-anon-volumes frontend`
- AND it executes that command

### Requirement R6: Refresh script dry-run does not execute Docker

The system SHALL support `scripts/refresh-frontend-deps.sh --dry-run` by printing the intended command without executing Docker.

Rationale: Manual recovery must be previewable with the same safety expectation as safe rebuild.

#### Scenario: Refresh dry-run short-circuits execution

- GIVEN `scripts/refresh-frontend-deps.sh --dry-run`
- WHEN the script reaches the renewal step
- THEN it prints the frontend renewal command
- AND no `docker` executable is invoked

### Requirement R7: Refresh script fails clearly when Docker is missing

The system SHALL exit non-zero with a clear missing-command message when `scripts/refresh-frontend-deps.sh` starts without `docker` available.

Rationale: Operators should get an actionable prerequisite failure instead of a partial or ambiguous recovery attempt.

#### Scenario: Missing Docker fails before renewal

- GIVEN `docker` is absent from `PATH`
- WHEN `scripts/refresh-frontend-deps.sh` starts
- THEN it exits non-zero
- AND it reports that `docker` is required

### Requirement R8: Refresh script rejects unsupported flags

The system SHALL reject unsupported `scripts/refresh-frontend-deps.sh` flags and SHALL accept no operational flag other than `--dry-run` and help.

Rationale: A narrow CLI prevents accidental coupling to backup or Neo4j rebuild flags and keeps the script single-purpose.

#### Scenario: Unsupported refresh flag is rejected

- GIVEN an unsupported flag such as `--skip-neo4j`
- WHEN `scripts/refresh-frontend-deps.sh --skip-neo4j` runs
- THEN it exits non-zero
- AND it does not execute Docker

## Constraints and Invariants

- The sentinel `$BACKUP_DIR/frontend-pnpm-lock.sha256` MUST be written only after a successful frontend renewal.
- `--renew-anon-volumes` MUST be scoped to `frontend` only and MUST NOT be used service-wide.
- The pre-backup `docker compose up -d --no-build postgres neo4j backend` path MUST remain untouched.
- Dry-run behavior MUST NOT execute any `docker` command.

## Out of Scope

- Removing the anonymous `/app/node_modules` volume from `docker-compose.yml`.
- Touching `frontend-prod`.
- Touching `.github/workflows/cd.yml`.
