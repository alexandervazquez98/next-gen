# Tasks: CI/CD Pipeline

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1750 across 6 PR slices (250 / 300 / 200 / 350 / 350 / 300) |
| 400-line budget risk | Low (per slice, enforced by chain) — overall High without chain |
| Chained PRs recommended | Yes (locked) |
| Delivery strategy | force-chained via `feature-branch-chain` (git-town) |
| Chain strategy | feature-branch-chain |
| Decision needed before apply | No (delivery strategy + chain already cached) |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: Low (per slice; overall High without chain)

### Suggested Work Units (chain order)

| # | Goal | Branch base | Merge into | Notes |
|---|------|-------------|------------|-------|
| PR1 | Lint + Dependabot fix + workflow skeleton | `main` | `main` | First slice lands on main; gates later lanes. |
| PR2 | Backend CI (pytest strict-markers + coverage) | `cicd/lint-dep-skeleton` | `cicd/lint-dep-skeleton` | Reuses workflow skeleton path filters. |
| PR3 | Frontend CI (Corepack pnpm + Vitest + ESLint/Prettier) | `cicd/backend-ci` | `cicd/backend-ci` | Wires ESLint/Prettier from PR1 into gate. |
| PR4 | Build lane + `frontend/Dockerfile.prod` | `cicd/frontend-ci` | `cicd/frontend-ci` | Multi-stage prod image, compose profile, image smoke. |
| PR5 | Smoke lane + Playwright (health waits, no `-v`) | `cicd/build-images` | `cicd/build-images` | Stack up, 2 smoke specs, compose down. |
| PR6 | CD lane (self-hosted, `cd-main`, issue alert) | `cicd/smoke-playwright` | `cicd/smoke-playwright` | Last slice; fast-forwards chain to main. |

Strict-TDD policy (`openspec/config.yaml` `sdd.strict_tdd`): every workflow or script task MUST cite an automated test/validator OR a documented manual-evidence justification.

---

## PR1 — Lint + Dependabot + Workflow Skeleton (~250 LOC)
**Branch**: `cicd/lint-dep-skeleton` off `main`. **Targets**: `main`. **Next base**: PR2 branches off this.

| ID | Title | Files | Reqs | Est | Deps | Verification gate | strict_tdd_evidence | Status |
|---|---|---|---|---|---|---|---|---|
| T1.1 | Fix `.github/dependabot.yml` — 3 ecosystems, groups, labels | `.github/dependabot.yml` | R3 | 40 | — | Schema check via dependabot.com/config-validator + T1.7 dry-run | Manual evidence: no public CI-side Dependabot validator; live PRs are the only authoritative proof per R3 scenario. | [x] |
| T1.2 | Add `actionlint` + `yamllint` config + validation step | `.actionlint.yaml`, `.yamllint.yml` | R1, R11 | 30 | — | `actionlint -color` clean, `yamllint .github/workflows/` | Actionlint is itself a static checker (RED→GREEN on its own install). | [x] |
| T1.3 | Backend lint config (Ruff + Black, `py311`) | `backend/ruff.toml`, `backend/pyproject.toml` | R2, R11 | 40 | — | `cd backend && ruff check backend tests`, `cd backend && black --check backend tests` | Ruff/Black dry-run on empty diff proves config validity (R2 legacy scenario). | [x] |
| T1.4 | Frontend lint config (ESLint flat + Prettier) | `frontend/eslint.config.js`, `frontend/.prettierrc.json` | R2, R11 | 40 | — | `cd frontend && corepack pnpm eslint --max-warnings 0`, `cd frontend && corepack pnpm prettier --check` | Prettier `--check` + ESLint `--max-warnings 0` on empty diff (R2 legacy scenario). | [x] |
| T1.5 | Create `.github/workflows/lint.yml` skeleton | `.github/workflows/lint.yml` | R1, R2 | 80 | T1.3, T1.4 | `actionlint .github/workflows/lint.yml` clean; empty-diff run green | T1.7 verification job is the test harness for this task. | [x] |
| T1.6 | `docs/ci-cd-runbook.md` stub (header + ToC) | `docs/ci-cd-runbook.md` | R9, R10 | 20 | — | File exists with agreed header + ToC pointing to PR6 sections | Manual evidence: stub only; full content authored in PR6 T6.2. | [x] |
| T1.7 | PR1 verification gate (actionlint + yamllint + ShellCheck + lint-on-empty-diff) | `.github/workflows/lint.yml` (adds `lint-verify` job) | R11 | 0 | T1.2, T1.5 | All four checks exit 0 on empty PR | This task IS the verification harness for PR1. | [x] |

