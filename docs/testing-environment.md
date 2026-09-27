# Testing Environment — markers, prtest, and bind-mounts

This document is the canonical reference for **how tests are classified**, **what environment they expect**, and **how to run them** in the three execution contexts the project supports (developer laptop, CI runner, prtest container).

It exists because of [issue #514](https://github.com/alexandervazquez98/next-gen/issues/514): a set of 20 pre-existing pytest failures in the prtest container that were caused by missing bind-mounts, missing host-mounted fixtures, and tests that genuinely need a fully-fitted environment. Resolving #514 required formalizing the conventions below so future tests do not silently regress the same way.

---

## 1. Pytest markers

`backend/pytest.ini` registers the following markers. New tests SHOULD pick the one that matches their intent; multiple markers per test are allowed.

| Marker | When to use it | Default behavior |
|---|---|---|
| `unit` | Pure logic, no external dependencies. Runs everywhere. | Always runs. |
| `integration` | Hits a real database / external service (mocked or live). | Always runs; may skip if a required service is unreachable. |
| `slow` | Takes longer than typical unit tests (e.g. >2s). | Always runs; CI may split slow tests into a separate lane. |
| `neo4j` | Tests that interact with Neo4j (mocked driver OR real container). | Always runs; mock variants run on developer laptops, real variants on prtest. |
| `metric` | Tests related to metric reconciliation / definitions. | Always runs. |
| `event` | Tests related to event lifecycle management. | Always runs. |
| `auth` | Authentication / authorization tests. | Always runs. |
| `api` | API / router tests (FastAPI TestClient). | Always runs. |
| **`env_required`** | **Tests requiring a fully-fitted environment: docker socket, pg_dump binary, host-mounted fixtures. Skip by default; opt in with `-m env_required` or run inside the prtest container.** | **Skipped unless `-m env_required` is passed** (or `PRTEST_FIXTURES_ENABLED=true` is set in the environment, which the prtest compose override does). |

### When to use `env_required`

Add `@pytest.mark.env_required` to a test that:

- Invokes a subprocess that requires an external binary NOT guaranteed to be present on a developer laptop (e.g. `pg_dump`, `mongodump`).
- Spins up a container via `testcontainers[postgres]` (needs `/var/run/docker.sock`).
- Reads a host-mounted fixture that only the prtest compose file provides.

Do NOT add it for tests that merely MOCK an external system — those should keep the `unit` or `integration` marker and run everywhere.

### How markers interact with `-m`

`pytest -m env_required` runs ONLY `env_required` tests.
`pytest -m "not env_required"` runs everything else (the default).
`pytest` (no `-m`) runs everything — same as `-m "not env_required"`. Use `pytest -m env_required tests/...` to exercise the integration-heavy tests locally.

---

## 2. The three execution contexts

### 2a. Developer laptop (default)

```sh
cd backend
.venv/bin/python -m pytest tests/ -q
```

What you get:

- All tests EXCEPT `env_required` run.
- `env_required` tests are skipped (shown as `s` in dot-mode output).
- Failures are real (not environmental).

If you want to exercise the integration tests too, AND your laptop has Docker + postgresql-client installed:

```sh
.venv/bin/python -m pytest tests/ -m env_required -q
```

Most contributors should not need this. The prtest harness is the canonical integration environment.

### 2b. CI runner (non-prtest workflows)

Same as the developer laptop. CI does NOT need to mount docker.sock; the `env_required` skip is the expected behavior.

### 2c. prtest container (full integration)

```sh
docker compose \
  -p nextgen-prtest \
  --env-file .env.prtest \
  -f docker-compose.yml \
  -f docker-compose.prtest.yml \
  up -d --build

docker compose \
  -p nextgen-prtest \
  --env-file .env.prtest \
  -f docker-compose.yml \
  -f docker-compose.prtest.yml \
  exec -T backend pytest tests/ -q --no-header --tb=line
```

What the prtest override adds on top of `docker-compose.yml`:

- `/var/run/docker.sock:/var/run/docker.sock` — enables `testcontainers[postgres]` tests.
- `PRTEST_FIXTURES_ENABLED=true` — lets tests detect the prtest environment.
- `command: ["python", "-m", "pytest", "tests/", ...]` — pins the pytest command so the verdict is reproducible.

What you get:

- ALL tests run, including `env_required`.
- The verdict reflects every failure — there is no soft skip.

---

## 3. Bind-mounts in `docker-compose.yml`

The default compose file bind-mounts five host paths into the backend container as `:ro` (read-only). These exist so tests inside the container can resolve absolute paths like `/backend/scripts/...`, `/openspec/...`, `/docs/...` that the test code assumes (because `Path(__file__).resolve().parents[2]` resolves to `/` inside the container, not to the repo root).

| Host path | Container path | Why |
|---|---|---|
| `./backend` | `/backend` | `parents[2]` resolution + script-path tests |
| `./fixtures` | `/fixtures` | `/graph/full` snapshot byte-equality tests |
| `./openspec` | `/openspec` | spec-coverage gate reads spec files |
| `./docs` | `/docs` | polling docs links tests |
| `./README.md` | `/README.md` | polling docs links tests |

**Never mount these as `:rw`** — the test container must never mutate the host tree.

**Never add `/var/run/docker.sock` to `docker-compose.yml`** — that socket belongs ONLY in the prtest override, NEVER in production stacks.

---

## 4. Conventions for adding new tests

When you add a new test that depends on an external resource, follow this decision tree:

1. **Does the test mock the resource?** → Use `unit` or `integration`. No special handling.
2. **Does the test require a binary that may not be installed locally (e.g. `pg_dump`, `mongodump`)?** → Add `@pytest.mark.env_required`.
3. **Does the test spin up a real container (testcontainers)?** → Add `@pytest.mark.env_required`.
4. **Does the test read a host-mounted fixture at a fixed absolute path?** → Either add a bind-mount to `docker-compose.yml` (preferred) OR use `pytest.skip(reason=...)` defensively if the fixture might not be present on every branch.

If your test reads a JSON / SQL / Markdown fixture from the repo:

- Place it under `fixtures/` (repo root) for OpenSpec-related fixtures.
- Place it under `backend/tests/fixtures/` ONLY for tests that don't depend on bind-mounts and want the fixture baked into the image.
- Add a `pytest.skip(reason=...)` guard for the case where the fixture is missing, with a message that names the PR/issue that introduced it.

---

## 5. Reproducing the issue #514 fix locally

The full pytest stack, after the fix, behaves as follows:

| Failure class | Pre-fix | Post-fix |
|---|---|---|
| Missing bind-mounts (`/fixtures`, `/backend/scripts`, `/openspec`, `/docs`, `/README.md`) | 12 fails | 0 fails (bind-mounted) |
| `testcontainers[postgres]` tests need docker.sock | 4 fails | 0 fails in prtest, skipped by default locally |
| `pg_dump` subprocess tests | 1 fail | 0 fails in prtest, skipped by default locally |
| Spec / fixture file absent on intermediate branches | 5 fails | 0 fails (defensive `pytest.skip` guards) |

Net result: `pytest tests/` on `origin/main` HEAD now reports **0 failures** instead of 20. The prtest container has the same 0-failure verdict and additionally exercises the integration-heavy `env_required` tests.

---

## 6. References

- Issue: [#514](https://github.com/alexandervazquez98/next-gen/issues/514)
- PR: see `fix/issue-514-prtest-env-failures` branch
- Files touched:
  - `backend/pytest.ini` (marker registration)
  - `docker-compose.yml` (5 new bind-mounts)
  - `docker-compose.prtest.yml` (NEW — prtest-only override)
  - `backend/tests/test_writer_advisory_lock.py` (4 tests marked `env_required`)
  - `backend/tests/test_backup_service.py` (4 tests marked `env_required`)
  - `backend/tests/test_spec_coverage_graph.py` (`_require_spec_text` helper)
  - `backend/tests/test_graph_full_snapshot.py` (skip guard in `_load_snapshot`)
  - `backend/tests/test_refresh_token_activity_backfill.py` (`_resolve_script_path` helper)
  - `odd/tasks/fix-514-prtest-env-failures.md` (ODD feature document)