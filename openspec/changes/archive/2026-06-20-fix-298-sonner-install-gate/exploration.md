# Exploration: fix-298-sonner-install-gate

> Investigation for SDD cycle `fix-298-sonner-install-gate` (issue #298).
> Status: **partial** — bug reproduction confirms the env-only nature of the
> failure, and most CI install gates already exist on `cicd/cd-lane`; what is
> missing is (a) explicit documentation for non-Docker local dev and (b)
> an optional pre-flight script.

## TL;DR

| Finding | Confidence |
| --- | --- |
| Bug reproduces (env-only). Wiping `node_modules/sonner` triggers the exact Vite error from issue #298. | High — reproduced in a temporary worktree, then removed. |
| `frontend-ci.yml` and `smoke.yml` ALREADY have explicit `pnpm install --frozen-lockfile` steps on `cicd/cd-lane` (NOT yet on `main`). | High — quoted lines below. |
| `smoke.yml` does NOT run `pnpm dev` directly; it uses the Docker frontend (whose Dockerfile runs install). | High — quoted lines below. |
| `frontend/README.md` does not exist; root `README.md` documents only the Docker path. | High — verified. |
| No pre-flight script (`scripts/check-frontend-deps.sh`) exists. | High — `ls scripts/` enumerated all 7 scripts; none are about frontend dep health. |
| `<Toaster />` is not mounted anywhere in `frontend/App.tsx`. | High — `git show main:frontend/App.tsx` confirmed. |
| Forecast for the fix: ~50–200 changed lines. Single PR. No chained PRs. | High — budget well below 400. |

## 1. Bug Reproduction (verified)

Worktree: `/home/alex/dev/next-gen/worktrees/fix-298-repro` based on `main@49dda73`.
Removed after verification (`git worktree remove --force`).

Steps run (with captured output):

1. `git worktree add /home/alex/dev/next-gen/worktrees/fix-298-repro main`
2. `cd .../fix-298-repro/frontend`
3. `ls node_modules/sonner` → "No such file or directory" (fresh checkout has no node_modules)
4. `grep sonner package.json` → 1 hit (matches issue claim)
5. `grep "from 'sonner'" context/AuthContext.tsx` → 1 hit (matches issue claim)
6. `pnpm install --frozen-lockfile` (succeeded in 887ms using pnpm@10.12.1 via corepack — the
   `packageManager` pin is honored even when the system pnpm is 11.4.0).
7. `rm -rf node_modules/sonner` (simulate "stale node_modules" scenario from the issue).
8. `pnpm exec vite build` → **REPRODUCED** with the exact error from issue #298:
   ```
   error during build:
   [vite]: Rollup failed to resolve import "sonner" from
     ".../frontend/context/AuthContext.tsx".
   This is most likely unintended because it can break your application at runtime.
   ```
9. `pnpm exec vite --port 13001` (dev mode startup) → **REPRODUCED** with the dev-server
   flavor of the same error:
   ```
     VITE v6.4.1  ready in 223 ms
     ➜  Local:   http://localhost:13001/
   Error: The following dependencies are imported but could not be resolved:
     sonner (imported by .../frontend/context/AuthContext.tsx)
   Are they installed?
   ```
10. Recovery: `pnpm install --frozen-lockfile` → `Done in 887ms using pnpm v10.12.1`,
    `node_modules/sonner` restored, `pnpm exec vite --port 13002` starts cleanly.
11. `pnpm --dir .../fix-298-repro/frontend run test:run` → **57 files, 479 tests pass**
    (issue claim said 476; current count is 479 — net +3 since the issue was filed).
12. `git worktree remove --force` (cleanup confirmed via `git worktree list`).

**Conclusion**: Bug claim is correct. Failure is purely a missing `node_modules/sonner`.
Source-of-truth files (`package.json`, `pnpm-lock.yaml`, `context/AuthContext.tsx`) are
internally consistent at `v1.13.2`. No code change is required to make the import resolve;
`pnpm install --frozen-lockfile` is sufficient.

## 2. CI Workflows — Current State

> **Important scope note**: The workflows below live on the integration branch
> `cicd/cd-lane` (`8bacc83`), NOT on `main` (`49dda73`). On `main`, the only workflow is
> `shellcheck.yml`. The install gates exist as part of the still-unmerged
> `ci-cd-pipeline` chain (PR1..PR6). When that chain fast-forwards into `main`, these gates
> become the baseline.

### `.github/workflows/frontend-ci.yml` (PR3 of ci-cd-pipeline)

Step list (relevant excerpt):

```yaml
75:  - name: Set up Node 22
76:    if: steps.changed.outputs.any_changed == 'true'
77:    uses: actions/setup-node@v4
78:    with:
79:      node-version: "22"
80:      cache: "pnpm"
81:      cache-dependency-path: frontend/pnpm-lock.yaml
82:
83:  - name: Enable Corepack
84:    if: steps.changed.outputs.any_changed == 'true'
85:    run: corepack enable
86:
87:  - name: Install frontend dependencies (frozen lockfile)
88:    if: steps.changed.outputs.any_changed == 'true'
89:    run: pnpm --dir frontend install --frozen-lockfile
90:
91:  - name: Verify Vitest install
92:    if: steps.changed.outputs.any_changed == 'true'
93:    working-directory: frontend
94:    run: pnpm exec vitest --version
95:
96:  - name: Run Vitest
97:    if: steps.changed.outputs.any_changed == 'true'
98:    run: pnpm --dir frontend run test:run
```

Verdict: **Acceptance criterion #1 is satisfied on `cicd/cd-lane`** — `corepack enable`
runs on L85, then the explicit `pnpm --dir frontend install --frozen-lockfile` on L89
runs BEFORE `vitest --version` (L94) and `vitest run` (L98). The `ci-verify` job at L152–154
also has `corepack prepare pnpm@10.12.1 --activate` and the same install command.

The only cosmetic gap vs the issue's wording (`corepack pnpm install --frozen-lockfile`
on the same line) is that the workflow uses `pnpm --dir frontend install` instead of
`corepack pnpm install`. They are functionally identical when `corepack enable` ran on
L85. A one-line cosmetic edit could harmonize the wording if desired.