**PR1 total**: 250 LOC. **Chain downstream**: PR2 branches off `cicd/lint-dep-skeleton`.

---

## PR2 — Backend CI (~300 LOC)
**Branch**: `cicd/backend-ci` off `cicd/lint-dep-skeleton`. **Targets**: `cicd/lint-dep-skeleton`. **Next base**: PR3 branches off this.

| ID | Title | Files | Reqs | Est | Deps | Verification gate | strict_tdd_evidence |
|---|---|---|---|---|---|---|---|
| T2.1 | `.github/workflows/backend-ci.yml` PR lane (Python 3.11, pip, pytest strict) | `.github/workflows/backend-ci.yml` | R4 | 110 | T1.5 | `python -m pytest --strict-markers --strict-config --cov` on backend-touched PR | Workflow itself enforces strict markers — unknown marker fails R4 scenario. |
| T2.2 | Nightly schedule lane with Postgres + Neo4j services (service containers) | `.github/workflows/backend-ci.yml` (adds nightly job) | R4 | 140 | T2.1 | Nightly run with `services: postgres, neo4j` healthy; `pytest -m integration` passes | Service container health + integration marker run (R4 backend PR scenario extended). |
| T2.3 | Coverage upload (Codecov OR artifact fallback) | `.github/workflows/backend-ci.yml`, `backend/.codecov.yml` if used | R4 | 30 | T2.1 | Coverage report uploaded; PR comment shows delta | Codecov upload is itself the verification action. |
| T2.4 | PR2 verification gate — backend-touched PR green | (workflow-only) | R4, R11 | 20 | T2.1–T2.3 | Open scratch PR touching `backend/`; workflow green | CI run logs are the evidence under strict TDD. |

**PR2 total**: 300 LOC. **Chain downstream**: PR3 branches off `cicd/backend-ci`.

---

## PR3 — Frontend CI (~200 LOC)
**Branch**: `cicd/frontend-ci` off `cicd/backend-ci`. **Targets**: `cicd/backend-ci`. **Next base**: PR4 branches off this.

| ID | Title | Files | Reqs | Est | Deps | Verification gate | strict_tdd_evidence |
|---|---|---|---|---|---|---|---|
| T3.1 | `.github/workflows/frontend-ci.yml` (setup-node v4 + Corepack + frozen lockfile + Vitest) | `.github/workflows/frontend-ci.yml` | R5 | 100 | T1.5 | `corepack pnpm install --frozen-lockfile` + `corepack pnpm test:run` green on frontend-touched PR | Lockfile drift fails install before tests (R5 lockfile scenario). |
| T3.2 | Wire ESLint + Prettier step on changed frontend files | `.github/workflows/frontend-ci.yml` | R2, R5 | 40 | T1.4 | `--max-warnings 0` ESLint + Prettier `--check` on changed TS/TSX exit 0 | Changed-file linter is the test for R2 + R5 wiring. |
| T3.3 | PR3 verification gate — frontend-touched PR green | (workflow-only) | R5, R11 | 60 | T3.1, T3.2 | Scratch PR touching `frontend/`; workflow green with coverage | CI run logs are the evidence under strict TDD. |

**PR3 total**: 200 LOC. **Chain downstream**: PR4 branches off `cicd/frontend-ci`.

---

## PR4 — Build + Frontend Prod Dockerfile (~350 LOC)
**Branch**: `cicd/build-images` off `cicd/frontend-ci`. **Targets**: `cicd/frontend-ci`. **Next base**: PR5 branches off this.

