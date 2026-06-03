# Verify Report PR5 — fix-multi-window-session-timeout

## Status

PASS for PR5 local hardening scope.

## Scope

Stack continuation after PR4 (#253): `fix/session-stack-hardening` targets `fix/session-inactivity-frontend`.

PR5 is intentionally small and non-backend:

- Bound `sessionBus` remote-event dedupe memory by TTL and max key count.
- Preserve duplicate suppression when both `BroadcastChannel` and `localStorage` deliver the same event.
- Add best-effort frontend session-id enrichment for terminal auth-failure `session-expired` events when a readable `access_token` JWT payload includes `sid`.
- Do not change backend refresh/token/rate-limit semantics.

## Strict TDD Evidence

| Phase | Evidence |
| --- | --- |
| RED | Added tests for sessionBus TTL/cap dedupe and API terminal auth-failure session-id enrichment before implementation. Initial focused run failed as expected for missing hardening behavior; the run also exposed a temporary test syntax typo that was corrected before GREEN. Targeted failures included TTL duplicate still suppressed after expiry and cap constants/behavior unavailable. |
| GREEN | Implemented `Map<string, number>`-based dedupe with 10-minute TTL and 256-key cap in `frontend/services/sessionBus.ts`; added safe JWT payload parsing in `frontend/services/api.ts` and included `sessionId` in terminal `session-expired` events when derivable. |
| TRIANGULATE | Focused frontend command passed: `corepack pnpm --dir frontend run test:run -- sessionBus.test.ts api.test.ts AuthContext.test.tsx` → **43 files passed / 407 tests passed**. |
| REFACTOR | Kept PR5 to frontend hardening + verification docs only; no backend/API contract change and no broad bus redesign. |

## Commands Run

### RED

```bash
cd /c/Users/polop/OneDrive/PROGRAMMING/next-gen-issues && corepack pnpm --dir frontend run test:run -- sessionBus.test.ts api.test.ts AuthContext.test.tsx
```

Observed failures before implementation included:

- `services/sessionBus.test.ts > expires remote-event dedupe keys after the TTL`
  - expected duplicate remote event to deliver again after TTL, but it remained suppressed.
- `services/sessionBus.test.ts > caps remote-event dedupe keys to prevent unbounded growth`
  - cap behavior/constants were not implemented.

### GREEN / Focused

```bash
cd /c/Users/polop/OneDrive/PROGRAMMING/next-gen-issues && corepack pnpm --dir frontend run test:run -- sessionBus.test.ts api.test.ts AuthContext.test.tsx
```

Result: **PASS — 43 files passed / 407 tests passed**.

### Final

```bash
cd /c/Users/polop/OneDrive/PROGRAMMING/next-gen-issues && corepack pnpm --dir frontend run test:run
```

Result: **PASS — 43 files passed / 407 tests passed**.

```bash
cd /c/Users/polop/OneDrive/PROGRAMMING/next-gen-issues && git diff --check
```

Result: **PASS**. Git reported only existing CRLF normalization warnings for edited frontend files.

## Manual Smoke Plan

Not run in this PR5 implementation pass. Recommended before merging the full stack:

1. Start or reuse the compose stack.
2. Open two browser tabs on the same frontend origin.
3. Login as the same non-persistent user/session.
4. Trigger idle timeout or revoke/expire the refresh session.
5. Verify both tabs converge to logged-out/login state without repeated redirects or refresh thrash.
6. Verify repeated cross-tab `session-expired`/`logout` events do not cause duplicate user-visible effects.

## PostgreSQL Validation Plan

Not run in this PR5 implementation pass. Recommended non-destructive validation before merging/deploying the full backend stack:

```bash
docker compose -f docker-compose.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d refresh_tokens"
docker compose -f docker-compose.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT column_name FROM information_schema.columns WHERE table_name='refresh_tokens' ORDER BY column_name;"
docker compose -f docker-compose.yml logs --tail=200 backend
```

Expected schema fields from PR1/PR2 include `session_id`, `policy_profile`, `last_activity_at`, `rotated_at`, `replaced_by_token_id`, `revoked_reason`, and `stale_recovery_count`.

## Risks / Remaining Issues

- Session-id enrichment is best-effort only: production HttpOnly cookies are intentionally not readable by JavaScript, so many real terminal events may still omit `sessionId` and fall back to broad session-expired handling.
- Dedupe TTL/cap values are conservative (`10m`, `256` keys). If auth-event volume grows significantly, tune with production telemetry.
- Manual two-tab and PostgreSQL checks remain planned, not completed, unless this report is updated with actual command/browser evidence.
