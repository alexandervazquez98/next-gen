# Feature Flag Activation Runbook

> Audience: operators who need to flip a feature flag in a running deploy
> without opening a pull request. Closes the workflow gap surfaced by
> [issue #546](https://github.com/alexandervazquez98/next-gen/issues/546).

## Why this exists

Before issue #546, every new feature flag required a code PR that touched
`docker-compose.yml`, `.env.example`, and at least one doc. Operators
could not flip a flag without merging a release. That friction forced
PRs like #541 and #543 to land alongside what should have been a routine
`.env` edit.

The fix is mechanical: `docker-compose.yml` now declares
`env_file: [.env]` on the five services that own an environment block,
and every feature flag uses the `${FLAG:-default}` interpolation
pattern. Operators edit `.env` and recreate the affected container.
No PR is required.

## How to flip a flag

The procedure is two steps:

1. **Edit `.env`** (the file at the repo root; it is gitignored and
   materialised per environment from `.env.example` plus a secrets
   store — see the `Materialize test-only .env` step in
   `.github/workflows/smoke.yml` for the canonical pattern).

   ```sh
   # Example: enable the CMDB PhysicalLink polling path (PR #543).
   echo 'FEATURE_CMDB_PHYSICAL_LINK_POLLING_ENABLED=true' >> .env
   ```

2. **Recreate the affected service.** Only the container that consumes
   the flag needs to be rebuilt — the rest of the stack keeps running.

   ```sh
   # Recreate the backend so the new env value reaches it.
   docker compose up -d --force-recreate --no-deps backend
   ```

   `--no-deps` prevents the cascade through `depends_on`; `--force-recreate`
   is required so the new env actually replaces the running container's
   frozen environment.

   For multi-service flags (rare), pass the service list instead:

   ```sh
   docker compose up -d --force-recreate --no-deps backend mqtt-subscriber
   ```

3. **Verify the flag landed.** Either call an endpoint that gates on the
   flag, or exec into the container and read its environment:

   ```sh
   docker compose exec backend printenv FEATURE_CMDB_PHYSICAL_LINK_POLLING_ENABLED
   # → true (when enabled in .env)
   # → false (when unset; the ${VAR:-false} default kicks in)
   ```

## How flags are wired

Three layers determine the value a flag takes inside a container, in
order from lowest to highest precedence:

| Layer | Where | What it does |
|-------|-------|--------------|
| 1 | `${VAR:-default}` in `docker-compose.yml` `environment:` | Provides the default when neither `.env` nor the shell override the var. |
| 2 | `env_file: .env` in `docker-compose.yml` | Reads the per-environment `.env` file and merges its values into the container env. The `frontend` service is excluded (build-time only, Vite context). |
| 3 | Process environment at `docker compose up` time | The shell env wins over both — useful for ad-hoc overrides (`VAR=foo docker compose up -d ...`). |

This contract is enforced by:

- `scripts/test-compose-env-file.sh` — asserts every owned service
  declares `env_file: [.env]`, the new flags are wired into
  `docker-compose.yml`, the literal `true` toggles are converted, and
  `.env.example` documents the new flag.
- `scripts/validate-env.sh` — fails on any var named in `.env.example`
  that is missing from `.env` (exit 10). Sensitive vars get extra
  checks; non-sensitive empty vars warn-only.

## When you DO need a PR

A pull request is still required when the flag is **new** (not yet in
`.env.example` or `docker-compose.yml`). The PR is small: one line in
`docker-compose.yml` near the existing flag entries, an 8-12 line
comment block in `.env.example` mirroring the precedent below, and a
cross-link in `docs/USER_GUIDE.md`.

The canonical precedent is commit `f8181cad` —
`chore(infra): wire FEATURE_CMDB_PROPOSALS_ENABLED into compose, env,
docs`. Touches `docker-compose.yml`, `.env.example`, and
`docs/USER_GUIDE.md`. Mirror that pattern for any new flag.

## References

- [Issue #546](https://github.com/alexandervazquez98/next-gen/issues/546)
  — original report and context.
- `f8181cad` — canonical precedent commit (the pattern this runbook
  codifies).
- `scripts/test-compose-env-file.sh` — the static check that enforces
  the contract on every PR.
- `scripts/validate-env.sh` — required-var enforcement and sensitive-var
  guards.
- `.github/workflows/smoke.yml` (lines 160-180) — canonical
  `.env.example → .env` materialization pattern used by CI.
- `docs/USER_GUIDE.md` — end-user-facing flag activation walk-through
  (Spanish).