| ID | Title | Files | Reqs | Est | Deps | Verification gate | strict_tdd_evidence |
|---|---|---|---|---|---|---|---|
| T4.1 | Multi-stage `frontend/Dockerfile.prod` (pnpm builder + nginx/static runner) | `frontend/Dockerfile.prod`, `frontend/.dockerignore` | R6 | 80 | — | `docker build -f frontend/Dockerfile.prod frontend/` succeeds; image runs and serves dist on expected port | T4.3 build workflow is the harness; build itself is the test. |
| T4.2 | `docker-compose.yml` `frontend-prod` profile (no breaking change to dev stack) | `docker-compose.yml` | R6 | 50 | T4.1 | `docker compose --profile prod config --quiet` valid; existing dev profile unchanged | `compose config` validation is the harness; non-breaking assertion via diff review. |
| T4.3 | `.github/workflows/build.yml` (build backend + frontend:prod, smoke-run each) | `.github/workflows/build.yml` | R6 | 180 | T4.1, T4.2 | `docker build` backend + frontend:prod succeed on `ubuntu-latest`; smoke-run exits 0 | Build job is the test for R6 images-build scenario. |
| T4.4 | PR4 verification gate — both images build clean on hosted runner | `.github/workflows/build.yml` (adds `build-verify` summary) | R6, R11 | 40 | T4.3 | Run logs show both images green; broken Dockerfile blocks merge (R6 broken scenario) | Build failure on broken Dockerfile is the test for R6 broken-Dockerfile scenario. |

**PR4 total**: 350 LOC. **Chain downstream**: PR5 branches off `cicd/build-images`.

---

## PR5 — Smoke + Playwright (~350 LOC)
**Branch**: `cicd/smoke-playwright` off `cicd/build-images`. **Targets**: `cicd/build-images`. **Next base**: PR6 branches off this.

| ID | Title | Files | Reqs | Est | Deps | Verification gate | strict_tdd_evidence |
|---|---|---|---|---|---|---|---|
| T5.1 | Add `@playwright/test` devDep + `corepack pnpm install` | `frontend/package.json`, `frontend/pnpm-lock.yaml` | R7 | 30 | T3.1 | Lockfile updated; `corepack pnpm install --frozen-lockfile` clean | Lockfile diff review + reinstall is the test. |
| T5.2 | `frontend/playwright.config.ts` (compose webServer, timeouts 120s/90s) | `frontend/playwright.config.ts` | R7 | 80 | T5.1 | `corepack pnpm playwright test --list` enumerates specs; local config loads | Config dry-run + spec enumeration is the test harness. |
| T5.3 | 2 Playwright smoke specs (frontend HTML + backend HTTP 200) | `frontend/test/e2e/frontend-html.spec.ts`, `frontend/test/e2e/backend-health.spec.ts` | R7 | 80 | T5.2 | `corepack pnpm playwright test` against compose stack green | The specs themselves are the R7 smoke-validates-serving-paths test. |
| T5.4 | `.github/workflows/smoke.yml` (compose up, health waits 120s/90s, Playwright, compose down no `-v`) | `.github/workflows/smoke.yml` | R7 | 120 | T5.3 | Workflow green on PR touching compose/services; unhealthy stack tears down without `-v` | T5.3 specs + T5.5 dir-creation are the tests for R7 unhealthy-stack scenario. |
| T5.5 | Document `docker/postgres/data` host dir creation (R1 mitigation) | `docker/README.md` or compose comment | R6, R7 | 10 | — | First-run `compose up` creates dir; doc snippet present | Manual evidence: compose default-bind-creates behavior; doc snippet is the artifact. |
| T5.6 | PR5 verification gate — smoke workflow green on PR | `.github/workflows/smoke.yml` | R7, R11 | 30 | T5.4 | Open scratch PR touching compose/services; workflow green | CI run logs are the evidence under strict TDD. |

**PR5 total**: 350 LOC. **Chain downstream**: PR6 branches off `cicd/smoke-playwright`.

---

## PR6 — CD Lane (~300 LOC)
**Branch**: `cicd/cd-lane` off `cicd/smoke-playwright`. **Targets**: `cicd/smoke-playwright`. **Final**: fast-forward chain to `main`.