### `.github/workflows/smoke.yml` (PR5 of ci-cd-pipeline)

Step list (relevant excerpt):

```yaml
198:  - name: Set up Node 22
199:    uses: actions/setup-node@v4
200:    with:
201:      node-version: "22"
202:      cache: "pnpm"
203:      cache-dependency-path: frontend/pnpm-lock.yaml
204:
205:  # corepack pins pnpm to the version declared in package.json
206:  # (`packageManager: pnpm@10.12.1`). The frontend preinstall guard
207:  # blocks npm — see frontend/package.json.
208:  - name: Enable Corepack
209:    run: corepack enable
210:
211:  - name: Install frontend dependencies (frozen lockfile)
212:    run: pnpm --dir frontend install --frozen-lockfile
213:
214:  - name: Install Playwright browsers
215:    run: pnpm --dir frontend exec playwright install --with-deps chromium
216:
217:  - name: Run Playwright smoke specs
218:    run: pnpm --dir frontend run test:e2e
```

Verdict: **Acceptance criterion #2 is partially satisfied** — install runs on L212 BEFORE
the Playwright step. BUT: smoke does NOT directly invoke `pnpm dev`. The frontend dev
server is the Docker frontend started by L181 (`docker compose up -d frontend`), whose
image is built from `frontend/Dockerfile` (which runs `pnpm install --frozen-lockfile` on
L6). So the smoke lane exercises the Docker path, not the raw `pnpm dev` path. The
specific failure mode from issue #298 (local `pnpm dev` outside Docker) is not directly
covered by smoke.

### `.github/workflows/lint.yml` (PR1 skeleton)

Already explicit at L207–209:

```yaml
207:  - name: Install dependencies
208:    if: steps.changed.outputs.any_changed == 'true'
209:    working-directory: frontend
210:    run: corepack pnpm install --frozen-lockfile
```

Verdict: Has explicit install gate. No change needed.

### `.github/workflows/build.yml` (PR4)

No direct `pnpm install` — uses Docker build of `frontend/Dockerfile.prod`, which bakes
in `corepack pnpm install --frozen-lockfile` (Dockerfile.prod L38–39). Verdict: N/A.

### `.github/workflows/cd.yml` (PR6)

No direct `pnpm install` — uses `scripts/safe-rebuild.sh` (docker-compose based). The
script does NOT contain any `pnpm install` calls (verified). Verdict: N/A.

