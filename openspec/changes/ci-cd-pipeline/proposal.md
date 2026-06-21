# Proposal: CI/CD Pipeline

## Intent

next-gen has no automated CI/CD beyond ShellCheck. Deploys are manual `scripts/safe-rebuild.sh` runs on the endpoint, Dependabot is disabled by invalid config, and each release depends on operator discipline. Desired outcome: PRs are auto-tested and auto-built; every merge to `main` auto-deploys through the same trusted `safe-rebuild.sh` on a production self-hosted runner.

## Scope

### In Scope
- Six chained PRs: lint, backend CI, frontend CI, build, smoke/Playwright, CD.
- Add frontend production Dockerfile; fix Dependabot; document self-hosted runner setup.
- Strict TDD/test-first for every lane that introduces logic.

### Out of Scope
- DB schema migration automation beyond existing `safe-rebuild.sh` behavior.
- Secret manager introduction; use GitHub Secrets plus ephemeral `.env`/host-local `.env`.
- Non-endpoint targets, broad E2E, multi-cloud, blue/green, canary.

## Capabilities

### New Capabilities
- `ci-cd-pipeline`: GitHub Actions lanes, smoke validation, and endpoint CD contract.

### Modified Capabilities
- None.

## Business Rules and Constraints

- 400 changed-line review budget per PR; force-chained delivery.
- Frozen pnpm lockfile via Corepack; hosted CI may run on `ubuntu-latest`.
- No auto-merge without required tests; CD auto-runs on `main` merge.
- CD uses a self-hosted runner on the endpoint, with Docker and `BACKUP_DIR` local.
- Deployment concurrency lock prevents parallel deploys; never use `docker compose down -v`.
- **Rollback policy (v1):** no auto-rollback. The smoke lane (PR5) is the deployment gate; on failure the CD workflow fails, an alert is raised, and a human restores from the pre-rebuild backup (existing `safe-rebuild.sh` behavior). Image-tag rollback and DB restore are explicitly deferred to a future change.
- PR1 boundary: lint + Dependabot fix + workflow skeleton only (~250 lines).

## Chained PR Plan

| PR | Scope | Est. | Verification gate |
|---|---|---:|---|
| PR1 — Lint + Dependabot fix + workflow skeleton | Changed-file lint config; workflow skeleton; `.github/dependabot.yml` fix | ~250 | ShellCheck + config validation |
| PR2 — Backend CI | Ruff/Black/Pytest on PR; scheduled nightly with Neo4j + Postgres services | ~300 | `python -m pytest` + strict markers |
| PR3 — Frontend CI | ESLint/Prettier + Vitest on PR; pnpm via Corepack | ~200 | `corepack pnpm test:run` |
| PR4 — Build lane + prod Dockerfile for frontend | Multi-stage frontend prod Dockerfile; backend image build smoke | ~350 | `docker build` succeeds |
| PR5 — Smoke lane + Playwright | Compose stack; 2 smoke tests: frontend HTML + backend endpoint | ~350 | Playwright smoke suite |
| PR6 — CD lane | Self-hosted runner job calls `safe-rebuild.sh` on `main`; concurrency; `workflow_dispatch` dry-run | ~300 | dry-run + deploy job logs |

## Approach

Use GitHub Actions. Reuse `scripts/safe-rebuild.sh` unchanged for CD; introduce lanes incrementally so each slice is reviewable and reversible.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `.github/workflows/` | New | CI, smoke, and CD workflows |
| `.github/dependabot.yml` | Modified | Enable GitHub Actions, backend pip, frontend pnpm/npm updates |
| `frontend/Dockerfile.prod` | New | Production frontend image |
| `docs/` | Modified | Self-hosted runner and release behavior docs |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Runner offline/misconfigured | Med | Document setup; dry-run dispatch |
| Main failure after deploy | Med | No auto-rollback in v1; smoke lane is the gate; human restores from `safe-rebuild.sh` pre-rebuild backup. Image-tag rollback deferred to a future change. |
| Legacy lint churn | Med | Scope PR1 lint to changed files |

## Rollback Plan

**Workflow rollback (this change):** disable or revert the affected workflow PR. For CD issues, disable the CD workflow/concurrency group and run the existing manual `safe-rebuild.sh` path from the endpoint.

**Service rollback (this change):** none automatic. If smoke fails after a `main` deploy, the CD job fails and an alert is raised; a human restores state by replaying the pre-rebuild backup captured at the start of that deploy (existing `safe-rebuild.sh` + `pre-rebuild-backup.sh` flow).

**Service rollback (future change, explicitly out of scope here):** image-tag pinning plus smoke-gated image swap, with DB schema left untouched.

## Dependencies

- GitHub Actions, GitHub Secrets, endpoint self-hosted runner with Docker and local `BACKUP_DIR`.

## Success Criteria

- [ ] PR checks cover lint, backend, frontend, build, and smoke lanes.
- [ ] Merge to `main` triggers one serialized deploy through `safe-rebuild.sh`.
- [ ] Dependabot opens valid dependency PRs.

## Open Edge Cases / Decision Gaps for Spec

- Rollback policy: **resolved for v1 (no auto-rollback, smoke gate + human recovery).** Spec must encode the alert + recovery runbook references.
- Confirm smoke endpoint names and acceptable startup timeouts.
- Confirm self-hosted runner hardening/rotation ownership.
