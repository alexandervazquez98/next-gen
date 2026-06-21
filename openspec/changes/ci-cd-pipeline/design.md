# Design: CI/CD Pipeline

## Technical Approach

Add six small GitHub Actions slices around existing project entry points: `backend/Dockerfile`, `frontend/Dockerfile` plus new `frontend/Dockerfile.prod`, `docker-compose.yml`, and unchanged `scripts/safe-rebuild.sh`. Hosted runners cover CI; the CD lane runs only on the production self-hosted runner and calls the same deploy script operators already trust.

## Architecture Decisions

| Area | Choice | Rejected | Rationale |
|---|---|---|---|
| D1 topology | One workflow per lane: `lint.yml`, `backend-ci.yml`, `frontend-ci.yml`, `build.yml`, `smoke.yml`, `cd.yml` | per-PR workflows; reusable workflows | Keeps each PR reviewable and avoids reusable indirection before patterns stabilize. |
| D4 changed lint | `tj-actions/changed-files` feeds Ruff/Black and ESLint/Prettier path lists | full-repo lint | Protects PR1 from legacy churn. Ruff/Black run `check` on changed `.py`; frontend tools run with `--max-warnings 0` on changed TS/TSX. |
| D8 chain tooling | `git-town` | manual rebase; gh-stack | Manual stacks rot under six PRs. `git-town` fits feature-branch chains and lowers polluted-diff risk. Dev prerequisite: install/configure `git-town`. |

PR6 call graph:

```text
PR5 smoke.yml: pull_request/push -> compose up -> health waits -> Playwright -> compose down (no -v)
main fast-forward merge -> cd.yml push:main -> self-hosted runner -> validate-env -> safe-rebuild --dry-run -> safe-rebuild -> issue on failure
manual: workflow_dispatch(dry_run:boolean) -> same runner -> dry-run only when requested
```

## File Changes

| Req | PR | Files/components |
|---|---:|---|
| Workflow Skeleton | 1 | `.github/workflows/lint.yml`; shared path filters per workflow |
| Changed-File Lint | 1 | `.github/workflows/lint.yml`, backend lint config, frontend lint/prettier config |
| Dependabot | 1 | `.github/dependabot.yml`: `github-actions` `/`, `pip` `/backend`, `npm` `/frontend`; weekly; grouped minor/patch; labels `dependencies`, scoped labels; ignore major updates initially |
| Backend CI | 2 | `.github/workflows/backend-ci.yml`, `backend/pytest.ini` read only |
| Frontend CI | 3 | `.github/workflows/frontend-ci.yml`, `frontend/package.json` scripts |
| Build Images | 4 | `.github/workflows/build.yml`, create `frontend/Dockerfile.prod`; read `backend/Dockerfile` |
| Smoke + Playwright | 5 | `.github/workflows/smoke.yml`, `frontend/playwright.config.ts`, `frontend/test/e2e/*.spec.ts` |
| CD Lane | 6 | `.github/workflows/cd.yml`; reads `scripts/validate-env.sh`, `scripts/safe-rebuild.sh` unchanged |
| Rollback v1 | 6 | `docs/ci-cd-runbook.md`, CD failure issue body |
| Self-hosted Runner Docs | 6 | `docs/self-hosted-runner.md` |
| Strict TDD | all | workflow validation paired with each slice |

## Interfaces / Contracts

Self-hosted runner labels: `self-hosted`, `linux`, `x64`, `production`, `next-gen`, `cd`. Capabilities: Docker Compose v2, repo checkout, `sh`, `gh`, write access to durable `BACKUP_DIR`, host `.env`, and `scripts/` callable from repo root. OS: patched Linux with systemd runner service. Verification maps one-to-one: label check in workflow, `docker compose version`, `test -f .env`, `sh scripts/validate-env.sh --check-backup-dir`, `test -w "$BACKUP_DIR"`, `gh auth status`. Rotation: remove old runner in GitHub, revoke token, register new short-lived token, restart service; document monthly/offboarding rotation. Hardening: least-privilege runner user in docker group, no untrusted fork CD, locked workdir permissions, log redaction, patch cadence.

Secrets: `GITHUB_TOKEN` creates `cd-failure` issues with `issues: write`; scoped per workflow, rotated by GitHub. `SELF_HOSTED_RUNNER_TOKEN` is never stored in repo; generated during registration and rotated by re-registration. Production `.env` secrets (`NEO4J_PASSWORD`, `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, optional CLI/AI values) remain host-local; no workflow logs values; rotation updates host `.env` then runs `validate-env.sh`. Dependabot uses no custom secret in v1.

Smoke/Playwright: runner starts existing `docker-compose.yml` services, waits backend 120s and frontend 90s using existing healthchecks/HTTP probes, runs Playwright from `frontend/` as the test runner against published ports, then `docker compose down` without `-v`.

CD job: checkout, assert runner contract, `sh scripts/validate-env.sh --check-backup-dir`, `sh scripts/safe-rebuild.sh --dry-run`, real `sh scripts/safe-rebuild.sh` unless dispatch `dry_run=true`, and on failure create a GitHub Issue labeled `cd-failure`. Use `concurrency: { group: cd-main, cancel-in-progress: false }`.

Branches: `cicd/lint-dep-skeleton` -> `cicd/backend-ci` -> `cicd/frontend-ci` -> `cicd/build-images` -> `cicd/smoke-playwright` -> `cicd/cd-lane`. PR1 targets `main`; PR2..PR6 target the previous branch. After reviews, merge bottom-up into parent branches, then fast-forward the final integrated chain to `main` through the PR1 tracker path.

## Testing Strategy

| PR | Proof |
|---:|---|
| 1 | actionlint/yamllint, ShellCheck existing workflow, Dependabot schema evidence, changed-file lint fixture |
| 2 | `cd backend && python -m pytest` with strict markers and coverage |
| 3 | `corepack pnpm install --frozen-lockfile`; `corepack pnpm test:coverage` |
| 4 | backend and frontend prod `docker build` |
| 5 | compose smoke plus 1-2 Playwright tests: frontend HTML and backend HTTP 200 |
| 6 | runner contract checks plus `safe-rebuild.sh --dry-run`; issue alert dry-run/manual evidence |

## Migration / Rollout

No data migration. Roll out through the six chained PRs; CD auto-deploys only after the integrated chain lands on `main`.

## Risks and Mitigations

R1 missing `docker/postgres/data`: smoke must create host dirs or use safe compose defaults. R2 Dependabot disabled: PR1 fixes. R3 Neo4j/APOC mismatch: backend CI should mock APOC unless required. R4 frontend Dockerfile dev-only: PR4 adds prod file. R5 Corepack unavailable: setup-node/corepack enable. R6 linter churn: changed-file scope. R7 endpoint secrets: keep host-local, redact logs. R8 Docker required: CD self-hosted only. R9 400-line budget: six slices. R10 active OpenSpec conflicts: touch only this change. New: runner offline, stack rebase pain, secret leakage, deploy killed mid-flight; mitigate with docs, `git-town`, masked logs, and `cancel-in-progress:false`.

## Open Questions

None.