### `.github/workflows/backend-ci.yml` (PR2)

Has Python `pip install` (L86–92). Backend-only, no frontend touch. Verdict: N/A.

### `.github/workflows/shellcheck.yml`

Shell-only, no Node. Verdict: N/A.

### Summary table

| Workflow | Install gate for frontend? | Verdict |
| --- | --- | --- |
| `frontend-ci.yml` | L89 `pnpm --dir frontend install --frozen-lockfile` | ✅ Satisfies AC#1 |
| `smoke.yml` | L212 same; runs Playwright on Docker frontend | ⚠️ Install OK; does NOT run raw `pnpm dev` |
| `lint.yml` | L209 `corepack pnpm install --frozen-lockfile` | ✅ |
| `build.yml` | via Dockerfile.prod internal install | N/A |
| `cd.yml` | via scripts/safe-rebuild.sh → docker | N/A |
| `backend-ci.yml` | pip install (backend) | N/A |
| `shellcheck.yml` | none needed | N/A |

## 3. Documentation — Current State

### `frontend/README.md`

**Does not exist** (`ls frontend/README.md` → no such file). Acceptance criterion #3 says
"create if missing" — so this is an explicit deliverable.

### Root `README.md`

The "Setup local" section (L61–67) documents ONLY the Docker path:

```markdown
## Setup local
1. Copia variables base: `cp .env.example .env`.
2. Levanta servicios: `docker-compose up -d`.
3. Frontend: `http://localhost:3000`.
4. Backend docs: `http://localhost:8000/docs`.
5. Neo4j Browser: `http://localhost:7474`.
```

No mention of `pnpm install` for non-Docker local development. Frontend test command is
shown (L88) but assumes install was done. A developer who runs `pnpm dev` directly (as
the issue does) finds no install instruction.

The README DOES link to `docs/supply-chain.md` (L38), which IS the install policy doc.

### `docs/supply-chain.md`

Relevant excerpt (from L8–19):

```markdown
2. Install from `frontend`: `corepack pnpm install --frozen-lockfile`.
3. Add dependencies from `frontend`: `corepack pnpm add <package>`.
4. Never run `npm install` in `frontend`; the package has a `preinstall` guard
   that fails non-pnpm installs.
