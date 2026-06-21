# Frontend Local Dev Install Gate Specification

## Purpose

Ensure non-Docker frontend developers can discover and recover missing declared dependencies before Vite reports unresolved imports such as `sonner`.

## Requirements

### Requirement: Frontend local development guide

The system MUST provide a `frontend/README.md` with `## Prerequisites`, `## Install`, `## Dev`, `## Test`, `## Build`, `## Troubleshooting`, and `## Known gaps`. The install guidance MUST use `corepack pnpm install --frozen-lockfile`.

#### Scenario: Frontend README documents required local workflow

- GIVEN a developer opens `frontend/README.md`
- WHEN they follow local setup guidance
- THEN they see all required sections
- AND install uses `corepack pnpm install --frozen-lockfile`

### Requirement: Root README local frontend pointer

The system MUST document a root README subsection named “Local frontend dev (no Docker)” and MUST state that this path is NOT covered by `docker-compose up`.

#### Scenario: Root README distinguishes Docker and non-Docker setup

- GIVEN a developer reads the root README
- WHEN they choose non-Docker frontend development
- THEN they find “Local frontend dev (no Docker)”
- AND the docs state Docker Compose does not cover that path

### Requirement: Frontend dependency pre-flight

The system MUST provide an executable `scripts/check-frontend-deps.sh` that is idempotent, checks missing imports from `frontend/context/AuthContext.tsx` and `frontend/App.tsx`, installs on misses, exits non-zero on install failure, and prints clear success or failure messages.

#### Scenario: Pre-flight recovers missing declared imports

- GIVEN declared frontend imports are missing from `node_modules`
- WHEN `scripts/check-frontend-deps.sh` runs
- THEN it runs `corepack pnpm install --frozen-lockfile`
- AND reports clear success or failure

### Requirement: Pre-flight RED-first test coverage

The system MUST provide `scripts/test-check-frontend-deps.sh` written RED-first and covering recovery, no-op sentinel, and mocked install failure.

#### Scenario: Script tests prove recovery no-op and failure paths

- GIVEN the pre-flight behavior is under test
- WHEN `scripts/test-check-frontend-deps.sh` runs
- THEN recovery, no-op sentinel, and mocked install failure are covered
- AND the test passes after implementation

### Requirement: Package script entrypoint

The system MUST expose the dependency pre-flight through `pnpm --dir frontend run check:deps`.

#### Scenario: Developer runs dependency check through pnpm

- GIVEN a developer is at the repo root
- WHEN they run `pnpm --dir frontend run check:deps`
- THEN the frontend dependency pre-flight executes
- AND the command exits with the pre-flight result

### Requirement: Existing frontend test suite remains green

The system MUST preserve the existing frontend test suite result for `pnpm --dir frontend run test:run`.

#### Scenario: Frontend tests still pass

- GIVEN the install-gate changes are applied
- WHEN `pnpm --dir frontend run test:run` runs
- THEN the suite passes
- AND the expected baseline remains 57 files / 479 tests

### Requirement: Merge order remains non-blocking

The system MUST keep this change independent of the parallel `cicd/cd-lane` chain.

#### Scenario: CI chain and local install gate land independently

- GIVEN either `cicd/cd-lane` or this change lands first
- WHEN the other lands later
- THEN this change remains docs/script-only for local dev
- AND CI gates can arrive through the separate chain