| ID | Title | Files | Reqs | Est | Deps | Verification gate | strict_tdd_evidence |
|---|---|---|---|---|---|---|---|
| T6.1 | `docs/self-hosted-runner.md` (install, registration, labels, rotation, hardening, troubleshooting) | `docs/self-hosted-runner.md` | R10 | 120 | — | Doc present with sections for labels `self-hosted,linux,x64,production,next-gen,cd`; rotation steps; hardening checklist | Manual evidence: operator walkthrough documented per R10 scenarios; no CI-runnable substitute. |
| T6.2 | `docs/ci-cd-runbook.md` full content (deploy procedure, recovery via `safe-rebuild.sh` pre-rebuild backup, alert ack) | `docs/ci-cd-runbook.md` | R9, R10 | 80 | T1.6 | Doc references `scripts/safe-rebuild.sh` + `pre-rebuild-backup.sh`; alert section points to GitHub Issue label `cd-failure` | Manual evidence: runbook is human-facing artifact per R9 post-deploy-recovery scenario. |
| T6.3 | `.github/workflows/cd.yml` shell (push main, `workflow_dispatch(dry_run:boolean)`, concurrency `cd-main` cancel-in-progress false, self-hosted runs-on) | `.github/workflows/cd.yml` | R8 | 80 | T1.5, T5.6 | `actionlint` clean; `concurrency.group == "cd-main"`; runs-on labels match T6.1 doc | `actionlint` is the test; CD YAML is the R8 main-merge-deploys-once harness. |
| T6.4 | Wire CD steps (checkout, assert runner contract, `validate-env.sh`, `safe-rebuild.sh --dry-run`, real `safe-rebuild.sh`, on failure create GitHub Issue labeled `cd-failure`) | `.github/workflows/cd.yml`, `scripts/assert-runner-contract.sh` (new, ~30 LOC) | R8, R9 | 40 | T6.3 | `scripts/test-cd-contract.sh` (T6.5) green; dispatch `dry_run=true` record created | T6.5 contract test is the harness for R8 deployment-failure-alerts scenario. |
| T6.5 | `scripts/test-cd-contract.sh` — asserts CD YAML parses, actionlint clean, runner-contract script validates labels and Docker/Compose presence | `scripts/test-cd-contract.sh` | R8, R11 | 50 | T6.4 | `sh scripts/test-cd-contract.sh` exits 0 in CI | This task IS the test for T6.4 under strict TDD. |
| T6.6 | PR6 verification gate — `actionlint` clean; `workflow_dispatch` dry-run record; manual deploy drill documented | `.github/workflows/cd.yml` | R8, R9, R11 | 30 | T6.5 | Dry-run dispatch creates dry-run record; runbook reachable from issue body | Manual evidence per R11 manual-evidence-requires-justification: real deploy to production endpoint cannot be automated in PR CI; dry-run + manual drill is the documented substitute. |

**PR6 total**: ~400 LOC at upper bound. If actual diff trends >400, split T6.1 (runner doc) into its own `docs/runner` PR immediately before PR6 lands. **Chain end**: after PR6 merges into `cicd/smoke-playwright`, fast-forward the integrated chain into `main` per `feature-branch-chain`.

---

## Review Workload Forecast (consolidated)

| PR | Tasks | Est LOC | Risk vs 400 | Cumulative LOC |
|---|---|---:|---|---:|
| PR1 | 7 | 250 | Low | 250 |
| PR2 | 4 | 300 | Low | 550 |
| PR3 | 3 | 200 | Low | 750 |
| PR4 | 4 | 350 | Low | 1100 |
| PR5 | 6 | 350 | Low | 1450 |
| PR6 | 6 | ~400 | Medium (watch T6.1+T6.5 split) | ~1850 |

- Total tasks: **30**.
- Total project impact: ~30 new/modified files, ~1850 LOC, 6 new workflow files, 2 new docs, 1 new Dockerfile, 1 new compose profile, 1 new shell contract test.
- 400-line flag: PR6 is the only slice at the upper edge — the contingency split above keeps the chain safe.
- Strict TDD: every task cites an automated validator OR a `manual evidence` justification per `openspec/config.yaml` `sdd.strict_tdd` policy.
- Chain integrity: each PR's `Branch base`/`Targets` enforce `feature-branch-chain` so child diffs stay focused; if GitHub shows previous slice content in a child diff, rebase/retarget before review.