5. Commit `frontend/pnpm-lock.yaml` with dependency changes.
...
| Lockfile | Docker and CI-style installs must use `corepack pnpm install --frozen-lockfile`. |
```

Verdict: The policy IS documented. The gap is that there's no discoverable "if you just
cloned and ran `pnpm dev`, here is what to do" walkthrough — `docs/supply-chain.md` is
about policy, not onboarding.

### `CONTRIBUTING.md`

**Does not exist**.

### `docs/USER_GUIDE.md` and `docs/AI_AGENT_GUIDE.md`

No mentions of `pnpm` / `node_modules` / install (grep returns nothing).

## 4. Docker Setup — Current State

### `docker-compose.yml` (frontend service, L108–136)

```yaml
108:  # Frontend (Vite Service)
109:  frontend:
110:    build:
111:      context: ./frontend
112:      dockerfile: Dockerfile
113:    container_name: nexgen_frontend
114:    ports:
115:      - "${FRONTEND_EXTERNAL_PORT:-3000}:3000"
116:    depends_on:
117:      backend:
118:        condition: service_healthy
119:    volumes:
120:      - ./frontend:/app
121:      - /app/node_modules
122:    environment:
123:      - VITE_API_TARGET=${VITE_API_TARGET:-http://nexgen_backend:8000}
```

The `volumes` block binds `./frontend` to `/app` for hot reload, plus an anonymous
volume on `/app/node_modules` so the host's potentially-stale `node_modules` doesn't
shadow the image's freshly-installed one. This is a good mitigation but the
**bind-mount + image-build contract** still requires `docker compose build` (or first-run
auto-build) for the image's `node_modules` to exist.

### `frontend/Dockerfile` (dev, used by docker-compose)

```dockerfile
FROM node:20-alpine

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml .npmrc pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .

# Expose Vite dev port
EXPOSE 3000

CMD ["pnpm", "run", "dev", "--", "--host"]
```

The dev Dockerfile does `pnpm install --frozen-lockfile` at build time. **But** the
node base image is `node:20-alpine` while the project pins `pnpm@10.12.1` (which works
with Node 20, but the prod Dockerfile uses `node:22-alpine` for consistency). Cosmetic
drift, not a bug.

### `frontend/Dockerfile.prod` (production, used by build lane + docker-compose.prod.yml)

```dockerfile
23:  FROM node:22-alpine AS builder
24:
25:  WORKDIR /app
26:
27:  RUN corepack enable
28:
29:  COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
30:
31:  RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
32:      corepack pnpm install --frozen-lockfile
```

Install gate baked in. No change needed.

### `scripts/safe-rebuild.sh` (used by `cd.yml`)

`grep -iE 'install|pnpm|node_modules' scripts/safe-rebuild.sh` → no matches. The script
is docker-compose-based and inherits the install from the Dockerfiles. No change needed.

## 5. Pre-flight Scripts and Makefile Targets

### `scripts/` directory

| File | Purpose (verified via filename + grep) | Install-related? |
| --- | --- | --- |
| `ci-cd-check-runner-contract.sh` | CI runner contract verifier | No |
| `pre-rebuild-backup.sh` | Pre-rebuild backup orchestration | No |
| `safe-rebuild.sh` | Docker rebuild orchestrator | No (delegates to Dockerfile) |
| `test-ci-cd-check-runner-contract.sh` | Tests for contract script | No |
| `test-neo4j-offline-backup-flags.sh` | Tests for offline backup flags | No |
| `test-safe-rebuild-path-validation.sh` | Tests for path validation | No |
| `validate-env.sh` | .env / BACKUP_DIR validation | No |

Verdict: No `check-frontend-deps.sh`. Acceptance criterion #4 would be a NEW file.

### Makefile

`Makefile` and `frontend/Makefile` both absent (`ls` → no matches). Project does not use
Make. Verdict: no Makefile target to wire the pre-flight into.

### `frontend/package.json` scripts

Existing (L7–21):

```json
"preinstall": "node -e \"...pnpm/... guard...\"",
"dev": "vite",
"build": "vite build",
"preview": "vite preview",
"test": "vitest",
"test:run": "vitest run",
"test:coverage": "vitest run --coverage",
"test:e2e": "playwright test",
"test:e2e:ui": "playwright test --ui",
"lint": "eslint --max-warnings=0",
"lint:fix": "eslint --fix",
"format": "prettier --write",
"format:check": "prettier --check"
```

No `predev` hook. Adding `predev: "bash ../scripts/check-frontend-deps.sh"` would block
dev startup if the sentinel is missing — but a hard block would frustrate the
"hot-iteration" case. Better as advisory (warn-only) or guarded by a sentinel file.

### `frontend/pnpm-workspace.yaml`

```yaml
packages:
  - .

strictDepBuilds: true

onlyBuiltDependencies:
  - esbuild

ignoredBuiltDependencies:
  - '@google/genai'
  - protobufjs
```

`strictDepBuilds: true` means new dependency build scripts must be approved here before
they run. Not install-related per se, but related to the "fresh-install safety" theme.

## 6. Strict TDD Applicability

`openspec/config.yaml` declares `tdd_policy: strict_tdd` with
`manual_evidence_allowed_when: "No relevant automated test can be reasonably created."`

Per-criterion verdicts:

| AC | Testable RED-first? | Approach |
| --- | --- | --- |
| #1 — CI install gate in `frontend-ci.yml` | Hard (YAML not unit-testable). | **Manual evidence**: workflow already passes on `cicd/cd-lane`; after the change it must still pass. Spec scenario "Frontend PR runs tests" already covers it. |
| #2 — Smoke verifies `pnpm dev` resolves | Partial. Could add a smoke step that starts `pnpm dev`, curls `:3000/`, kills it. | **Testable** as a workflow step (the step fails if import-analysis fails). Could be a unit-test-ish verification: `scripts/test-pnpm-dev-resolves.sh` that runs `pnpm exec vite build` against a clean node_modules and asserts no resolve errors. |
| #3 — README documents install | Hard (content not unit-testable). | **Manual evidence**: reviewer reads the README section. Could add a `scripts/check-readme.sh` that grep-asserts required sections exist (e.g., `^## Install`). |
| #4 — Pre-flight script | **CAN be unit-tested**. | `scripts/test-check-frontend-deps.sh`: stubs node_modules (removes sentinel), runs `check-frontend-deps.sh`, asserts it fails + triggers install; with sentinel in place, asserts it passes. RED test should be written BEFORE the script (per strict TDD). |
| #5 — Toaster mount follow-up | Easy (React render test). | Defer to child issue or include as a sub-task with a render test. |
| #6 — No regression on existing 476 tests | **Already automated**. | `pnpm --dir frontend run test:run` is the bar. Counts: 57 files / 479 tests now (vs 476 in issue). |

**Net recommendation**: strict TDD applies to the pre-flight script (AC#4) and to
AC#6. AC#1, #2 (the smoke `pnpm dev` part), #3, and #5 rely on manual evidence.
The proposal phase should explicitly call out which artifacts are RED-tested and
which are not, per `openspec/config.yaml` policy.

## 7. Forecast — Implementation Diff

| File | Change | Approx lines |
| --- | --- | --- |
| `.github/workflows/frontend-ci.yml` | Optional: rename step command from `pnpm --dir frontend install --frozen-lockfile` to `corepack pnpm install --frozen-lockfile` for consistency with `lint.yml`. | 0–1 |
| `.github/workflows/smoke.yml` | Optional: add a small step that runs `pnpm --dir frontend exec vite build` after L212 to catch non-Docker resolve failures earlier than Playwright. | 0–15 |
| `frontend/README.md` (new) | Sections: Prerequisites, Install, Dev (vite), Test, Troubleshooting (incl. "sonner missing? run pnpm install"). | 40–80 |
| `README.md` | Append a short "Local frontend dev (no Docker)" subsection pointing to `frontend/README.md`. | 5–15 |
| `scripts/check-frontend-deps.sh` (new) | Bash: check sentinel file `frontend/.frontend-deps-ok`; if missing, verify `node_modules/sonner` (and other resolved imports in AuthContext.tsx + App.tsx); if any missing, run `corepack pnpm install --frozen-lockfile` and write the sentinel. | 20–40 |
| `scripts/test-check-frontend-deps.sh` (new) | Unit tests for the above (RED-first per strict TDD). | 30–60 |
| `frontend/package.json` | Optional: `"predev": "bash ../scripts/check-frontend-deps.sh"` — advisory-only (prints warning but does not exit non-zero unless `--strict` flag is set). | 0–5 |
| `frontend/App.tsx` | OUT OF SCOPE for this PR. Mount `<Toaster />` here as a child issue. | 0 (deferred) |
| `openspec/changes/fix-298-sonner-install-gate/specs/{domain}/spec.md` (new) | Delta spec: ADDED requirements for local dev install gate + frontend README + Toaster follow-up reference. | 30–60 |

**Total**: ~50–200 changed lines (well below the 400-line budget). Single PR
recommended. No chained PRs.

**`Decision needed before apply: No`**
**`Chained PRs recommended: No`**
**`400-line budget risk: Low`**

## 8. Approaches

### Approach A — Docs + Pre-flight script (Recommended)

Add `frontend/README.md` (or a `docs/frontend-dev.md`), a discoverable section in the
root `README.md`, and an opt-in `scripts/check-frontend-deps.sh` that developers can
wire into their shell rc (`source scripts/check-frontend-deps.sh` would be too heavy;
better: a `make`-free target like `pnpm --dir frontend run check:deps`).

- Pros: discoverable, no breaking change, RED-testable for the script, leaves CI gates
  untouched (they're already in `cicd/cd-lane`).
- Cons: developers must read the README or run the script manually; a missed install
  still surfaces the original error.
- Effort: Low.

### Approach B — `predev` hook in `package.json`

Add `"predev": "bash ../scripts/check-frontend-deps.sh"` so `pnpm dev` self-heals.

- Pros: zero developer effort — install runs automatically on first `pnpm dev`.
- Cons: changes dev startup latency (a few seconds for the sentinel check); might
  surprise developers who expect `pnpm dev` to be instant; could mask legitimate
  dependency drift from the developer.
- Effort: Low.

### Approach C — Just docs, no script

Add `frontend/README.md` and call it a day.

- Pros: simplest. No new scripts to maintain.
- Cons: doesn't help developers who skip the README. Doesn't RED-test anything new.
- Effort: Trivial.

### Approach D — CI-only (already done on `cicd/cd-lane`)

Argue the install gate already exists; close the issue as a documentation request.

- Pros: zero code change.
- Cons: doesn't address the LOCAL dev path that issue #298 actually reports. The bug is
  reproducible on a clean `main` checkout — the CI gate doesn't help a developer who
  runs `pnpm dev` outside Docker.

### Recommendation

**Approach A** (docs + pre-flight script as a pnpm script, no `predev` hook). The
`scripts/check-frontend-deps.sh` can be wired into `pnpm --dir frontend run check:deps`
without forcing it on every dev invocation. CI gates stay as they are on `cicd/cd-lane`.
The `<Toaster />` follow-up becomes a child issue (#298-followup) referenced in the
README's "Known gaps" section.

## 9. Risks and Open Questions

- **Critical** (none — bug reproduction matches the issue exactly).
- **Warning**: `cicd/cd-lane` has not merged to `main` yet. If `fix-298-sonner-install-gate`
  merges to `main` BEFORE `cicd/cd-lane`, the new install gate on `cicd/cd-lane` will
  arrive later via the chain fast-forward. Conversely, if `cicd/cd-lane` merges first,
  the install gate becomes baseline and this change only adds docs + script. The
  proposal should call out the ordering.
- **Warning**: The `docker-compose.yml` frontend bind-mount (`./frontend:/app`) plus
  anonymous volume (`/app/node_modules`) creates a subtle case: a developer who runs
  `docker compose build --no-cache frontend` will get a fresh `node_modules` in the
  image, but the host's `./frontend/node_modules` (if it exists from a prior local
  install) is masked by the anonymous volume. If they then run `docker compose up
  frontend`, the image's `node_modules` is used. If they run `pnpm dev` directly on the
  host (without docker), they hit the bug. The pre-flight script should detect this
  state — but the simplest correct behavior is just "always run install if sentinel
  is missing."
- **Suggestion**: pnpm cache (`~/.local/share/pnpm/store`) can hide install drift on CI
  runners that reuse cache. Current workflows pin `cache-dependency-path:
  frontend/pnpm-lock.yaml`, which SHOULD invalidate on lockfile change. Worth a smoke
  test.
- **Suggestion**: Should the `<Toaster />` follow-up be (a) part of this PR, (b) a
  child issue, or (c) a `// TODO` in the README? Recommendation: **(b) child issue** —
  it's ~5 lines of code + a render test, and it deserves its own change folder for
  spec/design review.
- **Open question**: Should the pre-flight script also check the BACKEND (Python venv)
  deps, or stay frontend-only? Recommendation: **stay frontend-only** — backend
  already has `validate-env.sh` and the backend pytest lane in `backend-ci.yml`. Adding
  backend to the pre-flight would expand scope without justification.

## 10. Surprising Findings

1. **`cicd/cd-lane` is significantly ahead of `main` for CI** — seven workflow files
   exist on `cicd/cd-lane` but only `shellcheck.yml` exists on `main`. Anyone reading
   issue #298 against `main` directly will not see the CI install gates; they have to
   know to look at `cicd/cd-lane`. The README should link to the chain landing page.
2. **The `packageManager: "pnpm@10.12.1"` pin is honored transparently** — running
   `pnpm install` with system pnpm 11.4.0 still reports "Done in 887ms using pnpm
   v10.12.1" because the corepack layer intercepts the `packageManager` field. This is
   correct but non-obvious; the README should mention it so developers aren't surprised
   by the version report.
3. **The `preinstall` guard in `frontend/package.json` (L8) checks for `pnpm/` substring
   in `npm_config_user_agent`** — this is intentionally permissive (any pnpm version
   passes, not just 10.12.1). A developer who installs with `yarn` or `npm` is blocked.
   This is correct behavior and worth documenting.

## 11. Ready for Proposal

**Yes** — bug reproduces, CI gates are documented (some on `cicd/cd-lane`, some missing),
docs gap is clear, pre-flight script has a clear RED-test path, forecast is single-PR
budget-friendly. The design phase should resolve:
1. Order of operations: does this PR merge BEFORE or AFTER `cicd/cd-lane` fast-forwards?
2. Pre-flight script: bash sentinel vs pnpm script vs `predev` hook?
3. Toaster follow-up: child issue vs same PR?
4. Test scope: which RED tests get written before which script changes?
