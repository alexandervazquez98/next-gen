# CI/CD Pipeline Specification

## Purpose

Define the GitHub Actions CI/CD capability for linting, dependency updates, backend/frontend validation, image builds, smoke gating, and production deployment through the existing endpoint `safe-rebuild.sh` path.

## Requirements

### Requirement: Workflow Skeleton

The repository MUST provide a workflow skeleton that future lanes can plug into without duplicating trigger and path-selection policy.

#### Scenario: Skeleton routes changed paths
- GIVEN a pull request changes backend files
- WHEN the workflow skeleton evaluates the change set
- THEN backend-scoped jobs are eligible to run

#### Scenario: Unrelated paths stay quiet
- GIVEN a pull request changes only documentation
- WHEN path filtering is evaluated
- THEN backend and frontend test lanes are skipped or marked not required by design

### Requirement: Changed-File Lint Configuration

Lint checks MUST apply Ruff and Black to changed backend files and ESLint and Prettier to changed frontend files only.

#### Scenario: Changed source is linted
- GIVEN a pull request changes Python and TypeScript source files
- WHEN lint jobs run
- THEN only changed files in matching stacks are checked

#### Scenario: Legacy untouched files do not block PR1
- GIVEN existing untouched files have formatting issues
- WHEN changed-file lint runs
- THEN the job MUST NOT fail because of untouched files

### Requirement: Dependabot Configuration

The repository MUST include a valid `.github/dependabot.yml` for pip, frontend package management, and GitHub Actions updates.

#### Scenario: Dependabot opens dependency PRs
- GIVEN Dependabot scans configured ecosystems
- WHEN updates are available
- THEN it opens real pull requests for each configured ecosystem

#### Scenario: Invalid ecosystem is rejected before merge
- GIVEN the configuration uses an unsupported package ecosystem
- WHEN validation runs
- THEN the PR fails with actionable configuration evidence

### Requirement: Backend CI Lane

Pull requests touching `backend/**` MUST run pytest with strict markers and produce a coverage report.

#### Scenario: Backend PR runs tests
- GIVEN a pull request changes backend code
- WHEN backend CI runs
- THEN `python -m pytest` executes with strict marker configuration and coverage output

#### Scenario: Unknown marker fails CI
- GIVEN a backend test uses an undeclared marker
- WHEN pytest runs
- THEN backend CI fails instead of silently ignoring marker drift

### Requirement: Frontend CI Lane

Pull requests touching `frontend/**` MUST install via Corepack pnpm with a frozen lockfile, run Vitest, and produce coverage.

#### Scenario: Frontend PR runs tests
- GIVEN a pull request changes frontend code
- WHEN frontend CI runs
- THEN dependencies install with frozen lockfile and Vitest coverage is produced

#### Scenario: Lockfile drift blocks CI
- GIVEN package metadata and lockfile are inconsistent
- WHEN pnpm install runs
- THEN frontend CI fails before tests execute

### Requirement: Build Lane and Production Images

The system MUST build a runnable production frontend image from `frontend/Dockerfile.prod` and build the backend image cleanly.

#### Scenario: Images build successfully
- GIVEN build inputs are valid
- WHEN the build lane runs
- THEN frontend production and backend images build without errors

#### Scenario: Broken Dockerfile blocks merge
- GIVEN a Dockerfile cannot produce a runnable image
- WHEN the build lane runs
- THEN the workflow fails before smoke or deployment lanes proceed

### Requirement: Smoke Lane and Playwright Gate

The smoke lane MUST start the compose stack, wait for backend and frontend health, run two Playwright smoke tests, and tear the stack down.

#### Scenario: Smoke validates serving paths
- GIVEN the compose stack is healthy
- WHEN Playwright smoke tests run
- THEN the frontend serves HTML and one backend endpoint returns HTTP 200

#### Scenario: Unhealthy stack blocks deployment
- GIVEN backend or frontend health does not become ready
- WHEN the smoke timeout expires
- THEN the smoke lane fails and tears down the stack without volume deletion

### Requirement: CD Lane

On push to `main`, CD MUST run on the production self-hosted runner, serialize deployments, pre-flight `safe-rebuild.sh`, run the real deploy, expose manual dry-runs, and alert on failure.

#### Scenario: Main merge deploys once
- GIVEN code is merged to `main`
- WHEN CD starts on the self-hosted runner
- THEN it performs a dry-run/pre-flight, runs `scripts/safe-rebuild.sh`, and holds the deployment concurrency lock

#### Scenario: Deployment failure alerts humans
- GIVEN `safe-rebuild.sh` fails
- WHEN CD records the failure
- THEN the workflow fails and emits the configured alert for human recovery

### Requirement: Rollback Policy v1

The system MUST NOT perform automatic service rollback in v1; smoke failure or deploy failure MUST fail the workflow, alert humans, and point to recovery documentation.

#### Scenario: Smoke failure prevents deploy
- GIVEN smoke validation fails before deployment
- WHEN the pipeline evaluates deploy eligibility
- THEN deployment is blocked and an alert/runbook pointer is available

#### Scenario: Post-deploy recovery is manual
- GIVEN a deployed service needs recovery
- WHEN operators follow v1 policy
- THEN they restore from the pre-rebuild backup documented by the runbook

### Requirement: Self-Hosted Runner Documentation

The repository MUST document endpoint runner prerequisites, install steps, labels, registration token rotation, and hardening checklist.

#### Scenario: Operator can register runner
- GIVEN a new endpoint runner is needed
- WHEN an operator follows the runner setup guide
- THEN required labels, secrets, Docker access, and local paths are configured

#### Scenario: Token rotation is documented
- GIVEN a registration token is expired or exposed
- WHEN an operator follows the guide
- THEN token rotation steps are clear and auditable

### Requirement: Strict TDD Commitment

Every workflow or script introduced by this change MUST have an automated test or verifiable check paired in the tasks phase.

#### Scenario: New workflow has verification
- GIVEN a task introduces workflow behavior
- WHEN `sdd-tasks-minimax` plans implementation
- THEN it includes ShellCheck, config validation, pytest, Vitest, build, or smoke evidence as applicable

#### Scenario: Manual evidence requires justification
- GIVEN automation is not reasonable for a check
- WHEN tasks are written
- THEN the task documents why manual evidence is acceptable under strict TDD policy

## Open Questions

None.

## Resolved Decisions

| Decision | Resolution | Source |
|---|---|---|
| Alert channel on CD failure | GitHub Issue with label `cd-failure`, opened automatically by the workflow | User confirmation (spec round) |
| Deployment concurrency group | `cd-main` (CD only fires on `main`, so a single group suffices and serializes correctly) | Default + project convention |
| Smoke startup timeouts | Backend health wait: 120s. Frontend health wait: 90s. Both configurable via workflow `env:` block | Default reasonable for compose cold start on the endpoint |
| Chain strategy | `feature-branch-chain` — PR1 targets `main`; PR2..PR6 each target the previous PR's branch. Only the PR1-tracker chain's last merge lands on `main` via fast-forward. | User confirmation (spec round) |
| Rollback policy v1 | No auto-rollback. Smoke gate + GitHub Issue alert + human restores from `safe-rebuild.sh` pre-rebuild backup | Proposal (locked) |
