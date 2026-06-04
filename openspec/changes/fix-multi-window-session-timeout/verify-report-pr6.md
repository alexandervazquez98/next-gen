# Verify Report PR6 — fix-multi-window-session-timeout

## Status

PASS for the non-destructive validation slice, with residual manual/browser and populated-data validation tasks explicitly listed below.

## Scope

Stack continuation after PR5 (#255): `fix/session-stack-validation` targets `fix/session-stack-hardening`.

PR6 is validation/evidence only:

- confirm running Docker services are healthy;
- verify the PostgreSQL `refresh_tokens` table has the PR1/PR2 session metadata columns and indexes;
- run focused backend auth/session tests against the current stack branch;
- run focused frontend session tests against the current stack branch;
- verify the frontend and backend public surfaces respond without requiring a destructive environment reset.

No application code was changed in this PR6 slice.

## Strict TDD / Validation Evidence

PR6 does not add product behavior, so there is no RED/GREEN code cycle. It is a verification-only slice. Evidence is command-based and non-destructive.

| Check | Evidence |
| --- | --- |
| Docker services | `nexgen_postgres`, `nexgen_backend`, and `nexgen_frontend` reported `healthy`. |
| PostgreSQL schema | `refresh_tokens` contains session metadata columns: `session_id`, `policy_profile`, `last_activity_at`, `rotated_at`, `replaced_by_token_id`, `revoked_reason`, `stale_recovery_count`. |
| PostgreSQL indexes | Session/policy indexes exist: `ix_refresh_tokens_session_id`, `ix_refresh_tokens_policy_profile`, plus token/user indexes. |
| Backend session/auth tests | `python -m pytest backend/tests/test_session_policy.py backend/tests/test_auth_service_refresh.py backend/tests/test_auth_router_refresh.py` passed: **53 passed**. |
| Frontend session tests | `corepack pnpm --dir frontend run test:run -- sessionBus.test.ts api.test.ts AuthContext.test.tsx` passed: **43 files passed / 407 tests passed**. |
| Frontend serving | `curl http://localhost:3000/` returned **200**. |
| Auth protection surface | `curl http://localhost:8000/api/auth/users/me` returned **401** with `{"detail":"Not authenticated"}`. |

## Commands Run

### Docker health

```bash
docker inspect --format '{{.Name}} {{.State.Health.Status}}' nexgen_postgres nexgen_backend nexgen_frontend
```

Result:

```text
/nexgen_postgres healthy
/nexgen_backend healthy
/nexgen_frontend healthy
```

### PostgreSQL columns

```bash
docker exec nexgen_postgres psql -U nexgen_admin -d nexgen_auth -c "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='refresh_tokens' ORDER BY ordinal_position;"
```

Result excerpt:

```text
 id                   | integer                     | NO
 user_id              | integer                     | NO
 token_hash           | character varying           | NO
 created_at           | timestamp without time zone | NO
 expires_at           | timestamp without time zone | NO
 revoked_at           | timestamp without time zone | YES
 session_id           | character varying           | YES
 policy_profile       | character varying           | YES
 last_activity_at     | timestamp without time zone | YES
 rotated_at           | timestamp without time zone | YES
 replaced_by_token_id | integer                     | YES
 revoked_reason       | character varying           | YES
 stale_recovery_count | integer                     | YES
```

### PostgreSQL indexes

```bash
docker exec nexgen_postgres psql -U nexgen_admin -d nexgen_auth -c "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='refresh_tokens' ORDER BY indexname;"
```

Result excerpt:

```text
ix_refresh_tokens_policy_profile | CREATE INDEX ix_refresh_tokens_policy_profile ON public.refresh_tokens USING btree (policy_profile)
ix_refresh_tokens_session_id     | CREATE INDEX ix_refresh_tokens_session_id ON public.refresh_tokens USING btree (session_id)
ix_refresh_tokens_token_hash     | CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON public.refresh_tokens USING btree (token_hash)
ix_refresh_tokens_user_id        | CREATE INDEX ix_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id)
```

### PostgreSQL metadata count

```bash
docker exec nexgen_postgres psql -U nexgen_admin -d nexgen_auth -c "SELECT COUNT(*) AS total, COUNT(session_id) AS with_session_id, COUNT(policy_profile) AS with_policy_profile, COUNT(last_activity_at) AS with_last_activity_at, COUNT(stale_recovery_count) AS with_stale_recovery_count FROM refresh_tokens;"
```

Result:

```text
total | with_session_id | with_policy_profile | with_last_activity_at | with_stale_recovery_count
------+-----------------+---------------------+-----------------------+--------------------------
0     | 0               | 0                   | 0                     | 0
```

Interpretation: the table is empty in the current local Docker database, so this validates schema/index readiness but not live-row backfill contents.

### Backend log scan

```bash
docker logs --tail=200 nexgen_backend 2>&1 | grep -Ei 'refresh_tokens|migration|ALTER TABLE|ERROR|Traceback' | tail -80
```

Result: no matching migration/error/traceback lines in the last 200 backend log lines.

### Backend auth/session test matrix

```bash
cd /c/Users/polop/OneDrive/PROGRAMMING/next-gen-issues && python -m pytest backend/tests/test_session_policy.py backend/tests/test_auth_service_refresh.py backend/tests/test_auth_router_refresh.py
```

Result: **53 passed**, with deprecation warnings only.

### Frontend session test matrix

```bash
cd /c/Users/polop/OneDrive/PROGRAMMING/next-gen-issues && corepack pnpm --dir frontend run test:run -- sessionBus.test.ts api.test.ts AuthContext.test.tsx
```

Result: **43 files passed / 407 tests passed**.

### HTTP surface checks

```bash
curl -sS -o /tmp/frontend.txt -w '%{http_code}' http://localhost:3000/
curl -sS -o /tmp/me.txt -w '%{http_code}' http://localhost:8000/api/auth/users/me
```

Note: `/tmp/...` paths reflect the Git Bash/Linux-style shell used for validation; any temporary output path is equivalent.

Results:

- Frontend `/`: **200**.
- Unauthenticated `/api/auth/users/me`: **401**, body `{"detail":"Not authenticated"}`.

## Manual Two-Tab Smoke

Not completed in PR6. The Docker/frontend/backend surfaces are healthy and ready for this check, but actual browser two-tab interaction still requires a human/browser pass.

Recommended manual steps before merging/deploying the full stack:

1. Open `http://localhost:3000/` in two tabs on the same browser profile.
2. Login as the same non-persistent user/session.
3. Trigger idle timeout or revoke/expire the refresh session.
4. Verify both tabs converge to logged-out/login state without repeated redirects or refresh thrash.
5. Verify repeated cross-tab `session-expired`/`logout` events do not cause duplicate user-visible effects.

## Risks / Remaining Issues

- Live-row backfill was not proven because local `refresh_tokens` currently has zero rows.
- Manual two-tab UX was not completed; PR4/PR5 unit tests cover the mechanics, but browser-level convergence should still be smoke-tested before deployment.
- Docker compose emitted warnings about unset Neo4j/JWT/Cookie variables when queried via `docker compose ps --format json` before direct container inspection. The already-running containers inspected in this report were healthy. Warning excerpt:

```text
The "NEO4J_URI" variable is not set. Defaulting to a blank string.
The "NEO4J_USER" variable is not set. Defaulting to a blank string.
The "NEO4J_PASSWORD" variable is not set. Defaulting to a blank string.
The "JWT_SECRET_KEY" variable is not set. Defaulting to a blank string.
The "COOKIE_DOMAIN" variable is not set. Defaulting to a blank string.
```
